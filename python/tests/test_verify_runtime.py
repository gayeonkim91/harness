from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

import harness.shared.runtime.verify_runtime as verify_runtime
from harness.runtime_cli import main
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.results import (
    JudgementCode,
    NoteSignal,
    NoteTargetHint,
    VerificationItem,
    VerificationLintWarningCode,
    VerificationResult,
)
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode
from harness.shared.core.snapshot_helper import capture_workspace_baseline
from harness.shared.integrations.test_report_skill_bridge import (
    TEST_REPORT_STANDALONE_REF,
    TEST_REPORT_VERIFICATION_ASSIST_REF,
)
from harness.shared.runtime.verify_runtime import VerifyRuntimeInput, persist_verify_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)


def _workspace_with_baseline(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "logs").mkdir()
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    return workspace, task_root, baseline_ref


def _write_state(
    task_root: Path,
    baseline_ref: str | None,
    *,
    phase: CurrentPhase = CurrentPhase.VERIFICATION,
    session_state: SessionState = SessionState.IN_PROGRESS,
    pending_approval_for: str | None = None,
    current_step_ref: str | None = None,
    latest_checkpoint_ref: str | None = "logs/checkpoints/checkpoint.json",
    latest_verification_ref: str | None = None,
) -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=session_state,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=phase,
            repo_profile_ref=None,
            workspace_baseline_ref=baseline_ref,
            current_step_ref=current_step_ref,
            latest_checkpoint_ref=latest_checkpoint_ref,
            latest_verification_ref=latest_verification_ref,
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


def _write_plan(task_root: Path) -> None:
    (task_root / "plan.md").write_text("# Plan\n\n## Verification\n- Run checks.\n", encoding="utf-8")


def _verification_result(
    judgement: JudgementCode = JudgementCode.GO,
    *,
    note_signals: list[NoteSignal] | None = None,
    primary_cause_code: str | None = None,
    reason_fingerprint: str | None = None,
    basis_refs: list[str] | None = None,
    item_basis_refs: list[str] | None = None,
    item_key: str = "gate-tests",
    item_type: str = "gate",
    label: str = "Test suite",
    method: str = "pytest",
    item_summary: str = "All selected tests passed.",
) -> VerificationResult:
    resolved_basis_refs = basis_refs or ["logs/test-output.txt"]
    return VerificationResult(
        verification_ref="",
        judgement_code=judgement,
        summary="Verification passed.",
        verification_items=[
            VerificationItem(
                item_key=item_key,
                item_type=item_type,
                label=label,
                method=method,
                result="PASS",
                summary=item_summary,
                basis_refs=item_basis_refs or ["logs/test-output.txt"],
            )
        ],
        basis_refs=resolved_basis_refs,
        note_signals=note_signals or [],
        primary_cause_code=primary_cause_code,
        reason_fingerprint=reason_fingerprint,
    )


def _verification_result_payload() -> dict[str, object]:
    return {
        "verification_ref": "",
        "judgement_code": "GO",
        "summary": "Verification passed.",
        "verification_items": [
            {
                "item_key": "gate-tests",
                "item_type": "gate",
                "label": "Test suite",
                "method": "pytest",
                "result": "PASS",
                "summary": "All selected tests passed.",
                "basis_refs": ["logs/test-output.txt"],
            }
        ],
        "basis_refs": ["logs/test-output.txt"],
        "note_signals": [],
    }


def test_persist_verify_runtime_blocks_plan_mirror_read_error_as_invalid_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_state(task_root, "logs/workspace-baseline.json")
    original_state = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    (task_root / "plan.md").mkdir()

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_state
    assert not (task_root / "logs" / "verification").exists()


def test_persist_verify_runtime_writes_log_state_and_fingerprint(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    verification_ref = result["verification_ref"]
    state = read_state(task_root / "state.json")
    payload = json.loads((task_root / str(verification_ref)).read_text(encoding="utf-8"))

    assert result["reason_code"] is None
    assert state.latest_verification_ref == verification_ref
    assert not Path(str(verification_ref)).is_absolute()
    assert payload["verification_ref"] == verification_ref
    assert payload["judgement_code"] == "GO"
    assert payload["verified_task_diff_fingerprint"].startswith("sha256:")
    assert result["verified_task_diff_fingerprint"] == payload["verified_task_diff_fingerprint"]
    assert state.current_phase == CurrentPhase.VERIFICATION
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" in payload["lint_warnings"]


def test_persist_verify_runtime_reports_state_update_failure(monkeypatch, tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    writes = {"count": 0}

    def fail_first_write_state(*args, **kwargs):
        writes["count"] += 1
        if writes["count"] == 1:
            raise OSError("state write failed")
        return write_state(*args, **kwargs)

    monkeypatch.setattr(verify_runtime, "write_state", fail_first_write_state)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "VERIFY_STATE_UPDATE_FAILED"
    assert result["verification_ref"] is not None
    assert result["latest_verification_ref"] is None
    assert result["recovery_ref"].startswith("logs/verify-recovery/")
    assert result["recovery_record_persisted"] is True
    assert result["blocked_state_persisted"] is True
    assert result["verified_task_diff_fingerprint"].startswith("sha256:")
    assert state.latest_verification_ref is None
    assert state.session_state == SessionState.PAUSED
    assert state.blocked_transition == "verify_state_update"
    assert state.blocked_reason_ref == result["verification_ref"]
    assert (task_root / str(result["verification_ref"])).exists()
    recovery_payload = json.loads((task_root / str(result["recovery_ref"])).read_text(encoding="utf-8"))
    assert recovery_payload["record_type"] == "verify_state_update_recovery"
    assert recovery_payload["status"] == "unresolved"
    assert recovery_payload["orphan_result_ref"] == result["verification_ref"]
    assert recovery_payload["attempted_pointer_field"] == "latest_verification_ref"


def test_persist_verify_runtime_returns_structured_result_when_block_state_update_also_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    def fail_write_state(*args, **kwargs):
        raise OSError("state write failed")

    monkeypatch.setattr(verify_runtime, "write_state", fail_write_state)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] == "VERIFY_STATE_UPDATE_FAILED"
    assert result["blocked_state_persisted"] is False
    assert result["recovery_ref"].startswith("logs/verify-recovery/")
    assert state.blocked_transition is None
    assert state.latest_verification_ref is None


def test_persist_verify_runtime_returns_structured_result_when_recovery_record_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(verify_runtime, "record_state_update_recovery", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("recovery write failed")))
    monkeypatch.setattr(verify_runtime, "write_state", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("state write failed")))

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_STATE_UPDATE_FAILED"
    assert result["recovery_ref"] is None
    assert result["recovery_record_persisted"] is False
    assert result["blocked_state_persisted"] is False
    assert result["verification_ref"] is not None


def test_persist_verify_runtime_clears_previous_state_update_block_on_success(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    state = read_state(task_root / "state.json")
    state.blocked_transition = "verify_state_update"
    state.blocked_reason_ref = "logs/verification/orphan.json"
    write_state(task_root / "state.json", state)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )
    state = read_state(task_root / "state.json")

    assert result["reason_code"] is None
    assert state.latest_verification_ref == result["verification_ref"]
    assert state.blocked_transition is None
    assert state.blocked_reason_ref is None


def test_persist_verify_runtime_blocks_missing_baseline_without_log(tmp_path: Path) -> None:
    _, task_root, _ = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, None)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_WORKSPACE_BASELINE_MISSING"
    assert result["message_summary"] == "`/wf-verify` requires workspace baseline."
    assert list((task_root / "logs" / "verification").glob("*.json")) == []


def test_persist_verify_runtime_blocks_wrong_phase(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref, phase=CurrentPhase.PLAN)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_PHASE_MISMATCH"


def test_persist_verify_runtime_blocks_missing_basis_ref(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref, latest_checkpoint_ref=None, latest_verification_ref=None)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_BASIS_REF_MISSING"


def test_persist_verify_runtime_blocks_diff_failure_without_log(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (task_root / baseline_ref).unlink()

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_DIFF_UNAVAILABLE"
    assert list((task_root / "logs" / "verification").glob("*.json")) == []


def test_persist_verify_runtime_rejects_invalid_note_target(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                JudgementCode.GO_WITH_NOTE,
                note_signals=[
                    NoteSignal(
                        note_text="Carry to step.",
                        note_target_hint=NoteTargetHint.STEPS,
                        note_basis_refs=["verification.md#note"],
                    )
                ],
            ),
        )
    )

    assert result["reason_code"] == "VERIFY_NOTE_SIGNALS_INVALID"


def test_persist_verify_runtime_rejects_blank_note_signal_text(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                JudgementCode.GO_WITH_NOTE,
                note_signals=[
                    NoteSignal(
                        note_text=" ",
                        note_target_hint=NoteTargetHint.PLAN,
                        note_basis_refs=["verification.md#note"],
                    )
                ],
            ),
        )
    )

    assert result["reason_code"] == "VERIFY_NOTE_SIGNALS_INVALID"


def test_persist_verify_runtime_blocks_raw_stack_trace_in_verification_doc(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (task_root / "verification.md").write_text(
        """# Verification

Traceback (most recent call last):
  File "test.py", line 1, in <module>
ValueError: boom
""",
        encoding="utf-8",
    )

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_CONSOLE_STACK_TRACE_BLOCKED"
    assert list((task_root / "logs" / "verification").glob("*.json")) == []


def test_persist_verify_runtime_allows_single_caused_by_summary(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                basis_refs=["logs/test-output.txt", TEST_REPORT_VERIFICATION_ASSIST_REF],
                item_summary="Representative cause: Caused by: java.lang.IllegalStateException",
            ),
        )
    )

    assert result["reason_code"] is None


def test_persist_verify_runtime_blocks_unreadable_verification_doc(monkeypatch, tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (task_root / "verification.md").write_text("# Verification\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_verification_read(path: Path, *args, **kwargs):
        if path == task_root / "verification.md":
            raise OSError("cannot read verification.md")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_verification_read)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
        )
    )

    assert result["reason_code"] == "VERIFY_VERIFICATION_DOC_UNREADABLE"


def test_persist_verify_runtime_omits_test_report_warning_when_bridge_marker_present(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                basis_refs=["logs/test-output.txt", TEST_REPORT_VERIFICATION_ASSIST_REF],
            ),
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert result["reason_code"] is None
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" not in payload["lint_warnings"]


def test_persist_verify_runtime_does_not_use_candidate_basis_refs_to_suppress_test_report_warning(
    tmp_path: Path,
) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(),
            candidate_basis_refs=[TEST_REPORT_VERIFICATION_ASSIST_REF],
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert result["reason_code"] is None
    assert TEST_REPORT_VERIFICATION_ASSIST_REF not in payload["basis_refs"]
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" in payload["lint_warnings"]


def test_persist_verify_runtime_does_not_accept_standalone_test_report_marker(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                basis_refs=["logs/test-output.txt", TEST_REPORT_STANDALONE_REF],
            ),
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" in payload["lint_warnings"]


@pytest.mark.parametrize(
    "method",
    [
        "./mvnw verify",
        "ruff check .",
        "mypy src",
        "tsc --noEmit",
    ],
)
def test_persist_verify_runtime_warns_for_static_analysis_gate_without_report_bridge(
    tmp_path: Path,
    method: str,
) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                item_key="quality-gate",
                label="Quality gate",
                method=method,
            ),
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" in payload["lint_warnings"]


def test_persist_verify_runtime_warns_for_autofix_command_in_any_item_type(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                basis_refs=["logs/format-output.txt", TEST_REPORT_VERIFICATION_ASSIST_REF],
                item_type="gate",
                method="./gradlew :api:spotlessApply",
            ),
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert "VERIFY_AUTOFIX_COMMAND_RECORDED" in payload["lint_warnings"]


def test_persist_verify_runtime_does_not_require_test_report_for_cleanup_gradle_item(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                basis_refs=["logs/gradle-clean.txt"],
                item_type="cleanup",
                method="./gradlew clean",
            ),
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert "VERIFY_TEST_REPORT_SKILL_BYPASSED" not in payload["lint_warnings"]


def test_persist_verify_runtime_drops_unknown_lint_warning_codes(tmp_path: Path) -> None:
    workspace, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")
    verification_result = _verification_result(
        basis_refs=["logs/test-output.txt", TEST_REPORT_VERIFICATION_ASSIST_REF],
    )
    verification_result.lint_warnings = [
        "UNKNOWN_WARNING",
        VerificationLintWarningCode.AUTOFIX_COMMAND_RECORDED,
    ]

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=verification_result,
        )
    )

    payload = json.loads((task_root / str(result["verification_ref"])).read_text(encoding="utf-8"))
    assert payload["lint_warnings"] == ["VERIFY_AUTOFIX_COMMAND_RECORDED"]


@pytest.mark.parametrize(
    ("mutate", "message_fragment"),
    [
        (lambda result: result.update({"judgement_code": None}), "verification_result.judgement_code"),
        (lambda result: result.update({"judgement_code": 123}), "verification_result.judgement_code"),
        (lambda result: result.update({"judgement_code": "INVALID"}), "verification_result.judgement_code"),
        (lambda result: result.update({"summary": None}), "verification_result.summary"),
        (
            lambda result: result["verification_items"][0].update({"item_key": None}),
            "verification_result.verification_items\\[0\\].item_key",
        ),
        (
            lambda result: result["verification_items"][0].update({"item_type": None}),
            "verification_result.verification_items\\[0\\].item_type",
        ),
        (
            lambda result: result["verification_items"][0].update({"label": None}),
            "verification_result.verification_items\\[0\\].label",
        ),
        (
            lambda result: result["verification_items"][0].update({"method": None}),
            "verification_result.verification_items\\[0\\].method",
        ),
        (
            lambda result: result["verification_items"][0].update({"summary": None}),
            "verification_result.verification_items\\[0\\].summary",
        ),
        (
            lambda result: result["verification_items"][0].update({"result": None}),
            "verification_result.verification_items\\[0\\].result",
        ),
        (
            lambda result: result["verification_items"][0].update({"basis_refs": ["logs/test-output.txt", 123]}),
            "verification_result.verification_items\\[0\\].basis_refs\\[1\\]",
        ),
        (lambda result: result.update({"basis_refs": [None]}), "verification_result.basis_refs\\[0\\]"),
        (
            lambda result: result.update(
                {
                    "judgement_code": "GO_WITH_NOTE",
                    "note_signals": [
                        {
                            "note_text": None,
                            "note_target_hint": "plan",
                            "note_basis_refs": ["verification.md#note"],
                        }
                    ],
                }
            ),
            "verification_result.note_signals\\[0\\].note_text",
        ),
        (
            lambda result: result.update(
                {
                    "judgement_code": "GO_WITH_NOTE",
                    "note_signals": [
                        {
                            "note_text": "Carry note.",
                            "note_target_hint": "invalid",
                            "note_basis_refs": ["verification.md#note"],
                        }
                    ],
                }
            ),
            "verification_result.note_signals\\[0\\].note_target_hint",
        ),
    ],
)
def test_verify_runtime_rejects_invalid_dict_result_contract_fields(
    tmp_path: Path,
    mutate,
    message_fragment: str,
) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    payload = _verification_result_payload()
    mutate(payload)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=payload,
        )
    )

    assert result["reason_code"] == "VERIFY_RESULT_CONTRACT_INVALID"
    assert message_fragment.replace("\\", "") in str(result["message_summary"])
    assert result["verification_ref"] is None
    assert list((task_root / "logs" / "verification").glob("*.json")) == []
    assert read_state(task_root / "state.json").session_state == SessionState.IN_PROGRESS


def test_persist_verify_runtime_rejects_whitespace_failure_reason_fields(tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)

    result = persist_verify_runtime(
        VerifyRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            verification_result=_verification_result(
                JudgementCode.REWORK,
                primary_cause_code=" ",
                reason_fingerprint="reason",
            ),
        )
    )

    assert result["reason_code"] == "VERIFY_REASON_REQUIRED"


def test_runtime_cli_serializes_verify_result(monkeypatch, capsys, tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    payload = {
        "task_root": str(task_root),
        "workspace_root": str(REPO_ROOT),
        "verification_result": _verification_result_payload(),
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-verify-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["reason_code"] is None
    assert output["verification_ref"].startswith("logs/verification/")


def test_runtime_cli_returns_blocked_output_for_invalid_verify_payload(monkeypatch, capsys, tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    verification_result = _verification_result_payload()
    verification_result["summary"] = None
    payload = {
        "task_root": str(task_root),
        "workspace_root": str(REPO_ROOT),
        "verification_result": verification_result,
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-verify-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["reason_code"] == "VERIFY_RESULT_CONTRACT_INVALID"
    assert "verification_result.summary" in output["message_summary"]
    assert output["verification_ref"] is None
    assert list((task_root / "logs" / "verification").glob("*.json")) == []
