from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import harness.shared.runtime.apply_runtime as apply_runtime
from harness.runtime_cli import main
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.actions import (
    ArtifactAction,
    ArtifactTarget,
    CurrentStepRefSnapshot,
    SelectionBasis,
    SelectionMode,
)
from harness.shared.contracts.state import (
    CurrentPhase,
    DeferredStateTransition,
    HarnessCounters,
    HarnessState,
    SessionState,
    WorkflowMode,
)
from harness.shared.runtime.apply_runtime import ApplyRuntimeInput, execute_apply_runtime


def _write_state(task_root: Path, current_step_ref: str | None = "S1") -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.IMPLEMENTATION,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=current_step_ref,
            latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
            latest_verification_ref=None,
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


def _write_artifacts(task_root: Path) -> None:
    task_root.mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n\n## Contract Notes\n", encoding="utf-8")
    (task_root / "steps.md").write_text(
        "# Steps\n\n## Steps\n\n"
        "- [ ] Implement one. (go) [step_ref=S1]\n"
        "- [ ] Implement two. [step_ref=S2]\n\n"
        "## Working Notes\n",
        encoding="utf-8",
    )
    _write_state(task_root)


def _snapshot() -> CurrentStepRefSnapshot:
    return CurrentStepRefSnapshot(step_ref="S1", step_text="Implement one.", go_marker_present=True)


def _transition(next_phase: CurrentPhase = CurrentPhase.IMPLEMENTATION) -> DeferredStateTransition:
    return DeferredStateTransition(
        session_state=SessionState.IN_PROGRESS,
        current_phase=next_phase,
        pending_approval_for=None,
        review_outcome=None,
        closure_authorized=False,
        counters=HarnessCounters(),
    )


def test_apply_runtime_applies_plan_and_steps_notes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": "Keep API stable.", "note_basis_refs": ["plan.md#constraints"]},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.record_working_note",
                    params={
                        "current_step_ref_snapshot": _snapshot(),
                        "note_text": "Follow up during implementation.",
                        "note_basis_refs": ["steps.md#s1"],
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(CurrentPhase.STEP),
        )
    )

    assert result.apply_status.value == "APPLIED"
    assert result.reason_code is None
    assert sorted(result.updated_artifacts) == ["plan", "steps"]
    assert "- [contract-note] Keep API stable." in (task_root / "plan.md").read_text(encoding="utf-8")
    assert "Follow up during implementation." in (task_root / "steps.md").read_text(encoding="utf-8")
    assert read_state(task_root / "state.json").current_phase == CurrentPhase.STEP


def test_apply_runtime_blocks_deferred_transition_against_docs_only_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    docs_state = {
        "schema_version": 1,
        "workflow_kind": "docs_only",
        "docs_state": "discussion",
        "user_request": "문서 변경",
        "target_doc_refs": [],
        "proposal_ref": None,
        "diff_ref": None,
        "applied_ref": None,
        "last_event_ref": None,
        "event_history_refs": [],
        "last_updated": "2026-05-10 12:00:00 KST",
        "adapter_meta": {},
    }
    (task_root / "state.json").write_text(json.dumps(docs_state, indent=2) + "\n", encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == docs_state
    assert not (task_root / "state.json.v1.bak").exists()


def test_apply_runtime_blocks_docs_only_state_before_artifact_writes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "plan.md").write_text("# Plan\n\n## Contract Notes\n", encoding="utf-8")
    docs_state = {
        "schema_version": 1,
        "workflow_kind": "docs_only",
        "docs_state": "discussion",
        "user_request": "문서 변경",
        "target_doc_refs": [],
        "proposal_ref": None,
        "diff_ref": None,
        "applied_ref": None,
        "last_event_ref": None,
        "event_history_refs": [],
        "last_updated": "2026-05-10 12:00:00 KST",
        "adapter_meta": {},
    }
    (task_root / "state.json").write_text(json.dumps(docs_state, indent=2) + "\n", encoding="utf-8")
    original_plan = (task_root / "plan.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": "must not be written", "note_basis_refs": ["plan.md#goal"]},
                    basis_ref="logs/checkpoints/checkpoint.json",
                )
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert result.updated_artifacts == []
    assert (task_root / "plan.md").read_text(encoding="utf-8") == original_plan
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == docs_state
    assert not (task_root / "state.json.v1.bak").exists()


def test_apply_runtime_blocks_missing_state_for_deferred_transition(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "STATE_ARTIFACT_MISSING"


def test_apply_runtime_blocks_unreadable_state_before_artifact_writes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "plan.md").write_text("# Plan\n\n## Contract Notes\n", encoding="utf-8")
    (task_root / "state.json").mkdir()
    original_plan = (task_root / "plan.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": "must not be written", "note_basis_refs": ["plan.md#goal"]},
                    basis_ref="logs/checkpoints/checkpoint.json",
                )
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert result.updated_artifacts == []
    assert (task_root / "plan.md").read_text(encoding="utf-8") == original_plan


def test_apply_runtime_blocks_plan_read_error_during_state_precondition(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root)
    (task_root / "plan.md").mkdir()
    original_state = json.loads((task_root / "state.json").read_text(encoding="utf-8"))

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_state


def test_apply_runtime_marks_clears_and_selects_next_step(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.mark_current_step_done",
                    params={"current_step_ref_snapshot": _snapshot()},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={"current_step_ref_snapshot": _snapshot()},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.select_next_go_step",
                    params={
                        "current_step_ref_snapshot": _snapshot(),
                        "selection_basis": SelectionBasis(mode=SelectionMode.NEXT_PENDING_AFTER_CURRENT),
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(),
        )
    )

    steps = (task_root / "steps.md").read_text(encoding="utf-8")
    state = read_state(task_root / "state.json")

    assert result.apply_status.value == "APPLIED"
    assert "- [x] Implement one. [step_ref=S1]" in steps
    assert "- [ ] Implement two. (go) [step_ref=S2]" in steps
    assert result.current_step_ref_update_mode == "set"
    assert result.resolved_current_step_ref == "S2"
    assert state.current_step_ref == "S2"


def test_apply_runtime_blocks_unsupported_action_without_writes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_plan = (task_root / "plan.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.not_supported",
                    params={},
                    basis_ref="logs/checkpoints/checkpoint.json",
                )
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_UNSUPPORTED_ACTION"
    assert (task_root / "plan.md").read_text(encoding="utf-8") == original_plan
    assert read_state(task_root / "state.json").current_phase == CurrentPhase.IMPLEMENTATION


def test_apply_runtime_blocks_snapshot_mismatch_without_writes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_steps = (task_root / "steps.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={
                        "current_step_ref_snapshot": CurrentStepRefSnapshot(
                            step_ref="S1",
                            step_text="Implement one.",
                            go_marker_present=False,
                        )
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                )
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    assert (task_root / "steps.md").read_text(encoding="utf-8") == original_steps
    assert read_state(task_root / "state.json").current_phase == CurrentPhase.IMPLEMENTATION


def test_apply_runtime_blocks_stale_snapshot_text_without_writes(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_steps = (task_root / "steps.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={
                        "current_step_ref_snapshot": CurrentStepRefSnapshot(
                            step_ref="S1",
                            step_text="Stale step text.",
                            go_marker_present=True,
                        )
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                )
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    assert (task_root / "steps.md").read_text(encoding="utf-8") == original_steps


def test_apply_runtime_blocks_bad_sequence_instead_of_clearing_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_steps = (task_root / "steps.md").read_text(encoding="utf-8")

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={"current_step_ref_snapshot": _snapshot()},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.select_next_go_step",
                    params={
                        "current_step_ref_snapshot": _snapshot(),
                        "selection_basis": SelectionBasis(mode=SelectionMode.NEXT_PENDING_AFTER_CURRENT),
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={"current_step_ref_snapshot": _snapshot()},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    assert (task_root / "steps.md").read_text(encoding="utf-8") == original_steps
    assert read_state(task_root / "state.json").current_step_ref == "S1"


def test_apply_runtime_blocks_postcondition_failure_before_writes(monkeypatch, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_plan = (task_root / "plan.md").read_text(encoding="utf-8")
    original_steps = (task_root / "steps.md").read_text(encoding="utf-8")

    def fail_postcondition(previous_steps: str | None, next_steps: str | None):
        return "unchanged", None, "APPLY_GO_POSTCONDITION_INVALID"

    def fail_if_written(path: Path, content: str) -> None:
        raise AssertionError(f"unexpected write to {path}")

    monkeypatch.setattr(apply_runtime, "_resolve_current_step_ref_update", fail_postcondition)
    monkeypatch.setattr(apply_runtime, "_atomic_write", fail_if_written)

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": "Plan note.", "note_basis_refs": []},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.record_working_note",
                    params={
                        "current_step_ref_snapshot": _snapshot(),
                        "note_text": "Step note.",
                        "note_basis_refs": [],
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_GO_POSTCONDITION_INVALID"
    assert result.applied_actions == []
    assert result.updated_artifacts == []
    assert (task_root / "plan.md").read_text(encoding="utf-8") == original_plan
    assert (task_root / "steps.md").read_text(encoding="utf-8") == original_steps
    assert not (task_root / "logs" / "apply-recovery").exists()


def test_apply_runtime_ignores_nested_checklists_in_steps_section(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    (task_root / "steps.md").write_text(
        "# Steps\n\n## Steps\n\n"
        "- [ ] Implement one. (go) [step_ref=S1]\n"
        "  - [ ] nested note [step_ref=N1]\n"
        "- [ ] Implement two. [step_ref=S2]\n\n"
        "## Working Notes\n",
        encoding="utf-8",
    )

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.clear_current_step",
                    params={"current_step_ref_snapshot": _snapshot()},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(),
        )
    )

    assert result.apply_status.value == "APPLIED"
    assert result.current_step_ref_update_mode == "clear"


def test_apply_runtime_records_partial_recovery_on_commit_partial(monkeypatch, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    original_steps = (task_root / "steps.md").read_text(encoding="utf-8")
    real_atomic_write = apply_runtime._atomic_write

    def flaky_atomic_write(path: Path, content: str) -> None:
        if path.name == "steps.md":
            raise OSError("simulated write failure")
        real_atomic_write(path, content)

    monkeypatch.setattr(apply_runtime, "_atomic_write", flaky_atomic_write)

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            routing_basis_ref="logs/checkpoints/checkpoint.json",
            required_artifact_actions=[
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": "Plan note.", "note_basis_refs": []},
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.record_working_note",
                    params={
                        "current_step_ref_snapshot": _snapshot(),
                        "note_text": "Step note.",
                        "note_basis_refs": [],
                    },
                    basis_ref="logs/checkpoints/checkpoint.json",
                ),
            ],
            deferred_state_transition=_transition(CurrentPhase.PLAN),
        )
    )

    recovery_records = list((task_root / "logs" / "apply-recovery").glob("*.json"))
    payload = json.loads(recovery_records[0].read_text(encoding="utf-8"))

    assert result.apply_status.value == "BLOCKED"
    assert result.reason_code == "APPLY_COMMIT_PARTIAL"
    assert result.updated_artifacts == ["plan"]
    assert [action.action for action in result.applied_actions] == ["plan.record_contract_note"]
    assert result.current_step_ref_update_mode == "unchanged"
    assert result.resolved_current_step_ref is None
    assert "Plan note." in (task_root / "plan.md").read_text(encoding="utf-8")
    assert (task_root / "steps.md").read_text(encoding="utf-8") == original_steps
    assert read_state(task_root / "state.json").current_phase == CurrentPhase.IMPLEMENTATION
    assert payload["status"] == "unresolved"
    assert payload["updated_artifacts"] == ["plan"]
    assert payload["required_artifact_actions"][1]["action"] == "steps.record_working_note"


def test_apply_runtime_noop_actions_still_apply_deferred_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)

    result = execute_apply_runtime(
        ApplyRuntimeInput(
            task_root=task_root,
            required_artifact_actions=[],
            deferred_state_transition=_transition(CurrentPhase.VERIFICATION),
        )
    )

    assert result.apply_status.value == "NOOP"
    assert result.updated_artifacts == []
    assert read_state(task_root / "state.json").current_phase == CurrentPhase.VERIFICATION
    assert read_state(task_root / "state.json").current_step_ref is None


def test_runtime_cli_serializes_apply_result(monkeypatch, capsys, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    _write_artifacts(task_root)
    payload = {
        "task_root": str(task_root),
        "required_artifact_actions": [
            {
                "target": "plan",
                "action": "plan.rewrite_required",
                "params": {"rewrite_reason_code": "plan_gap"},
                "basis_ref": "logs/checkpoints/checkpoint.json",
            }
        ],
        "routing_basis_ref": "logs/checkpoints/checkpoint.json",
        "deferred_state_transition": {
            "session_state": "in_progress",
            "current_phase": "plan",
            "pending_approval_for": None,
            "review_outcome": None,
            "closure_authorized": False,
            "counters": {"rework_count": 0, "rewrite_count": 1, "rollback_count": 0},
        },
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-apply-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["apply_status"] == "APPLIED"
    assert output["updated_artifacts"] == ["plan"]
