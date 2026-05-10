"""Deterministic routing helper used by /wf-next."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shared.artifacts.state_artifact import read_state
from harness.shared.contracts.actions import ArtifactAction, ArtifactTarget, CurrentStepRefSnapshot, SelectionBasis, SelectionMode
from harness.shared.contracts.approval import ApprovalPoint, grant_approval
from harness.shared.contracts.results import (
    CheckpointResult,
    JudgementCode,
    NextResult,
    NoteSignal,
    NoteTargetHint,
    ReviewResult,
    VerificationItem,
    VerificationResult,
)
from harness.shared.contracts.state import CurrentPhase, DeferredStateTransition, HarnessCounters, HarnessState, ReviewOutcome, SessionState
from harness.shared.core.state_migration import StateMigrationError
from harness.shared.core.steps_parser import parse_steps
from harness.shared.core.task_paths import get_task_paths


@dataclass(slots=True)
class NextRuntimeInput:
    """Normalized routing input after skill prompt resolution."""

    task_root: Path
    source: str
    current_phase: CurrentPhase
    pending_approval_for: str | None
    resolved_result_ref: str | None
    judgement_code: JudgementCode
    stop_condition_code: str | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if isinstance(self.current_phase, str):
            self.current_phase = CurrentPhase(self.current_phase)
        if isinstance(self.judgement_code, str):
            self.judgement_code = JudgementCode(self.judgement_code)


def execute_next_runtime(input_data: NextRuntimeInput) -> NextResult:
    """Build routing/actions/state transitions from resolved judgement.

    The skill layer resolves ambiguity before calling this helper.
    `resolved_result_ref` is the only canonical result ref consumed here.
    """

    task_paths = get_task_paths(input_data.task_root)
    try:
        state = read_state(task_paths.state_path)
    except (StateMigrationError, KeyError, TypeError, ValueError):
        return _blocked_result_without_state(
            input_data,
            reason_code="STATE_ARTIFACT_INVALID",
            routing_basis_ref="state.json",
        )

    if input_data.source not in {"checkpoint", "verify", "review", "approval"}:
        return _blocked_result(
            state,
            reason_code="NEXT_SOURCE_UNSUPPORTED",
            routing_basis_ref="state.json",
            pending_approval_for=state.pending_approval_for,
        )
    if input_data.source == "approval":
        if _is_repaired_legacy_verification_approval_event(state, input_data):
            return _repaired_legacy_verification_approval_result(state)
        return _route_approval(state, input_data.resolved_result_ref)

    if not input_data.resolved_result_ref:
        return _blocked_result(
            state,
            reason_code="NEXT_RESULT_REF_MISSING",
            routing_basis_ref="state.json",
            pending_approval_for=state.pending_approval_for,
        )

    result_ref = input_data.resolved_result_ref
    if input_data.source == "review":
        if not state.latest_review_ref:
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_MISSING",
                routing_basis_ref="state.json",
                pending_approval_for=state.pending_approval_for,
            )
        if result_ref != state.latest_review_ref:
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_NOT_LATEST",
                routing_basis_ref=result_ref,
                pending_approval_for=state.pending_approval_for,
            )
        try:
            review = _read_review_result(task_paths.task_root, result_ref)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_UNREADABLE",
                routing_basis_ref=result_ref,
                pending_approval_for=state.pending_approval_for,
            )
        return _route_review(state, review, result_ref)

    if input_data.source == "verify":
        if not state.latest_verification_ref:
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_MISSING",
                routing_basis_ref="state.json",
                pending_approval_for=state.pending_approval_for,
            )
        if result_ref != state.latest_verification_ref:
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_NOT_LATEST",
                routing_basis_ref=result_ref,
                pending_approval_for=state.pending_approval_for,
            )
        try:
            verification = _read_verification_result(task_paths.task_root, result_ref)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return _blocked_result(
                state,
                reason_code="NEXT_RESULT_REF_UNREADABLE",
                routing_basis_ref=result_ref,
                pending_approval_for=state.pending_approval_for,
            )
        actions = _plan_note_actions(verification.note_signals, result_ref)
        if actions is None:
            return _blocked_result(
                state,
                reason_code="VERIFY_NOTE_TARGET_INVALID_FOR_PHASE",
                routing_basis_ref=result_ref,
                pending_approval_for=None,
            )
        routed = _route_verify(state, verification, result_ref)
        if routed.reason_code is not None:
            return routed
        routed.required_artifact_actions[:0] = actions
        if routed.deferred_state_transition is None and routed.required_artifact_actions:
            routed.deferred_state_transition = _transition_for(
                state,
                routed.next_session_state,
                routed.next_phase,
                routed.pending_approval_for,
                verification.judgement_code,
                verification.stop_condition_code,
            )
        return routed

    if not state.latest_checkpoint_ref:
        return _blocked_result(
            state,
            reason_code="NEXT_RESULT_REF_MISSING",
            routing_basis_ref="state.json",
            pending_approval_for=state.pending_approval_for,
        )
    if result_ref != state.latest_checkpoint_ref:
        return _blocked_result(
            state,
            reason_code="NEXT_RESULT_REF_NOT_LATEST",
            routing_basis_ref=result_ref,
            pending_approval_for=state.pending_approval_for,
        )
    try:
        checkpoint = _read_checkpoint_result(task_paths.task_root, result_ref)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _blocked_result(
            state,
            reason_code="NEXT_RESULT_REF_UNREADABLE",
            routing_basis_ref=result_ref,
            pending_approval_for=state.pending_approval_for,
        )

    actions = _note_actions(checkpoint, result_ref)
    if actions is None:
        return _blocked_result(
            state,
            reason_code="CHECKPOINT_NOTE_TARGET_INVALID_FOR_PHASE",
            routing_basis_ref=result_ref,
            pending_approval_for=None,
        )

    routed = _route_checkpoint(task_paths.task_root, state, checkpoint, result_ref)
    if routed.reason_code is not None:
        return routed
    routed.required_artifact_actions[:0] = actions
    if routed.deferred_state_transition is None and routed.required_artifact_actions:
        routed.deferred_state_transition = _transition_for(
            state,
            routed.next_session_state,
            routed.next_phase,
            routed.pending_approval_for,
            checkpoint.judgement_code,
            None,
        )
    return routed


def _route_approval(state: HarnessState, latest_result_ref: str | None) -> NextResult:
    pending = state.pending_approval_for
    if pending is None:
        return _blocked_result(state, "NEXT_APPROVAL_CONTEXT_INVALID", "state.json", None)

    if pending == ApprovalPoint.PRE_PLAN_TO_PLAN.value:
        if state.session_state != SessionState.AWAITING_APPROVAL or state.current_phase != CurrentPhase.PRE_PLANNING:
            return _blocked_result(state, "NEXT_APPROVAL_CONTEXT_INVALID", "state.json", None)
        if not state.latest_checkpoint_ref:
            return _blocked_result(state, "NEXT_RESULT_REF_MISSING", "state.json", pending)
        if latest_result_ref is not None and latest_result_ref != state.latest_checkpoint_ref:
            return _blocked_result(state, "NEXT_APPROVAL_RESULT_REF_MISMATCH", "state.json", pending)
        return _approval_result(
            state,
            routing_basis_ref=state.latest_checkpoint_ref,
            next_phase=CurrentPhase.PLAN,
            next_session_state=SessionState.IN_PROGRESS,
            pending_approval_for=None,
            closure_authorized=state.closure_authorized,
            approval_point=ApprovalPoint.PRE_PLAN_TO_PLAN,
        )

    if pending == ApprovalPoint.PLAN_TO_IMPLEMENTATION.value:
        if state.session_state != SessionState.AWAITING_APPROVAL or state.current_phase != CurrentPhase.STEP:
            return _blocked_result(state, "NEXT_APPROVAL_CONTEXT_INVALID", "state.json", None)
        if not state.latest_checkpoint_ref:
            return _blocked_result(state, "NEXT_RESULT_REF_MISSING", "state.json", pending)
        if latest_result_ref is not None and latest_result_ref != state.latest_checkpoint_ref:
            return _blocked_result(state, "NEXT_APPROVAL_RESULT_REF_MISMATCH", "state.json", pending)
        return _approval_result(
            state,
            routing_basis_ref=state.latest_checkpoint_ref,
            next_phase=CurrentPhase.IMPLEMENTATION,
            next_session_state=SessionState.IN_PROGRESS,
            pending_approval_for=None,
            closure_authorized=state.closure_authorized,
            approval_point=ApprovalPoint.PLAN_TO_IMPLEMENTATION,
        )

    if pending == ApprovalPoint.CLOSURE.value:
        if (
            state.session_state != SessionState.AWAITING_APPROVAL
            or state.current_phase != CurrentPhase.REVIEW
            or state.review_outcome not in {ReviewOutcome.DONE, ReviewOutcome.DONE_WITH_NOTE}
        ):
            return _blocked_result(state, "NEXT_APPROVAL_CONTEXT_INVALID", "state.json", None)
        if not state.latest_review_ref:
            return _blocked_result(state, "NEXT_RESULT_REF_MISSING", "state.json", pending)
        if latest_result_ref is not None and latest_result_ref != state.latest_review_ref:
            return _blocked_result(state, "NEXT_APPROVAL_RESULT_REF_MISMATCH", "state.json", pending)
        return _approval_result(
            state,
            routing_basis_ref=state.latest_review_ref,
            next_phase=CurrentPhase.REVIEW,
            next_session_state=SessionState.DONE,
            pending_approval_for=None,
            closure_authorized=True,
            approval_point=ApprovalPoint.CLOSURE,
        )

    return _blocked_result(state, "NEXT_APPROVAL_CONTEXT_INVALID", "state.json", None)


def _is_repaired_legacy_verification_approval_event(state: HarnessState, input_data: NextRuntimeInput) -> bool:
    if state.pending_approval_for is not None:
        return False
    if state.session_state != SessionState.IN_PROGRESS or state.current_phase != CurrentPhase.VERIFICATION:
        return False
    return input_data.pending_approval_for == "verification_entry"


def _repaired_legacy_verification_approval_result(state: HarnessState) -> NextResult:
    routing_basis_ref = state.latest_checkpoint_ref or "state.json"
    return NextResult(
        next_phase=CurrentPhase.VERIFICATION,
        next_session_state=SessionState.IN_PROGRESS,
        pending_approval_for=None,
        required_artifact_actions=[],
        reason_code=None,
        routing_basis_ref=routing_basis_ref,
        deferred_state_transition=DeferredStateTransition(
            session_state=SessionState.IN_PROGRESS,
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for=None,
            review_outcome=state.review_outcome,
            closure_authorized=state.closure_authorized,
            counters=state.counters,
            blocked_transition=state.blocked_transition,
            blocked_reason_ref=state.blocked_reason_ref,
            stop_condition_ref=state.stop_condition_ref,
            approvals_granted=state.approvals_granted,
        ),
    )


def _resolve_task_ref(task_root: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return task_root / path


def _read_checkpoint_result(task_root: Path, ref: str) -> CheckpointResult:
    payload = json.loads(_resolve_task_ref(task_root, ref).read_text(encoding="utf-8"))
    snapshot_payload = payload.get("current_step_ref_snapshot")
    snapshot = None
    if snapshot_payload is not None:
        snapshot = CurrentStepRefSnapshot(
            step_ref=str(snapshot_payload["step_ref"]),
            step_text=str(snapshot_payload["step_text"]),
            go_marker_present=bool(snapshot_payload["go_marker_present"]),
        )
    return CheckpointResult(
        checkpoint_ref=str(payload["checkpoint_ref"]),
        phase=CurrentPhase(payload["phase"]),
        judgement_code=JudgementCode(payload["judgement_code"]),
        summary=str(payload["summary"]),
        basis_refs=[str(ref_item) for ref_item in payload.get("basis_refs", [])],
        note_signals=[
            NoteSignal(
                note_text=str(note["note_text"]),
                note_target_hint=NoteTargetHint(note["note_target_hint"]),
                note_basis_refs=[str(ref_item) for ref_item in note.get("note_basis_refs", [])],
            )
            for note in payload.get("note_signals", [])
        ],
        stop_condition_code=payload.get("stop_condition_code"),
        primary_cause_code=payload.get("primary_cause_code"),
        reason_fingerprint=payload.get("reason_fingerprint"),
        current_step_ref_snapshot=snapshot,
    )


def _read_verification_result(task_root: Path, ref: str) -> VerificationResult:
    payload = json.loads(_resolve_task_ref(task_root, ref).read_text(encoding="utf-8"))
    return VerificationResult(
        verification_ref=str(payload["verification_ref"]),
        judgement_code=JudgementCode(payload["judgement_code"]),
        summary=str(payload["summary"]),
        verification_items=[
            VerificationItem(
                item_key=str(item["item_key"]),
                item_type=str(item["item_type"]),
                label=str(item["label"]),
                method=str(item["method"]),
                result=str(item["result"]),
                summary=str(item["summary"]),
                basis_refs=[str(ref_item) for ref_item in item.get("basis_refs", [])],
            )
            for item in payload.get("verification_items", [])
        ],
        basis_refs=[str(ref_item) for ref_item in payload.get("basis_refs", [])],
        note_signals=[
            NoteSignal(
                note_text=str(note["note_text"]),
                note_target_hint=NoteTargetHint(note["note_target_hint"]),
                note_basis_refs=[str(ref_item) for ref_item in note.get("note_basis_refs", [])],
            )
            for note in payload.get("note_signals", [])
        ],
        verified_task_diff_fingerprint=str(payload["verified_task_diff_fingerprint"]),
        stop_condition_code=payload.get("stop_condition_code"),
        primary_cause_code=payload.get("primary_cause_code"),
        reason_fingerprint=payload.get("reason_fingerprint"),
    )


def _read_review_result(task_root: Path, ref: str) -> ReviewResult:
    payload = json.loads(_resolve_task_ref(task_root, ref).read_text(encoding="utf-8"))
    return ReviewResult(
        review_ref=str(payload["review_ref"]),
        judgement_code=JudgementCode(payload["judgement_code"]),
        summary=str(payload["summary"]),
        out_of_scope_change=_strict_bool(payload["out_of_scope_change"]),
        key_issues=[str(item) for item in payload.get("key_issues", [])],
        verification_blind_spots=[str(item) for item in payload.get("verification_blind_spots", [])],
        carry_forward_notes=[str(item) for item in payload.get("carry_forward_notes", [])],
        basis_refs=[str(item) for item in payload.get("basis_refs", [])],
        verified_task_diff_fingerprint=payload.get("verified_task_diff_fingerprint"),
        primary_cause_code=payload.get("primary_cause_code"),
        reason_fingerprint=payload.get("reason_fingerprint"),
    )


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("Boolean field must be a JSON boolean.")


def _plan_note_actions(note_signals: list[NoteSignal], basis_ref: str) -> list[ArtifactAction] | None:
    actions: list[ArtifactAction] = []
    for note in note_signals:
        if note.note_target_hint != NoteTargetHint.PLAN:
            return None
        actions.append(
            ArtifactAction(
                target=ArtifactTarget.PLAN,
                action="plan.record_contract_note",
                params={"note_text": note.note_text, "note_basis_refs": note.note_basis_refs},
                basis_ref=basis_ref,
            )
        )
    return actions


def _note_actions(checkpoint: CheckpointResult, basis_ref: str) -> list[ArtifactAction] | None:
    actions: list[ArtifactAction] = []
    for note in checkpoint.note_signals:
        if note.note_target_hint == NoteTargetHint.PLAN:
            actions.append(
                ArtifactAction(
                    target=ArtifactTarget.PLAN,
                    action="plan.record_contract_note",
                    params={"note_text": note.note_text, "note_basis_refs": note.note_basis_refs},
                    basis_ref=basis_ref,
                )
            )
            continue
        if note.note_target_hint == NoteTargetHint.STEPS:
            if checkpoint.current_step_ref_snapshot is None:
                return None
            actions.append(
                ArtifactAction(
                    target=ArtifactTarget.STEPS,
                    action="steps.record_working_note",
                    params={
                        "current_step_ref_snapshot": checkpoint.current_step_ref_snapshot,
                        "note_text": note.note_text,
                        "note_basis_refs": note.note_basis_refs,
                    },
                    basis_ref=basis_ref,
                )
            )
            continue
        return None
    return actions


def _blocked_result(
    state: HarnessState,
    reason_code: str,
    routing_basis_ref: str,
    pending_approval_for: str | None,
) -> NextResult:
    return NextResult(
        next_phase=state.current_phase,
        next_session_state=SessionState.PAUSED,
        pending_approval_for=pending_approval_for,
        required_artifact_actions=[],
        reason_code=reason_code,
        routing_basis_ref=routing_basis_ref,
        deferred_state_transition=DeferredStateTransition(
            session_state=SessionState.PAUSED,
            current_phase=state.current_phase,
            pending_approval_for=pending_approval_for,
            review_outcome=state.review_outcome,
            closure_authorized=state.closure_authorized,
            counters=state.counters,
            blocked_transition="wf-next",
            blocked_reason_ref=routing_basis_ref,
            stop_condition_ref=state.stop_condition_ref,
            approvals_granted=state.approvals_granted,
        ),
    )


def _blocked_result_without_state(
    input_data: NextRuntimeInput,
    *,
    reason_code: str,
    routing_basis_ref: str,
) -> NextResult:
    return NextResult(
        next_phase=input_data.current_phase,
        next_session_state=SessionState.PAUSED,
        pending_approval_for=input_data.pending_approval_for,
        required_artifact_actions=[],
        reason_code=reason_code,
        routing_basis_ref=routing_basis_ref,
        deferred_state_transition=None,
    )


def _transition_for(
    state: HarnessState,
    session_state: SessionState,
    phase: CurrentPhase,
    pending_approval_for: str | None,
    judgement_code: JudgementCode,
    stop_condition_code: str | None,
) -> DeferredStateTransition:
    counters = HarnessCounters(
        rework_count=state.counters.rework_count + (1 if judgement_code == JudgementCode.REWORK else 0),
        rewrite_count=state.counters.rewrite_count
        + (1 if judgement_code in {JudgementCode.REWRITE_PLAN, JudgementCode.REWRITE_STEP} else 0),
        rollback_count=state.counters.rollback_count + (1 if judgement_code == JudgementCode.ROLLBACK else 0),
    )
    return DeferredStateTransition(
        session_state=session_state,
        current_phase=phase,
        pending_approval_for=pending_approval_for,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters=counters,
        stop_condition_ref=stop_condition_code,
        approvals_granted=state.approvals_granted,
    )


def _result(
    state: HarnessState,
    checkpoint: CheckpointResult,
    result_ref: str,
    next_phase: CurrentPhase,
    next_session_state: SessionState,
    pending_approval_for: str | None,
    actions: list[ArtifactAction],
) -> NextResult:
    return NextResult(
        next_phase=next_phase,
        next_session_state=next_session_state,
        pending_approval_for=pending_approval_for,
        required_artifact_actions=actions,
        reason_code=None,
        routing_basis_ref=result_ref,
        deferred_state_transition=_transition_for(
            state,
            next_session_state,
            next_phase,
            pending_approval_for,
            checkpoint.judgement_code,
            checkpoint.stop_condition_code,
        ),
    )


def _verification_result(
    state: HarnessState,
    verification: VerificationResult,
    result_ref: str,
    next_phase: CurrentPhase,
    next_session_state: SessionState,
    pending_approval_for: str | None,
    actions: list[ArtifactAction],
) -> NextResult:
    return NextResult(
        next_phase=next_phase,
        next_session_state=next_session_state,
        pending_approval_for=pending_approval_for,
        required_artifact_actions=actions,
        reason_code=None,
        routing_basis_ref=result_ref,
        deferred_state_transition=_transition_for(
            state,
            next_session_state,
            next_phase,
            pending_approval_for,
            verification.judgement_code,
            verification.stop_condition_code,
        ),
    )


def _review_result(
    state: HarnessState,
    review: ReviewResult,
    result_ref: str,
    next_phase: CurrentPhase,
    next_session_state: SessionState,
    pending_approval_for: str | None,
    actions: list[ArtifactAction],
    review_outcome: ReviewOutcome,
    closure_authorized: bool = False,
) -> NextResult:
    return NextResult(
        next_phase=next_phase,
        next_session_state=next_session_state,
        pending_approval_for=pending_approval_for,
        required_artifact_actions=actions,
        reason_code=None,
        routing_basis_ref=result_ref,
        deferred_state_transition=_review_transition_for(
            state,
            next_session_state,
            next_phase,
            pending_approval_for,
            review.judgement_code,
            review_outcome,
            closure_authorized,
        ),
    )


def _approval_result(
    state: HarnessState,
    routing_basis_ref: str,
    next_phase: CurrentPhase,
    next_session_state: SessionState,
    pending_approval_for: str | None,
    closure_authorized: bool,
    approval_point: ApprovalPoint,
) -> NextResult:
    approvals_granted = grant_approval(state.approvals_granted, approval_point)
    return NextResult(
        next_phase=next_phase,
        next_session_state=next_session_state,
        pending_approval_for=pending_approval_for,
        required_artifact_actions=[],
        reason_code=None,
        routing_basis_ref=routing_basis_ref,
        deferred_state_transition=DeferredStateTransition(
            session_state=next_session_state,
            current_phase=next_phase,
            pending_approval_for=pending_approval_for,
            review_outcome=state.review_outcome,
            closure_authorized=closure_authorized,
            counters=state.counters,
            blocked_transition=state.blocked_transition,
            blocked_reason_ref=state.blocked_reason_ref,
            stop_condition_ref=state.stop_condition_ref,
            approvals_granted=approvals_granted,
        ),
    )


def _review_transition_for(
    state: HarnessState,
    session_state: SessionState,
    phase: CurrentPhase,
    pending_approval_for: str | None,
    judgement_code: JudgementCode,
    review_outcome: ReviewOutcome,
    closure_authorized: bool,
) -> DeferredStateTransition:
    counters = HarnessCounters(
        rework_count=state.counters.rework_count + (1 if judgement_code == JudgementCode.REWORK else 0),
        rewrite_count=state.counters.rewrite_count + (1 if judgement_code == JudgementCode.REWRITE_PLAN else 0),
        rollback_count=state.counters.rollback_count,
    )
    return DeferredStateTransition(
        session_state=session_state,
        current_phase=phase,
        pending_approval_for=pending_approval_for,
        review_outcome=review_outcome,
        closure_authorized=closure_authorized,
        counters=counters,
        blocked_transition=state.blocked_transition,
        blocked_reason_ref=state.blocked_reason_ref,
        stop_condition_ref=state.stop_condition_ref,
        approvals_granted=state.approvals_granted,
    )


def _rewrite_reason(checkpoint: CheckpointResult) -> str:
    return checkpoint.primary_cause_code or checkpoint.judgement_code.value


def _verification_rewrite_reason(verification: VerificationResult) -> str:
    return verification.primary_cause_code or verification.judgement_code.value


def _review_rewrite_reason(review: ReviewResult) -> str:
    return review.primary_cause_code or review.judgement_code.value


def _plan_rewrite_action(checkpoint: CheckpointResult, result_ref: str) -> ArtifactAction:
    return ArtifactAction(
        target=ArtifactTarget.PLAN,
        action="plan.rewrite_required",
        params={"rewrite_reason_code": _rewrite_reason(checkpoint)},
        basis_ref=result_ref,
    )


def _plan_rewrite_action_from_verify(verification: VerificationResult, result_ref: str) -> ArtifactAction:
    return ArtifactAction(
        target=ArtifactTarget.PLAN,
        action="plan.rewrite_required",
        params={"rewrite_reason_code": _verification_rewrite_reason(verification)},
        basis_ref=result_ref,
    )


def _plan_rewrite_action_from_review(review: ReviewResult, result_ref: str) -> ArtifactAction:
    return ArtifactAction(
        target=ArtifactTarget.PLAN,
        action="plan.rewrite_required",
        params={"rewrite_reason_code": _review_rewrite_reason(review)},
        basis_ref=result_ref,
    )


def _steps_rewrite_action(checkpoint: CheckpointResult, result_ref: str) -> ArtifactAction | None:
    if checkpoint.current_step_ref_snapshot is None:
        return None
    return ArtifactAction(
        target=ArtifactTarget.STEPS,
        action="steps.rewrite_required",
        params={
            "current_step_ref_snapshot": checkpoint.current_step_ref_snapshot,
            "rewrite_reason_code": _rewrite_reason(checkpoint),
        },
        basis_ref=result_ref,
    )


def _route_checkpoint(task_root: Path, state: HarnessState, checkpoint: CheckpointResult, result_ref: str) -> NextResult:
    judgement = checkpoint.judgement_code
    phase = checkpoint.phase

    if phase == CurrentPhase.PRE_PLANNING:
        if judgement in {JudgementCode.GO, JudgementCode.GO_WITH_NOTE}:
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.PRE_PLANNING,
                SessionState.AWAITING_APPROVAL,
                ApprovalPoint.PRE_PLAN_TO_PLAN.value,
                [],
            )
        if judgement == JudgementCode.REWRITE_PLAN:
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.PRE_PLANNING,
                SessionState.IN_PROGRESS,
                None,
                [_plan_rewrite_action(checkpoint, result_ref)],
            )
        return _result(state, checkpoint, result_ref, CurrentPhase.PRE_PLANNING, SessionState.PAUSED, None, [])

    if phase == CurrentPhase.PLAN:
        if judgement in {JudgementCode.GO, JudgementCode.GO_WITH_NOTE}:
            return _result(state, checkpoint, result_ref, CurrentPhase.STEP, SessionState.IN_PROGRESS, None, [])
        if judgement == JudgementCode.REWRITE_PLAN:
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.PLAN,
                SessionState.IN_PROGRESS,
                None,
                [_plan_rewrite_action(checkpoint, result_ref)],
            )
        return _result(state, checkpoint, result_ref, CurrentPhase.PLAN, SessionState.PAUSED, None, [])

    if phase == CurrentPhase.STEP:
        if judgement in {JudgementCode.GO, JudgementCode.GO_WITH_NOTE}:
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.STEP,
                SessionState.AWAITING_APPROVAL,
                ApprovalPoint.PLAN_TO_IMPLEMENTATION.value,
                [],
            )
        if judgement == JudgementCode.REWRITE_STEP:
            action = _steps_rewrite_action(checkpoint, result_ref)
            if action is None:
                return _blocked_result(state, "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE", "state.json", state.pending_approval_for)
            return _result(state, checkpoint, result_ref, CurrentPhase.STEP, SessionState.IN_PROGRESS, None, [action])
        if judgement == JudgementCode.REWRITE_PLAN:
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.PLAN,
                SessionState.IN_PROGRESS,
                None,
                [_plan_rewrite_action(checkpoint, result_ref)],
            )
        return _result(state, checkpoint, result_ref, CurrentPhase.STEP, SessionState.PAUSED, None, [])

    if phase == CurrentPhase.IMPLEMENTATION:
        return _route_implementation(task_root, state, checkpoint, result_ref)

    return _blocked_result(state, "NEXT_CHECKPOINT_PHASE_UNSUPPORTED", result_ref, state.pending_approval_for)


def _route_verify(state: HarnessState, verification: VerificationResult, result_ref: str) -> NextResult:
    judgement = verification.judgement_code
    if judgement in {JudgementCode.GO, JudgementCode.GO_WITH_NOTE}:
        return _verification_result(state, verification, result_ref, CurrentPhase.REVIEW, SessionState.IN_PROGRESS, None, [])
    if judgement == JudgementCode.REWORK:
        return _verification_result(
            state,
            verification,
            result_ref,
            CurrentPhase.VERIFICATION,
            SessionState.IN_PROGRESS,
            None,
            [],
        )
    if judgement == JudgementCode.REWRITE_STEP:
        return _verification_result(state, verification, result_ref, CurrentPhase.STEP, SessionState.IN_PROGRESS, None, [])
    if judgement == JudgementCode.REWRITE_PLAN:
        return _verification_result(
            state,
            verification,
            result_ref,
            CurrentPhase.PLAN,
            SessionState.IN_PROGRESS,
            None,
            [_plan_rewrite_action_from_verify(verification, result_ref)],
        )
    if judgement not in {JudgementCode.ROLLBACK, JudgementCode.HOLD}:
        return _blocked_result(state, "NEXT_VERIFY_JUDGEMENT_UNSUPPORTED", result_ref, state.pending_approval_for)
    return _verification_result(
        state,
        verification,
        result_ref,
        CurrentPhase.VERIFICATION,
        SessionState.PAUSED,
        None,
        [],
    )


def _route_review(state: HarnessState, review: ReviewResult, result_ref: str) -> NextResult:
    judgement = review.judgement_code
    if judgement == JudgementCode.DONE:
        return _review_result(
            state,
            review,
            result_ref,
            CurrentPhase.REVIEW,
            SessionState.AWAITING_APPROVAL,
            ApprovalPoint.CLOSURE.value,
            [],
            ReviewOutcome.DONE,
        )
    if judgement == JudgementCode.DONE_WITH_NOTE:
        return _review_result(
            state,
            review,
            result_ref,
            CurrentPhase.REVIEW,
            SessionState.AWAITING_APPROVAL,
            ApprovalPoint.CLOSURE.value,
            [],
            ReviewOutcome.DONE_WITH_NOTE,
        )
    if judgement == JudgementCode.REWORK:
        return _review_result(
            state,
            review,
            result_ref,
            CurrentPhase.STEP,
            SessionState.IN_PROGRESS,
            None,
            [],
            ReviewOutcome.REWORK,
        )
    if judgement == JudgementCode.REWRITE_PLAN:
        return _review_result(
            state,
            review,
            result_ref,
            CurrentPhase.PLAN,
            SessionState.IN_PROGRESS,
            None,
            [_plan_rewrite_action_from_review(review, result_ref)],
            ReviewOutcome.REWRITE_PLAN,
        )
    if judgement == JudgementCode.HOLD:
        return _review_result(
            state,
            review,
            result_ref,
            CurrentPhase.REVIEW,
            SessionState.PAUSED,
            None,
            [],
            ReviewOutcome.HOLD,
        )
    return _blocked_result(state, "NEXT_REVIEW_JUDGEMENT_UNSUPPORTED", result_ref, state.pending_approval_for)


def _route_implementation(
    task_root: Path,
    state: HarnessState,
    checkpoint: CheckpointResult,
    result_ref: str,
) -> NextResult:
    judgement = checkpoint.judgement_code
    if judgement in {JudgementCode.GO, JudgementCode.GO_WITH_NOTE}:
        snapshot = checkpoint.current_step_ref_snapshot
        if snapshot is None:
            return _blocked_result(state, "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE", "state.json", state.pending_approval_for)
        remaining = _has_pending_step_after_current(task_root / "steps.md", snapshot.step_ref)
        if remaining is None:
            return _blocked_result(state, "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE", "state.json", state.pending_approval_for)
        actions = [
            _step_action("steps.mark_current_step_done", snapshot, result_ref),
            _step_action("steps.clear_current_step", snapshot, result_ref),
        ]
        if remaining:
            actions.append(
                _step_action(
                    "steps.select_next_go_step",
                    snapshot,
                    result_ref,
                    {"selection_basis": SelectionBasis(mode=SelectionMode.NEXT_PENDING_AFTER_CURRENT)},
                )
            )
            return _result(
                state,
                checkpoint,
                result_ref,
                CurrentPhase.IMPLEMENTATION,
                SessionState.IN_PROGRESS,
                None,
                actions,
            )
        return _result(
            state,
            checkpoint,
            result_ref,
            CurrentPhase.VERIFICATION,
            SessionState.IN_PROGRESS,
            None,
            actions,
        )

    if judgement == JudgementCode.REWORK:
        return _result(state, checkpoint, result_ref, CurrentPhase.IMPLEMENTATION, SessionState.IN_PROGRESS, None, [])
    if judgement == JudgementCode.REWRITE_STEP:
        action = _steps_rewrite_action(checkpoint, result_ref)
        if action is None:
            return _blocked_result(state, "NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE", "state.json", state.pending_approval_for)
        return _result(state, checkpoint, result_ref, CurrentPhase.STEP, SessionState.IN_PROGRESS, None, [action])
    if judgement == JudgementCode.REWRITE_PLAN:
        return _result(
            state,
            checkpoint,
            result_ref,
            CurrentPhase.PLAN,
            SessionState.IN_PROGRESS,
            None,
            [_plan_rewrite_action(checkpoint, result_ref)],
        )
    return _result(state, checkpoint, result_ref, CurrentPhase.IMPLEMENTATION, SessionState.PAUSED, None, [])


def _step_action(
    action: str,
    snapshot: CurrentStepRefSnapshot,
    basis_ref: str,
    extra_params: dict[str, Any] | None = None,
) -> ArtifactAction:
    params: dict[str, Any] = {"current_step_ref_snapshot": snapshot}
    if extra_params:
        params.update(extra_params)
    return ArtifactAction(
        target=ArtifactTarget.STEPS,
        action=action,
        params=params,
        basis_ref=basis_ref,
    )


def _has_pending_step_after_current(steps_path: Path, current_step_ref: str) -> bool | None:
    try:
        content = steps_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed = parse_steps(content)
    if parsed.reason_code is not None:
        return None
    seen_current = False
    for step in parsed.steps:
        if step.step_ref == current_step_ref:
            seen_current = True
            continue
        if seen_current and step.mark == " ":
            return True
    if not seen_current:
        return None
    return False
