"""Deterministic helper for checkpoint persistence and sink updates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.actions import CurrentStepRefSnapshot
from harness.shared.contracts.profile import RepoProfile
from harness.shared.contracts.results import CheckItem, CheckpointResult, JudgementCode, NoteSignal, NoteTargetHint
from harness.shared.contracts.state import CurrentPhase, HarnessState
from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.phase_spec_loader import PhaseSpec, PhaseSpecLoadError, load_phase_spec, resolve_workspace_root
from harness.shared.core.task_paths import get_task_paths
from harness.shared.core.timestamp import kst_now_human, kst_now_iso


CAUSE_REQUIRED_JUDGEMENTS = {
    JudgementCode.REWORK,
    JudgementCode.REWRITE_STEP,
    JudgementCode.REWRITE_PLAN,
    JudgementCode.ROLLBACK,
    JudgementCode.HOLD,
}

CHECK_ITEM_RESULTS = {"YES", "NO", "N/A"}


@dataclass(slots=True)
class CheckpointRuntimeInput:
    """Structured checkpoint result emitted by the skill prompt."""

    task_root: Path
    checkpoint_result: CheckpointResult
    workspace_root: Path | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root)
        if isinstance(self.checkpoint_result, dict):
            self.checkpoint_result = _checkpoint_result_from_payload(self.checkpoint_result)


def _kst_timestamp() -> str:
    return kst_now_iso()


def _checkpoint_result_from_payload(payload: dict[str, Any]) -> CheckpointResult:
    snapshot_payload = payload.get("current_step_ref_snapshot")
    snapshot = None
    if snapshot_payload is not None:
        snapshot = CurrentStepRefSnapshot(
            step_ref=str(snapshot_payload["step_ref"]),
            step_text=str(snapshot_payload["step_text"]),
            go_marker_present=bool(snapshot_payload["go_marker_present"]),
        )

    return CheckpointResult(
        checkpoint_ref=str(payload.get("checkpoint_ref") or ""),
        phase=CurrentPhase(payload["phase"]),
        judgement_code=JudgementCode(payload["judgement_code"]),
        summary=str(payload["summary"]),
        check_items=[
            CheckItem(
                item_index=int(item["item_index"]),
                item_text=str(item["item_text"]),
                result=str(item["result"]),
                rationale=str(item["rationale"]),
                basis_refs=[str(ref) for ref in item.get("basis_refs", [])],
            )
            for item in payload.get("check_items", [])
        ],
        basis_refs=[str(ref) for ref in payload.get("basis_refs", [])],
        note_signals=[
            NoteSignal(
                note_text=str(note["note_text"]),
                note_target_hint=NoteTargetHint(note["note_target_hint"]),
                note_basis_refs=[str(ref) for ref in note.get("note_basis_refs", [])],
            )
            for note in payload.get("note_signals", [])
        ],
        stop_condition_code=payload.get("stop_condition_code"),
        primary_cause_code=payload.get("primary_cause_code"),
        reason_fingerprint=payload.get("reason_fingerprint"),
        current_step_ref_snapshot=snapshot,
    )


def _checkpoint_payload(
    result: CheckpointResult,
    persisted_at: str,
    repo_profile: RepoProfile | None = None,
) -> dict[str, Any]:
    payload = asdict(result)
    payload["phase"] = result.phase.value
    payload["judgement_code"] = result.judgement_code.value
    payload["note_signals"] = [
        {
            "note_text": note.note_text,
            "note_target_hint": note.note_target_hint.value,
            "note_basis_refs": note.note_basis_refs,
        }
        for note in result.note_signals
    ]
    payload["persisted_at"] = persisted_at
    profile_context = _checkpoint_profile_context(repo_profile, result.phase)
    if profile_context is not None:
        payload["repo_profile_context"] = profile_context
    return payload


def _checkpoint_profile_context(repo_profile: RepoProfile | None, phase: CurrentPhase) -> dict[str, Any] | None:
    if repo_profile is None:
        return None
    applicable_supplements = sorted(
        supplement.supplement_id
        for supplement in repo_profile.checkpoint_supplements.values()
        if supplement.applies_to_phase == phase.value
    )
    return {
        "profile_id": repo_profile.profile_id,
        "profile_version": repo_profile.profile_version,
        "applicable_checkpoint_supplements": applicable_supplements,
    }


def _with_latest_checkpoint_ref(state: HarnessState, checkpoint_ref: str) -> HarnessState:
    return HarnessState(
        schema_version=state.schema_version,
        session_state=state.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=state.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=state.current_step_ref,
        latest_checkpoint_ref=checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=state.pending_approval_for,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters=state.counters,
        blocked_transition=state.blocked_transition,
        blocked_reason_ref=state.blocked_reason_ref,
        stop_condition_ref=state.stop_condition_ref,
        last_updated=kst_now_human(),
        approvals_granted=state.approvals_granted,
        adapter_meta=state.adapter_meta,
    )


def _blocked_checkpoint_output(reason_code: str, message_summary: str | None = None) -> dict[str, object]:
    return {
        "checkpoint_ref": None,
        "latest_checkpoint_ref": None,
        "reason_code": reason_code,
        "message_summary": message_summary or f"Checkpoint blocked: {reason_code}",
    }


def _validate_checkpoint_result(result: CheckpointResult, state: HarnessState, phase_spec: PhaseSpec) -> str | None:
    if not result.summary.strip():
        return "CHECKPOINT_RESULT_CONTRACT_INVALID"
    if result.phase != state.current_phase:
        return "CHECKPOINT_PHASE_MISMATCH"
    if result.judgement_code.value not in phase_spec.allowed_judgements:
        return "CHECKPOINT_JUDGEMENT_INVALID"
    if result.judgement_code == JudgementCode.GO_WITH_NOTE and not result.note_signals:
        return "CHECKPOINT_NOTE_SIGNALS_INVALID"
    if result.judgement_code != JudgementCode.GO_WITH_NOTE and result.note_signals:
        return "CHECKPOINT_NOTE_SIGNALS_INVALID"
    if result.judgement_code in CAUSE_REQUIRED_JUDGEMENTS:
        if not result.primary_cause_code or not result.reason_fingerprint:
            return "CHECKPOINT_REASON_REQUIRED"

    if result.phase in {CurrentPhase.PRE_PLANNING, CurrentPhase.PLAN}:
        if result.current_step_ref_snapshot is not None:
            return "CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID"
    else:
        if result.current_step_ref_snapshot is None:
            return "CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID"
        if result.current_step_ref_snapshot.step_ref != state.current_step_ref:
            return "CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID"

    for note in result.note_signals:
        if result.phase in {CurrentPhase.PRE_PLANNING, CurrentPhase.PLAN} and note.note_target_hint != NoteTargetHint.PLAN:
            return "CHECKPOINT_NOTE_TARGET_INVALID"
        if note.note_target_hint == NoteTargetHint.STEPS and result.current_step_ref_snapshot is None:
            return "CHECKPOINT_NOTE_TARGET_INVALID"
        if not note.note_text.strip():
            return "CHECKPOINT_NOTE_SIGNALS_INVALID"

    if len(result.check_items) != len(phase_spec.checkpoint_items):
        return "CHECKPOINT_CHECK_ITEMS_INCOMPLETE"

    for expected_index, item in enumerate(result.check_items, start=1):
        if item.item_index != expected_index:
            return "CHECKPOINT_CHECK_ITEMS_INCOMPLETE"
        if item.result not in CHECK_ITEM_RESULTS:
            return "CHECKPOINT_CHECK_ITEM_INVALID"
        if not item.item_text.strip() or not item.rationale.strip():
            return "CHECKPOINT_CHECK_ITEM_INVALID"
        if item.result == "YES" and not item.basis_refs:
            return "CHECKPOINT_CHECK_ITEM_INVALID"

    return None


def persist_checkpoint_runtime(input_data: CheckpointRuntimeInput) -> dict[str, object]:
    """Persist checkpoint logs/state after the prompt finishes its evaluation."""

    task_paths = get_task_paths(input_data.task_root)
    try:
        workspace_root = resolve_workspace_root(input_data.workspace_root)
    except PhaseSpecLoadError:
        return _blocked_checkpoint_output(
            "CHECKPOINT_WORKSPACE_ROOT_MISSING",
            "`/wf-checkpoint` requires an explicit workspace_root.",
        )

    if not task_paths.state_path.exists():
        guard_decision = run_guard(
            GuardInput(
                action="wf-checkpoint",
                task_root=task_paths.task_root,
                state=None,
                context={
                    "phase": input_data.checkpoint_result.phase.value,
                    "workspace_root": workspace_root,
                },
            )
        )
        return _blocked_checkpoint_output(
            guard_decision.reason_code or "STATE_ARTIFACT_MISSING",
            guard_decision.message_summary,
        )

    state = read_state(task_paths.state_path)
    result = input_data.checkpoint_result
    guard_decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=task_paths.task_root,
            state=state,
            context={
                "phase": result.phase.value,
                "workspace_root": workspace_root,
            },
        )
    )
    if not guard_decision.allow:
        return _blocked_checkpoint_output(
            guard_decision.reason_code or "CHECKPOINT_GUARD_BLOCKED",
            guard_decision.message_summary,
        )

    try:
        phase_spec = load_phase_spec(result.phase.value, workspace_root=workspace_root)
    except PhaseSpecLoadError:
        return _blocked_checkpoint_output(
            "CHECKPOINT_PHASE_SPEC_UNAVAILABLE",
            "Checkpoint phase spec could not be loaded.",
        )

    invalid_reason = _validate_checkpoint_result(result, state, phase_spec)
    if invalid_reason is not None:
        return _blocked_checkpoint_output(invalid_reason)

    checkpoint_path = reserve_log_path(task_paths.logs_dir, "checkpoints")
    checkpoint_ref = log_ref_for_path(task_paths.logs_dir, checkpoint_path)
    result.checkpoint_ref = checkpoint_ref
    final_payload = _checkpoint_payload(result, persisted_at=_kst_timestamp(), repo_profile=guard_decision.repo_profile)
    checkpoint_path.write_text(
        json.dumps(final_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    write_state(task_paths.state_path, _with_latest_checkpoint_ref(state, checkpoint_ref))

    return {
        "checkpoint_ref": checkpoint_ref,
        "latest_checkpoint_ref": checkpoint_ref,
        "reason_code": None,
    }
