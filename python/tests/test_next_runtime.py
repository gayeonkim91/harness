from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

from harness.runtime_cli import main
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.state import (
    CurrentPhase,
    HarnessCounters,
    HarnessState,
    ReviewOutcome,
    SessionState,
    WorkflowMode,
)
from harness.shared.contracts.results import JudgementCode
from harness.shared.runtime.next_runtime import NextRuntimeInput, execute_next_runtime


def _write_state(
    task_root: Path,
    phase: CurrentPhase,
    current_step_ref: str | None = None,
    latest_checkpoint_ref: str | None = None,
    latest_verification_ref: str | None = None,
    latest_review_ref: str | None = None,
    pending_approval_for: str | None = None,
    session_state: SessionState = SessionState.IN_PROGRESS,
    review_outcome: str | None = None,
) -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=session_state,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=phase,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=current_step_ref,
            latest_checkpoint_ref=latest_checkpoint_ref,
            latest_verification_ref=latest_verification_ref,
            latest_review_ref=latest_review_ref,
            pending_approval_for=pending_approval_for,
            review_outcome=ReviewOutcome(review_outcome) if review_outcome is not None else None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )


def _write_steps(task_root: Path, body: str) -> None:
    (task_root / "steps.md").write_text(f"# Steps\n\n## Steps\n\n{body}\n\n## Working Notes\n", encoding="utf-8")


def test_next_runtime_blocks_plan_mirror_read_error_as_invalid_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    original_state = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    (task_root / "plan.md").mkdir()

    result = execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="checkpoint",
            current_phase=CurrentPhase.PLAN,
            pending_approval_for=None,
            resolved_result_ref=None,
            judgement_code=JudgementCode.GO,
        )
    )

    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert result.routing_basis_ref == "state.json"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_state


def _write_checkpoint(
    task_root: Path,
    phase: str,
    judgement: str,
    *,
    note_signals: list[dict[str, object]] | None = None,
    current_step_ref_snapshot: dict[str, object] | None = None,
    primary_cause_code: str | None = None,
) -> str:
    ref = "logs/checkpoints/checkpoint.json"
    path = task_root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checkpoint_ref": ref,
        "phase": phase,
        "judgement_code": judgement,
        "summary": "checkpoint summary",
        "check_items": [],
        "basis_refs": ["plan.md#goal"],
        "note_signals": note_signals or [],
        "stop_condition_code": None,
        "primary_cause_code": primary_cause_code,
        "reason_fingerprint": "fingerprint" if primary_cause_code else None,
        "current_step_ref_snapshot": current_step_ref_snapshot,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _set_state_field(task_root, "latest_checkpoint_ref", ref)
    return ref


def _write_verification(
    task_root: Path,
    judgement: str,
    *,
    note_signals: list[dict[str, object]] | None = None,
    primary_cause_code: str | None = None,
) -> str:
    ref = "logs/verification/verification.json"
    path = task_root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "verification_ref": ref,
        "judgement_code": judgement,
        "summary": "verification summary",
        "verification_items": [
            {
                "item_key": "gate-tests",
                "item_type": "gate",
                "label": "Test suite",
                "method": "pytest",
                "result": "PASS",
                "summary": "Passed.",
                "basis_refs": ["logs/test-output.txt"],
            }
        ],
        "basis_refs": ["logs/test-output.txt"],
        "note_signals": note_signals or [],
        "verified_task_diff_fingerprint": "sha256:verified",
        "stop_condition_code": None,
        "primary_cause_code": primary_cause_code,
        "reason_fingerprint": "fingerprint" if primary_cause_code else None,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _set_state_field(task_root, "latest_verification_ref", ref)
    return ref


def _write_review(
    task_root: Path,
    judgement: str,
    *,
    primary_cause_code: str | None = None,
    carry_forward_notes: list[str] | None = None,
) -> str:
    ref = "logs/review/review.json"
    path = task_root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "review_ref": ref,
        "judgement_code": judgement,
        "summary": "review summary",
        "out_of_scope_change": False,
        "key_issues": [],
        "verification_blind_spots": [],
        "carry_forward_notes": carry_forward_notes or [],
        "basis_refs": ["logs/verification/verification.json"],
        "primary_cause_code": primary_cause_code,
        "reason_fingerprint": "fingerprint" if primary_cause_code else None,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ref


def _set_state_field(task_root: Path, field: str, value: object) -> None:
    state_path = task_root / "state.json"
    if not state_path.exists():
        return
    state = read_state(state_path)
    setattr(state, field, value)
    write_state(state_path, state)


def _next(task_root: Path, ref: str, phase: CurrentPhase, hint: JudgementCode = JudgementCode.HOLD):
    return execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="checkpoint",
            current_phase=phase,
            pending_approval_for=None,
            resolved_result_ref=ref,
            judgement_code=hint,
        )
    )


def _next_verify(task_root: Path, ref: str, hint: JudgementCode = JudgementCode.HOLD):
    return execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="verify",
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for=None,
            resolved_result_ref=ref,
            judgement_code=hint,
        )
    )


def _next_review(task_root: Path, ref: str, hint: JudgementCode = JudgementCode.HOLD):
    return execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="review",
            current_phase=CurrentPhase.REVIEW,
            pending_approval_for=None,
            resolved_result_ref=ref,
            judgement_code=hint,
        )
    )


def test_next_checkpoint_plan_go_routes_to_step_from_artifact_not_hint(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(task_root, "plan", "GO")

    result = _next(task_root, ref, CurrentPhase.PLAN, hint=JudgementCode.HOLD)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.STEP
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.required_artifact_actions == []
    assert result.routing_basis_ref == ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.current_phase == CurrentPhase.STEP


def test_next_checkpoint_pre_planning_go_requests_pre_plan_approval(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PRE_PLANNING)
    ref = _write_checkpoint(task_root, "pre-planning", "GO")

    result = _next(task_root, ref, CurrentPhase.PRE_PLANNING)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.PRE_PLANNING
    assert result.next_session_state == SessionState.AWAITING_APPROVAL
    assert result.pending_approval_for == "pre_plan_to_plan"
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.approvals_granted == []


def test_next_checkpoint_step_go_requests_plan_to_implementation_approval(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.STEP, current_step_ref="S1")
    ref = _write_checkpoint(
        task_root,
        "step",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.STEP)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.STEP
    assert result.next_session_state == SessionState.AWAITING_APPROVAL
    assert result.pending_approval_for == "plan_to_implementation"


def test_next_checkpoint_plan_rewrite_emits_plan_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(task_root, "plan", "REWRITE_PLAN", primary_cause_code="plan_scope_mismatch")

    result = _next(task_root, ref, CurrentPhase.PLAN)

    assert result.next_phase == CurrentPhase.PLAN
    assert result.required_artifact_actions[0].target.value == "plan"
    assert result.required_artifact_actions[0].action == "plan.rewrite_required"
    assert result.required_artifact_actions[0].params["rewrite_reason_code"] == "plan_scope_mismatch"
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.counters.rewrite_count == 1


def test_next_checkpoint_go_with_plan_note_emits_note_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(
        task_root,
        "plan",
        "GO_WITH_NOTE",
        note_signals=[
            {
                "note_text": "Keep API compatibility visible.",
                "note_target_hint": "plan",
                "note_basis_refs": ["plan.md#constraints"],
            }
        ],
    )

    result = _next(task_root, ref, CurrentPhase.PLAN)

    assert result.next_phase == CurrentPhase.STEP
    assert len(result.required_artifact_actions) == 1
    assert result.required_artifact_actions[0].action == "plan.record_contract_note"
    assert result.required_artifact_actions[0].params["note_basis_refs"] == ["plan.md#constraints"]


def test_next_checkpoint_implementation_go_selects_next_step_when_remaining(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="S1")
    _write_steps(
        task_root,
        "- [ ] Implement one. (go) [step_ref=S1]\n- [ ] Implement two. [step_ref=S2]",
    )
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.IMPLEMENTATION)

    assert result.next_phase == CurrentPhase.IMPLEMENTATION
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert [action.action for action in result.required_artifact_actions] == [
        "steps.mark_current_step_done",
        "steps.clear_current_step",
        "steps.select_next_go_step",
    ]
    selection_basis = result.required_artifact_actions[-1].params["selection_basis"]
    assert selection_basis.mode.value == "next_pending_after_current"


def test_next_checkpoint_blocks_when_snapshot_no_longer_matches_step_source(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="step:1")
    (task_root / "plan.md").write_text(
        "# Plan\n\n## Steps\n\n- [ ] Different step text. (go)\n- [ ] Implement two.\n",
        encoding="utf-8",
    )
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "step:1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.IMPLEMENTATION)

    assert result.reason_code == "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE"
    assert result.required_artifact_actions == []


def test_next_checkpoint_implementation_ignores_nested_pending_steps(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="S1")
    _write_steps(
        task_root,
        "- [ ] Implement one. (go) [step_ref=S1]\n  - [ ] nested note [step_ref=N1]",
    )
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.IMPLEMENTATION)

    assert result.next_phase == CurrentPhase.VERIFICATION
    assert [action.action for action in result.required_artifact_actions] == [
        "steps.mark_current_step_done",
        "steps.clear_current_step",
    ]


def test_next_checkpoint_implementation_go_enters_verification_when_no_remaining_step(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="S1")
    _write_steps(task_root, "- [ ] Implement one. (go) [step_ref=S1]")
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.IMPLEMENTATION)

    assert result.next_phase == CurrentPhase.VERIFICATION
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.pending_approval_for is None
    assert [action.action for action in result.required_artifact_actions] == [
        "steps.mark_current_step_done",
        "steps.clear_current_step",
    ]


def test_next_checkpoint_blocks_steps_note_without_snapshot(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(
        task_root,
        "plan",
        "GO_WITH_NOTE",
        note_signals=[
            {
                "note_text": "Follow up in current step.",
                "note_target_hint": "steps",
                "note_basis_refs": ["steps.md#s1"],
            }
        ],
    )

    result = _next(task_root, ref, CurrentPhase.PLAN)

    assert result.reason_code == "CHECKPOINT_NOTE_TARGET_INVALID_FOR_PHASE"
    assert result.next_session_state == SessionState.PAUSED
    assert result.required_artifact_actions == []


def test_next_checkpoint_blocks_unresolvable_current_step_context(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="S1")
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )

    result = _next(task_root, ref, CurrentPhase.IMPLEMENTATION)

    assert result.reason_code == "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE"
    assert result.next_session_state == SessionState.PAUSED


def test_next_checkpoint_blocks_missing_latest_checkpoint_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(task_root, "plan", "GO")
    _set_state_field(task_root, "latest_checkpoint_ref", None)

    result = _next(task_root, ref, CurrentPhase.PLAN)

    assert result.reason_code == "NEXT_RESULT_REF_MISSING"
    assert result.next_session_state == SessionState.PAUSED


def test_next_checkpoint_blocks_non_latest_checkpoint_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    latest_ref = _write_checkpoint(task_root, "plan", "GO")
    stale_ref = "logs/checkpoints/stale.json"
    (task_root / stale_ref).write_text((task_root / latest_ref).read_text(encoding="utf-8"), encoding="utf-8")

    result = _next(task_root, stale_ref, CurrentPhase.PLAN)

    assert result.reason_code == "NEXT_RESULT_REF_NOT_LATEST"
    assert result.next_session_state == SessionState.PAUSED


def _next_approval(
    task_root: Path,
    ref: str | None = None,
    hint: JudgementCode = JudgementCode.DONE,
    pending_approval_for: str | None = None,
):
    return execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="approval",
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for=pending_approval_for,
            resolved_result_ref=ref,
            judgement_code=hint,
        )
    )


def test_next_approval_pre_plan_to_plan_enters_plan_and_records_grant(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    checkpoint_ref = "logs/checkpoints/checkpoint.json"
    _write_state(
        task_root,
        CurrentPhase.PRE_PLANNING,
        latest_checkpoint_ref=checkpoint_ref,
        pending_approval_for="pre_plan_to_plan",
        session_state=SessionState.AWAITING_APPROVAL,
    )

    result = _next_approval(task_root)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.PLAN
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.pending_approval_for is None
    assert result.required_artifact_actions == []
    assert result.routing_basis_ref == checkpoint_ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.pending_approval_for is None
    assert result.deferred_state_transition.closure_authorized is False
    assert result.deferred_state_transition.approvals_granted == [1]


def test_next_approval_plan_to_implementation_enters_implementation_and_records_grant(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    checkpoint_ref = "logs/checkpoints/checkpoint.json"
    _write_state(
        task_root,
        CurrentPhase.STEP,
        latest_checkpoint_ref=checkpoint_ref,
        pending_approval_for="plan_to_implementation",
        session_state=SessionState.AWAITING_APPROVAL,
    )

    result = _next_approval(task_root)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.IMPLEMENTATION
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.pending_approval_for is None
    assert result.routing_basis_ref == checkpoint_ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.approvals_granted == [1, 2]


def test_next_approval_plan_to_implementation_preserves_existing_grants(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    checkpoint_ref = "logs/checkpoints/checkpoint.json"
    _write_state(
        task_root,
        CurrentPhase.STEP,
        latest_checkpoint_ref=checkpoint_ref,
        pending_approval_for="plan_to_implementation",
        session_state=SessionState.AWAITING_APPROVAL,
    )
    _set_state_field(task_root, "approvals_granted", [1])

    result = _next_approval(task_root)

    assert result.reason_code is None
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.approvals_granted == [1, 2]


def test_next_approval_plan_to_implementation_blocks_wrong_phase(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
        pending_approval_for="plan_to_implementation",
        session_state=SessionState.AWAITING_APPROVAL,
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_plan_to_implementation_blocks_wrong_session(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.STEP,
        latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
        pending_approval_for="plan_to_implementation",
        session_state=SessionState.IN_PROGRESS,
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_absorbs_repaired_legacy_verification_entry_event(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    checkpoint_ref = "logs/checkpoints/checkpoint.json"
    _write_state(
        task_root,
        CurrentPhase.VERIFICATION,
        latest_checkpoint_ref=checkpoint_ref,
        pending_approval_for="verification_entry",
        session_state=SessionState.AWAITING_APPROVAL,
    )
    _set_state_field(task_root, "schema_version", 2)
    _set_state_field(task_root, "last_updated", "2026-04-19 22:00:00 KST")

    result = _next_approval(task_root, pending_approval_for="verification_entry")
    state = read_state(task_root / "state.json")

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.VERIFICATION
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.pending_approval_for is None
    assert result.routing_basis_ref == checkpoint_ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.approvals_granted == []
    assert state.session_state == SessionState.IN_PROGRESS
    assert state.pending_approval_for is None


def test_next_approval_blocks_accidental_approval_in_verification_without_legacy_token(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    checkpoint_ref = "logs/checkpoints/checkpoint.json"
    _write_state(
        task_root,
        CurrentPhase.VERIFICATION,
        latest_checkpoint_ref=checkpoint_ref,
        pending_approval_for=None,
        session_state=SessionState.IN_PROGRESS,
    )

    result = _next_approval(task_root, ref=checkpoint_ref)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_closure_marks_done_and_authorized(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    review_ref = "logs/review/review.json"
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref=review_ref,
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )
    _set_state_field(task_root, "approvals_granted", [1, 2])

    result = _next_approval(task_root)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.REVIEW
    assert result.next_session_state == SessionState.DONE
    assert result.pending_approval_for is None
    assert result.required_artifact_actions == []
    assert result.routing_basis_ref == review_ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.closure_authorized is True
    assert result.deferred_state_transition.review_outcome.value == "DONE"
    assert result.deferred_state_transition.approvals_granted == [1, 2, 3]


def test_next_approval_closure_blocks_active_session(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref="logs/review/review.json",
        pending_approval_for="closure",
        session_state=SessionState.IN_PROGRESS,
        review_outcome="DONE",
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_closure_blocks_wrong_phase(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.VERIFICATION,
        latest_review_ref="logs/review/review.json",
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_closure_blocks_non_done_review_outcome(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref="logs/review/review.json",
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="REWORK",
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_accepts_matching_result_ref_hint(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    review_ref = "logs/review/review.json"
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref=review_ref,
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )

    result = _next_approval(task_root, review_ref)

    assert result.reason_code is None
    assert result.routing_basis_ref == review_ref


def test_next_approval_blocks_without_pending_target(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.REVIEW)

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_blocks_unsupported_pending_target(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        pending_approval_for="manual_override",
        session_state=SessionState.AWAITING_APPROVAL,
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_APPROVAL_CONTEXT_INVALID"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for is None


def test_next_approval_blocks_missing_latest_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )

    result = _next_approval(task_root)

    assert result.reason_code == "NEXT_RESULT_REF_MISSING"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for == "closure"


def test_next_approval_blocks_result_ref_mismatch(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref="logs/review/latest.json",
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )

    result = _next_approval(task_root, "logs/review/stale.json")

    assert result.reason_code == "NEXT_APPROVAL_RESULT_REF_MISMATCH"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for == "closure"


def test_next_approval_blocks_plan_to_implementation_result_ref_mismatch(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(
        task_root,
        CurrentPhase.STEP,
        latest_checkpoint_ref="logs/checkpoints/latest.json",
        pending_approval_for="plan_to_implementation",
        session_state=SessionState.AWAITING_APPROVAL,
    )

    result = _next_approval(task_root, "logs/checkpoints/stale.json")

    assert result.reason_code == "NEXT_APPROVAL_RESULT_REF_MISMATCH"
    assert result.next_session_state == SessionState.PAUSED
    assert result.pending_approval_for == "plan_to_implementation"


def test_next_review_done_routes_to_closure_approval(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "DONE")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.REVIEW
    assert result.next_session_state == SessionState.AWAITING_APPROVAL
    assert result.pending_approval_for == "closure"
    assert result.required_artifact_actions == []
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.review_outcome.value == "DONE"
    assert result.deferred_state_transition.closure_authorized is False


def test_next_review_transition_preserves_existing_stop_and_block_refs(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "DONE")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)
    state = read_state(task_root / "state.json")
    state.stop_condition_ref = "logs/stop-condition.json"
    state.blocked_transition = "previous"
    state.blocked_reason_ref = "logs/previous-block.json"
    write_state(task_root / "state.json", state)

    result = _next_review(task_root, ref)

    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.stop_condition_ref == "logs/stop-condition.json"
    assert result.deferred_state_transition.blocked_transition == "previous"
    assert result.deferred_state_transition.blocked_reason_ref == "logs/previous-block.json"


def test_next_review_done_with_note_does_not_emit_artifact_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "DONE_WITH_NOTE", carry_forward_notes=["Tell user about caveat."])
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.next_session_state == SessionState.AWAITING_APPROVAL
    assert result.pending_approval_for == "closure"
    assert result.required_artifact_actions == []


def test_next_review_rework_routes_to_step(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "REWORK", primary_cause_code="review_bug")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.next_phase == CurrentPhase.STEP
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.required_artifact_actions == []
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.review_outcome.value == "REWORK"
    assert result.deferred_state_transition.counters.rework_count == 1


def test_next_review_blocks_non_latest_review_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    latest_ref = _write_review(task_root, "DONE")
    stale_ref = "logs/review/stale.json"
    (task_root / stale_ref).write_text((task_root / latest_ref).read_text(encoding="utf-8"), encoding="utf-8")
    _write_state(task_root, CurrentPhase.REVIEW)
    state = read_state(task_root / "state.json")
    state.latest_review_ref = latest_ref
    write_state(task_root / "state.json", state)

    result = _next_review(task_root, stale_ref)

    assert result.reason_code == "NEXT_RESULT_REF_NOT_LATEST"
    assert result.next_session_state == SessionState.PAUSED


def test_next_review_blocks_missing_latest_review_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "DONE")
    _write_state(task_root, CurrentPhase.REVIEW)

    result = _next_review(task_root, ref)

    assert result.reason_code == "NEXT_RESULT_REF_MISSING"
    assert result.next_session_state == SessionState.PAUSED


def test_next_review_rewrite_plan_emits_plan_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "REWRITE_PLAN", primary_cause_code="plan_gap")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.next_phase == CurrentPhase.PLAN
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert [action.action for action in result.required_artifact_actions] == ["plan.rewrite_required"]
    assert result.required_artifact_actions[0].params["rewrite_reason_code"] == "plan_gap"
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.review_outcome.value == "REWRITE_PLAN"


def test_next_review_hold_pauses_review(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "HOLD", primary_cause_code="review_unclear")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.next_phase == CurrentPhase.REVIEW
    assert result.next_session_state == SessionState.PAUSED
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.review_outcome.value == "HOLD"


def test_next_review_blocks_unsupported_rewrite_step(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "REWRITE_STEP", primary_cause_code="unsupported")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.reason_code == "NEXT_REVIEW_JUDGEMENT_UNSUPPORTED"
    assert result.next_session_state == SessionState.PAUSED


def test_next_review_rejects_string_boolean_payload(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    ref = _write_review(task_root, "DONE")
    payload = json.loads((task_root / ref).read_text(encoding="utf-8"))
    payload["out_of_scope_change"] = "false"
    (task_root / ref).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_state(task_root, CurrentPhase.REVIEW, latest_review_ref=ref)

    result = _next_review(task_root, ref)

    assert result.reason_code == "NEXT_RESULT_REF_UNREADABLE"


def test_next_verify_go_routes_to_review_from_artifact_not_hint(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "GO")

    result = _next_verify(task_root, ref, hint=JudgementCode.HOLD)

    assert result.reason_code is None
    assert result.next_phase == CurrentPhase.REVIEW
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.required_artifact_actions == []
    assert result.routing_basis_ref == ref
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.current_phase == CurrentPhase.REVIEW


def test_next_verify_go_with_note_emits_plan_note_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(
        task_root,
        "GO_WITH_NOTE",
        note_signals=[
            {
                "note_text": "Carry verification caution.",
                "note_target_hint": "plan",
                "note_basis_refs": ["logs/verification/verification.json#note"],
            }
        ],
    )

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.REVIEW
    assert [action.action for action in result.required_artifact_actions] == ["plan.record_contract_note"]
    assert result.required_artifact_actions[0].params["note_text"] == "Carry verification caution."


def test_next_verify_rewrite_plan_emits_plan_rewrite_action(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "REWRITE_PLAN", primary_cause_code="verification_contract_gap")

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.PLAN
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert [action.action for action in result.required_artifact_actions] == ["plan.rewrite_required"]
    assert result.required_artifact_actions[0].params["rewrite_reason_code"] == "verification_contract_gap"


def test_next_verify_rework_stays_in_verification(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "REWORK", primary_cause_code="test_flake")

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.VERIFICATION
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.required_artifact_actions == []
    assert result.deferred_state_transition is not None
    assert result.deferred_state_transition.counters.rework_count == 1


def test_next_verify_rewrite_step_routes_to_step_without_actions(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "REWRITE_STEP", primary_cause_code="step_contract_gap")

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.STEP
    assert result.next_session_state == SessionState.IN_PROGRESS
    assert result.required_artifact_actions == []


def test_next_verify_rollback_routes_to_paused_verification(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "ROLLBACK", primary_cause_code="rollback_required")

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.VERIFICATION
    assert result.next_session_state == SessionState.PAUSED
    assert result.required_artifact_actions == []


def test_next_verify_hold_routes_to_paused_verification(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "HOLD", primary_cause_code="manual_review_needed")

    result = _next_verify(task_root, ref)

    assert result.next_phase == CurrentPhase.VERIFICATION
    assert result.next_session_state == SessionState.PAUSED
    assert result.required_artifact_actions == []


def test_next_verify_blocks_unsupported_done_judgement(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "DONE")

    result = _next_verify(task_root, ref)

    assert result.reason_code == "NEXT_VERIFY_JUDGEMENT_UNSUPPORTED"
    assert result.next_session_state == SessionState.PAUSED


def test_next_verify_blocks_missing_diff_fingerprint_as_unreadable(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "GO")
    path = task_root / ref
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["verified_task_diff_fingerprint"]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = _next_verify(task_root, ref)

    assert result.reason_code == "NEXT_RESULT_REF_UNREADABLE"


def test_next_verify_blocks_missing_latest_verification_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(task_root, "GO")
    _set_state_field(task_root, "latest_verification_ref", None)

    result = _next_verify(task_root, ref)

    assert result.reason_code == "NEXT_RESULT_REF_MISSING"
    assert result.next_session_state == SessionState.PAUSED


def test_next_verify_blocks_non_latest_verification_ref(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    latest_ref = _write_verification(task_root, "GO")
    stale_ref = "logs/verification/stale.json"
    (task_root / stale_ref).write_text((task_root / latest_ref).read_text(encoding="utf-8"), encoding="utf-8")

    result = _next_verify(task_root, stale_ref)

    assert result.reason_code == "NEXT_RESULT_REF_NOT_LATEST"
    assert result.next_session_state == SessionState.PAUSED


def test_next_verify_blocks_steps_note_target(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.VERIFICATION)
    ref = _write_verification(
        task_root,
        "GO_WITH_NOTE",
        note_signals=[
            {
                "note_text": "Invalid target.",
                "note_target_hint": "steps",
                "note_basis_refs": ["logs/verification/verification.json#note"],
            }
        ],
    )

    result = _next_verify(task_root, ref)

    assert result.reason_code == "VERIFY_NOTE_TARGET_INVALID_FOR_PHASE"
    assert result.next_session_state == SessionState.PAUSED
    assert result.required_artifact_actions == []


def test_runtime_cli_serializes_next_result(monkeypatch, capsys, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.PLAN)
    ref = _write_checkpoint(task_root, "plan", "GO")
    payload = {
        "task_root": str(task_root),
        "source": "checkpoint",
        "current_phase": "plan",
        "pending_approval_for": None,
        "resolved_result_ref": ref,
        "judgement_code": "HOLD",
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-next-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["next_phase"] == "step"
    assert output["deferred_state_transition"]["current_phase"] == "step"


def test_runtime_cli_round_trips_next_actions_into_apply(monkeypatch, capsys, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    _write_state(task_root, CurrentPhase.IMPLEMENTATION, current_step_ref="S1")
    _write_steps(
        task_root,
        "- [ ] Implement one. (go) [step_ref=S1]\n- [ ] Implement two. [step_ref=S2]",
    )
    ref = _write_checkpoint(
        task_root,
        "implementation",
        "GO",
        current_step_ref_snapshot={"step_ref": "S1", "step_text": "Implement one.", "go_marker_present": True},
    )
    next_payload = {
        "task_root": str(task_root),
        "source": "checkpoint",
        "current_phase": "implementation",
        "pending_approval_for": None,
        "resolved_result_ref": ref,
        "judgement_code": "HOLD",
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-next-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(next_payload)))

    assert main() == 0
    next_output = json.loads(capsys.readouterr().out)
    assert next_output["required_artifact_actions"][-1]["params"]["selection_basis"] == {
        "mode": "next_pending_after_current",
        "explicit_step_ref": None,
    }
    assert next_output["required_artifact_actions"][-1]["params"]["current_step_ref_snapshot"] == {
        "step_ref": "S1",
        "step_text": "Implement one.",
        "go_marker_present": True,
    }

    apply_payload = {
        "task_root": str(task_root),
        "required_artifact_actions": next_output["required_artifact_actions"],
        "routing_basis_ref": next_output["routing_basis_ref"],
        "deferred_state_transition": next_output["deferred_state_transition"],
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-apply-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(apply_payload)))

    assert main() == 0
    apply_output = json.loads(capsys.readouterr().out)
    steps = (task_root / "steps.md").read_text(encoding="utf-8")

    assert apply_output["apply_status"] == "APPLIED"
    assert apply_output["current_step_ref_update_mode"] == "set"
    assert apply_output["resolved_current_step_ref"] == "S2"
    assert "- [x] Implement one. [step_ref=S1]" in steps
    assert "- [ ] Implement two. (go) [step_ref=S2]" in steps


def test_runtime_cli_round_trips_closure_approval_into_apply(monkeypatch, capsys, tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    review_ref = "logs/review/review.json"
    _write_state(
        task_root,
        CurrentPhase.REVIEW,
        latest_review_ref=review_ref,
        pending_approval_for="closure",
        session_state=SessionState.AWAITING_APPROVAL,
        review_outcome="DONE",
    )
    _set_state_field(task_root, "approvals_granted", [1, 2])
    next_payload = {
        "task_root": str(task_root),
        "source": "approval",
        "current_phase": "review",
        "pending_approval_for": "closure",
        "resolved_result_ref": None,
        "judgement_code": "DONE",
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-next-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(next_payload)))

    assert main() == 0
    next_output = json.loads(capsys.readouterr().out)
    assert next_output["required_artifact_actions"] == []
    assert next_output["deferred_state_transition"]["session_state"] == "done"
    assert next_output["deferred_state_transition"]["closure_authorized"] is True
    assert next_output["deferred_state_transition"]["approvals_granted"] == [1, 2, 3]

    apply_payload = {
        "task_root": str(task_root),
        "required_artifact_actions": next_output["required_artifact_actions"],
        "routing_basis_ref": next_output["routing_basis_ref"],
        "deferred_state_transition": next_output["deferred_state_transition"],
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-apply-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(apply_payload)))

    assert main() == 0
    apply_output = json.loads(capsys.readouterr().out)
    state = read_state(task_root / "state.json")

    assert apply_output["apply_status"] == "NOOP"
    assert state.session_state == SessionState.DONE
    assert state.current_phase == CurrentPhase.REVIEW
    assert state.pending_approval_for is None
    assert state.closure_authorized is True
    assert state.approvals_granted == [1, 2, 3]
