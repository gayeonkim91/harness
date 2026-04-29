from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import harness.shared.runtime.verify_runtime as verify_runtime
from harness.runtime_cli import main
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.results import JudgementCode, NoteSignal, NoteTargetHint, VerificationItem, VerificationResult
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode
from harness.shared.core.snapshot_helper import capture_workspace_baseline
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
    session_state: SessionState = SessionState.ACTIVE,
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
) -> VerificationResult:
    return VerificationResult(
        verification_ref="",
        judgement_code=judgement,
        summary="Verification passed.",
        verification_items=[
            VerificationItem(
                item_key="gate-tests",
                item_type="gate",
                label="Test suite",
                method="pytest",
                result="PASS",
                summary="All selected tests passed.",
                basis_refs=["logs/test-output.txt"],
            )
        ],
        basis_refs=["logs/test-output.txt"],
        note_signals=note_signals or [],
        primary_cause_code=primary_cause_code,
        reason_fingerprint=reason_fingerprint,
    )


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
    state_payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    state_payload["blocked_transition"] = "verify_state_update"
    state_payload["blocked_reason_ref"] = "logs/verification/orphan.json"
    (task_root / "state.json").write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
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


def test_runtime_cli_serializes_verify_result(monkeypatch, capsys, tmp_path: Path) -> None:
    _, task_root, baseline_ref = _workspace_with_baseline(tmp_path)
    _write_plan(task_root)
    _write_state(task_root, baseline_ref)
    payload = {
        "task_root": str(task_root),
        "workspace_root": str(REPO_ROOT),
        "verification_result": {
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
        },
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-verify-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["reason_code"] is None
    assert output["verification_ref"].startswith("logs/verification/")
