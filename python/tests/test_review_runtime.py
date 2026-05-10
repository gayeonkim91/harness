from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

import harness.shared.runtime.review_runtime as review_runtime
from harness.runtime_cli import main
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.results import JudgementCode, ReviewResult
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode
from harness.shared.core.diff_helper import build_task_scoped_diff, compute_task_diff_fingerprint
from harness.shared.core.snapshot_helper import capture_workspace_baseline
from harness.shared.runtime.review_runtime import ReviewRuntimeInput, persist_review_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)


def _workspace_with_review_state(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "logs").mkdir()
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    _write_plan(task_root)
    verification_ref = _write_verification(task_root, baseline_ref)
    _write_state(task_root, baseline_ref, verification_ref)
    return workspace, task_root, baseline_ref


def _write_plan(task_root: Path) -> None:
    (task_root / "plan.md").write_text(
        "# Plan\n\n## Goal\nReview goal.\n\n## Scope\nReview scope.\n\n## DoD\n- [ ] Done\n",
        encoding="utf-8",
    )


def _write_verification(task_root: Path, baseline_ref: str) -> str:
    diff = build_task_scoped_diff(task_root, baseline_ref)
    fingerprint = compute_task_diff_fingerprint(diff)
    ref = "logs/verification/verification.json"
    path = task_root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "verification_ref": ref,
                "judgement_code": "GO",
                "summary": "Verified.",
                "verification_items": [],
                "basis_refs": ["logs/test-output.txt"],
                "note_signals": [],
                "verified_task_diff_fingerprint": fingerprint,
                "stop_condition_code": None,
                "primary_cause_code": None,
                "reason_fingerprint": None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return ref


def _write_state(
    task_root: Path,
    baseline_ref: str | None,
    verification_ref: str | None,
    *,
    phase: CurrentPhase = CurrentPhase.REVIEW,
    current_step_ref: str | None = None,
) -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=phase,
            repo_profile_ref=None,
            workspace_baseline_ref=baseline_ref,
            current_step_ref=current_step_ref,
            latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
            latest_verification_ref=verification_ref,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )


def _review_result(judgement: JudgementCode = JudgementCode.DONE) -> ReviewResult:
    is_blocking = judgement in {JudgementCode.REWORK, JudgementCode.REWRITE_PLAN, JudgementCode.HOLD}
    return ReviewResult(
        review_ref="",
        judgement_code=judgement,
        summary="Review passed.",
        out_of_scope_change=False,
        key_issues=["Blocking review issue."] if is_blocking else [],
        verification_blind_spots=[],
        carry_forward_notes=["Document final caution."] if judgement == JudgementCode.DONE_WITH_NOTE else [],
        basis_refs=["logs/verification/verification.json"],
        primary_cause_code="review_issue" if is_blocking else None,
        reason_fingerprint="review_issue" if is_blocking else None,
    )


def _review_result_payload() -> dict[str, object]:
    return {
        "review_ref": "",
        "judgement_code": "DONE",
        "summary": "Review passed.",
        "out_of_scope_change": False,
        "key_issues": [],
        "verification_blind_spots": [],
        "carry_forward_notes": [],
        "basis_refs": ["logs/verification/verification.json"],
        "verified_task_diff_fingerprint": None,
    }


def test_persist_review_runtime_blocks_plan_mirror_read_error_as_invalid_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_state(task_root, "logs/workspace-baseline.json", "logs/verification/verification.json")
    original_state = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    (task_root / "plan.md").mkdir()

    result = persist_review_runtime(
        ReviewRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            review_result=_review_result(),
        )
    )

    assert result["reason_code"] == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_state
    assert not (task_root / "logs" / "review").exists()


def test_persist_review_runtime_writes_log_and_updates_state(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    review_ref = result["review_ref"]
    state = read_state(task_root / "state.json")
    payload = json.loads((task_root / str(review_ref)).read_text(encoding="utf-8"))

    assert result["reason_code"] is None
    assert state.latest_review_ref == review_ref
    assert not Path(str(review_ref)).is_absolute()
    assert payload["review_ref"] == review_ref
    assert payload["judgement_code"] == "DONE"
    assert payload["verified_task_diff_fingerprint"].startswith("sha256:")


def test_persist_review_runtime_reports_state_update_failure(monkeypatch, tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)

    writes = {"count": 0}

    def fail_first_write_state(*args, **kwargs):
        writes["count"] += 1
        if writes["count"] == 1:
            raise OSError("state write failed")
        return write_state(*args, **kwargs)

    monkeypatch.setattr(review_runtime, "write_state", fail_first_write_state)

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "REVIEW_STATE_UPDATE_FAILED"
    assert result["review_ref"] is not None
    assert result["latest_review_ref"] is None
    assert result["recovery_ref"].startswith("logs/review-recovery/")
    assert result["recovery_record_persisted"] is True
    assert result["blocked_state_persisted"] is True
    assert result["verified_task_diff_fingerprint"].startswith("sha256:")
    assert state.latest_review_ref is None
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_transition == "review_state_update"
    assert state.blocked_reason_ref == result["review_ref"]
    assert (task_root / str(result["review_ref"])).exists()
    recovery_payload = json.loads((task_root / str(result["recovery_ref"])).read_text(encoding="utf-8"))
    assert recovery_payload["record_type"] == "review_state_update_recovery"
    assert recovery_payload["status"] == "unresolved"
    assert recovery_payload["orphan_result_ref"] == result["review_ref"]
    assert recovery_payload["attempted_pointer_field"] == "latest_review_ref"


def test_persist_review_runtime_returns_structured_result_when_block_state_update_also_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)

    def fail_write_state(*args, **kwargs):
        raise OSError("state write failed")

    monkeypatch.setattr(review_runtime, "write_state", fail_write_state)

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "REVIEW_STATE_UPDATE_FAILED"
    assert result["blocked_state_persisted"] is False
    assert result["recovery_ref"].startswith("logs/review-recovery/")
    assert state.blocked_transition is None
    assert state.latest_review_ref is None


def test_persist_review_runtime_returns_structured_result_when_recovery_record_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    monkeypatch.setattr(review_runtime, "record_state_update_recovery", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("recovery write failed")))
    monkeypatch.setattr(review_runtime, "write_state", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("state write failed")))

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    assert result["reason_code"] == "REVIEW_STATE_UPDATE_FAILED"
    assert result["recovery_ref"] is None
    assert result["recovery_record_persisted"] is False
    assert result["blocked_state_persisted"] is False
    assert result["review_ref"] is not None


def test_persist_review_runtime_clears_previous_review_execution_block_on_success(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    verification_ref = read_state(task_root / "state.json").latest_verification_ref
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.REVIEW,
            repo_profile_ref=None,
            workspace_baseline_ref=baseline_ref,
            current_step_ref=None,
            latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
            latest_verification_ref=verification_ref,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition="review_execution",
            blocked_reason_ref="logs/review-failures/failed.json",
            stop_condition_ref="logs/stop.json",
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] is None
    assert state.blocked_transition is None
    assert state.blocked_reason_ref is None
    assert state.stop_condition_ref == "logs/stop.json"


def test_persist_review_runtime_clears_previous_state_update_block_on_success(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    verification_ref = read_state(task_root / "state.json").latest_verification_ref
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.REVIEW,
            repo_profile_ref=None,
            workspace_baseline_ref=baseline_ref,
            current_step_ref=None,
            latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
            latest_verification_ref=verification_ref,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition="review_state_update",
            blocked_reason_ref="logs/review/orphan.json",
            stop_condition_ref="logs/stop.json",
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] is None
    assert state.latest_review_ref == result["review_ref"]
    assert state.blocked_transition is None
    assert state.blocked_reason_ref is None
    assert state.stop_condition_ref == "logs/stop.json"


def test_persist_review_runtime_blocks_stale_verification_without_log(tmp_path: Path) -> None:
    workspace, task_root, _ = _workspace_with_review_state(tmp_path)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    assert result["reason_code"] == "REVIEW_VERIFICATION_STALE"
    assert list((task_root / "logs" / "review").glob("*.json")) == []
    assert read_state(task_root / "state.json").session_state == SessionState.IN_PROGRESS


def test_persist_review_runtime_blocks_missing_verification_ref(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    _write_state(task_root, baseline_ref, None)

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    assert result["reason_code"] == "REVIEW_VERIFICATION_REF_MISSING"
    assert result["message_summary"] == "`/wf-review` requires latest verification ref."
    assert read_state(task_root / "state.json").session_state == SessionState.IN_PROGRESS


def test_persist_review_runtime_guard_reason_matrix_without_record_or_state_change(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    verification_ref = read_state(task_root / "state.json").latest_verification_ref
    cases = [
        ("missing-workspace-root", None, baseline_ref, verification_ref, CurrentPhase.REVIEW, None, "REVIEW_WORKSPACE_ROOT_MISSING"),
        ("missing-state", REPO_ROOT, baseline_ref, verification_ref, CurrentPhase.REVIEW, None, "STATE_ARTIFACT_MISSING"),
        ("wrong-phase", REPO_ROOT, baseline_ref, verification_ref, CurrentPhase.PLAN, None, "REVIEW_PHASE_MISMATCH"),
        ("current-step", REPO_ROOT, baseline_ref, verification_ref, CurrentPhase.REVIEW, "S1", "REVIEW_CURRENT_STEP_REF_INVALID"),
        ("missing-baseline", REPO_ROOT, None, verification_ref, CurrentPhase.REVIEW, None, "REVIEW_WORKSPACE_BASELINE_MISSING"),
        ("missing-plan", REPO_ROOT, baseline_ref, verification_ref, CurrentPhase.REVIEW, None, "PLAN_ARTIFACT_MISSING"),
    ]
    for label, workspace_root, baseline, verification, phase, current_step_ref, expected in cases:
        case_root = task_root.parent / f"case-{label}"
        case_root.mkdir()
        (case_root / "logs").mkdir()
        if label != "missing-state":
            if label != "missing-plan":
                _write_plan(case_root)
            _write_state(case_root, baseline, verification, phase=phase, current_step_ref=current_step_ref)

        result = persist_review_runtime(
            ReviewRuntimeInput(task_root=case_root, workspace_root=workspace_root, review_result=_review_result())
        )

        assert result["reason_code"] == expected
        assert not (case_root / "logs" / "review").exists()
        assert not (case_root / "logs" / "review-failures").exists()
        if label != "missing-state":
            assert read_state(case_root / "state.json").session_state == SessionState.IN_PROGRESS


def test_persist_review_runtime_blocks_invalid_session_and_pending_without_record(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    verification_ref = read_state(task_root / "state.json").latest_verification_ref
    for label, session_state, pending_approval_for, expected in [
        ("paused", SessionState.PAUSED, None, "REVIEW_SESSION_STATE_INVALID"),
        ("pending", SessionState.IN_PROGRESS, "closure", "REVIEW_PENDING_APPROVAL_INVALID"),
    ]:
        case_root = task_root.parent / f"case-{label}"
        case_root.mkdir()
        (case_root / "logs").mkdir()
        _write_plan(case_root)
        write_state(
            case_root / "state.json",
            HarnessState(
                schema_version=1,
                session_state=session_state,
                workflow_mode=WorkflowMode.GENERIC,
                current_phase=CurrentPhase.REVIEW,
                repo_profile_ref=None,
                workspace_baseline_ref=baseline_ref,
                current_step_ref=None,
                latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
                latest_verification_ref=verification_ref,
                latest_review_ref=None,
                pending_approval_for=pending_approval_for,
                review_outcome=None,
                closure_authorized=False,
                counters=HarnessCounters(),
                blocked_transition=None,
                blocked_reason_ref=None,
                stop_condition_ref=None,
                last_updated="2026-04-19T22:00:00+09:00",
                adapter_meta={},
            ),
        )

        result = persist_review_runtime(
            ReviewRuntimeInput(task_root=case_root, workspace_root=REPO_ROOT, review_result=_review_result())
        )

        assert result["reason_code"] == expected
        assert not (case_root / "logs" / "review-failures").exists()


def test_persist_review_runtime_blocks_diff_failure_without_record(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_review_state(tmp_path)
    (task_root / baseline_ref).unlink()

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    assert result["reason_code"] == "REVIEW_DIFF_UNAVAILABLE"
    assert not (task_root / "logs" / "review-failures").exists()


def test_persist_review_runtime_rejects_out_of_scope_done(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result()
    review.out_of_scope_change = True

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))
    state = read_state(task_root / "state.json")
    failure_payload = json.loads((task_root / str(result["review_failure_ref"])).read_text(encoding="utf-8"))

    assert result["reason_code"] == "REVIEW_OUT_OF_SCOPE_INVALID"
    assert result["latest_review_ref"] is None
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_transition == "review_execution"
    assert state.blocked_reason_ref == result["review_failure_ref"]
    assert state.latest_review_ref is None
    assert failure_payload["record_type"] == "review_failure"
    assert failure_payload["reason_code"] == "REVIEW_OUT_OF_SCOPE_INVALID"
    assert "logs/review-failures/" in result["review_failure_ref"]


def test_persist_review_runtime_requires_key_issues_for_blocking_judgement(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.REWORK)
    review.key_issues = []

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "REVIEW_KEY_ISSUES_REQUIRED"
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_rejects_blank_key_issues_for_blocking_judgement(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.REWORK)
    review.key_issues = [" "]

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "REVIEW_KEY_ISSUES_REQUIRED"
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_requires_carry_forward_notes_for_done_with_note(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.DONE_WITH_NOTE)
    review.carry_forward_notes = []

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_CARRY_FORWARD_NOTES_INVALID"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_rejects_blank_carry_forward_notes_for_done_with_note(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.DONE_WITH_NOTE)
    review.carry_forward_notes = [" "]

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_CARRY_FORWARD_NOTES_INVALID"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_requires_reason_for_blocking_judgement(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.HOLD)
    review.primary_cause_code = None

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_REASON_REQUIRED"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_rejects_whitespace_blocking_reason(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.HOLD)
    review.primary_cause_code = "review_issue"
    review.reason_fingerprint = " "

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_REASON_REQUIRED"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_requires_summary(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result()
    review.summary = ""

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_RESULT_CONTRACT_INVALID"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_rejects_blank_verification_blind_spot(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result()
    review.verification_blind_spots = [" "]

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_VERIFICATION_BLIND_SPOTS_INVALID"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_rejects_review_rewrite_step_from_phase_spec(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    review = _review_result(JudgementCode.REWRITE_STEP)

    result = persist_review_runtime(ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=review))

    assert result["reason_code"] == "REVIEW_JUDGEMENT_INVALID"
    assert read_state(task_root / "state.json").blocked_reason_ref == result["review_failure_ref"]


def test_persist_review_runtime_treats_null_verification_fingerprint_as_unreadable(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    state = read_state(task_root / "state.json")
    verification_path = task_root / str(state.latest_verification_ref)
    payload = json.loads(verification_path.read_text(encoding="utf-8"))
    payload["verified_task_diff_fingerprint"] = None
    verification_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=_review_result())
    )

    assert result["reason_code"] == "REVIEW_VERIFICATION_REF_UNREADABLE"
    assert read_state(task_root / "state.json").session_state == SessionState.IN_PROGRESS


@pytest.mark.parametrize(
    ("mutate", "message_fragment", "reason_code"),
    [
        (
            lambda result: result.update({"judgement_code": None}),
            "review_result.judgement_code",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"judgement_code": "INVALID"}),
            "review_result.judgement_code",
            "REVIEW_JUDGEMENT_INVALID",
        ),
        (
            lambda result: result.update({"summary": None}),
            "review_result.summary",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"out_of_scope_change": "false"}),
            "review_result.out_of_scope_change",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"key_issues": [None]}),
            "review_result.key_issues[0]",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"verification_blind_spots": ["gap", 123]}),
            "review_result.verification_blind_spots[1]",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"carry_forward_notes": [123]}),
            "review_result.carry_forward_notes[0]",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"basis_refs": [None]}),
            "review_result.basis_refs[0]",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"primary_cause_code": 123}),
            "review_result.primary_cause_code",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
        (
            lambda result: result.update({"reason_fingerprint": 123}),
            "review_result.reason_fingerprint",
            "REVIEW_RESULT_CONTRACT_INVALID",
        ),
    ],
)
def test_review_runtime_records_failure_for_invalid_dict_result_contract_fields(
    tmp_path: Path,
    mutate,
    message_fragment: str,
    reason_code: str,
) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    payload = _review_result_payload()
    mutate(payload)

    result = persist_review_runtime(
        ReviewRuntimeInput(task_root=task_root, workspace_root=REPO_ROOT, review_result=payload)
    )
    state = read_state(task_root / "state.json")
    failure_payload = json.loads((task_root / str(result["review_failure_ref"])).read_text(encoding="utf-8"))

    assert result["reason_code"] == reason_code
    assert message_fragment in str(result["message_summary"])
    assert result["latest_review_ref"] is None
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_transition == "review_execution"
    assert state.blocked_reason_ref == result["review_failure_ref"]
    assert failure_payload["record_type"] == "review_failure"
    assert failure_payload["reason_code"] == reason_code
    assert failure_payload["review_output"] == payload


def test_runtime_cli_serializes_review_result(monkeypatch, capsys, tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    payload = {
        "task_root": str(task_root),
        "workspace_root": str(REPO_ROOT),
        "review_result": _review_result_payload(),
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-review-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["reason_code"] is None
    assert output["review_ref"].startswith("logs/review/")


def test_runtime_cli_records_review_failure_for_string_boolean_review_payload(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    _, task_root, _ = _workspace_with_review_state(tmp_path)
    payload = {
        "task_root": str(task_root),
        "workspace_root": str(REPO_ROOT),
        "review_result": _review_result_payload(),
    }
    payload["review_result"]["out_of_scope_change"] = "false"
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-review-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)
    state = read_state(task_root / "state.json")

    assert exit_code == 0
    assert output["reason_code"] == "REVIEW_RESULT_CONTRACT_INVALID"
    assert output["review_failure_ref"].startswith("logs/review-failures/")
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_transition == "review_execution"
