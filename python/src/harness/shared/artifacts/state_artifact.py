"""state.json artifact helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from harness.shared.artifacts.plan_artifact import (
    apply_plan_current_state_to_harness_state,
    plan_current_state_from_harness_state,
    read_plan_current_state,
    write_plan_current_state,
)
from harness.shared.contracts.results import ApplyResult, ApplyStatus
from harness.shared.contracts.state import (
    CurrentPhase,
    DeferredStateTransition,
    HarnessCounters,
    HarnessState,
    ReviewOutcome,
    SessionState,
    WorkflowMode,
)
from harness.shared.core.state_migration import CURRENT_SCHEMA_VERSION, migrate_state_file
from harness.shared.core.timestamp import kst_now_human


def _normalize_path(state_path: str | Path) -> Path:
    return Path(state_path)


def _kst_timestamp() -> str:
    return kst_now_human()


def _resolve_current_step_ref(
    previous_current_step_ref: str | None,
    next_phase: CurrentPhase,
    next_session_state: SessionState,
) -> str | None:
    if next_session_state == SessionState.DONE:
        return None
    if next_phase in {
        CurrentPhase.PRE_PLANNING,
        CurrentPhase.PLAN,
        CurrentPhase.VERIFICATION,
        CurrentPhase.REVIEW,
    }:
        return None
    return previous_current_step_ref


def _allows_current_step_ref(phase: CurrentPhase, session_state: SessionState) -> bool:
    return session_state != SessionState.DONE and phase in {CurrentPhase.STEP, CurrentPhase.IMPLEMENTATION}


def _state_to_payload(state: HarnessState) -> dict[str, Any]:
    payload = asdict(state)
    payload["session_state"] = state.session_state.value
    payload["workflow_mode"] = state.workflow_mode.value
    payload["current_phase"] = state.current_phase.value
    payload["review_outcome"] = state.review_outcome.value if state.review_outcome is not None else None
    return payload


def _write_state_json(path: Path, state: HarnessState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_state_to_payload(state), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _read_state_json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reconcile_state_from_plan(state_path: Path, state: HarnessState) -> HarnessState:
    plan_path = state_path.with_name("plan.md")
    if not plan_path.exists():
        return state

    plan_current = read_plan_current_state(plan_path)
    if plan_current is None:
        return state

    reconciled = apply_plan_current_state_to_harness_state(state, plan_current)
    return reconciled


def _write_plan_mirror_for_state(state_path: Path, state: HarnessState) -> None:
    plan_path = state_path.with_name("plan.md")
    if plan_path.exists():
        write_plan_current_state(plan_path, plan_current_state_from_harness_state(state))


def _plan_mirror_exists(state_path: Path) -> bool:
    return state_path.with_name("plan.md").exists()


def _load_enum(enum_cls: type, value: str | None) -> Any:
    if value is None:
        return None
    return enum_cls(value)


def _payload_to_state(payload: dict[str, Any]) -> HarnessState:
    counters_payload = payload.get("counters", {})
    counters = HarnessCounters(
        rework_count=int(counters_payload.get("rework_count", 0)),
        rewrite_count=int(counters_payload.get("rewrite_count", 0)),
        rollback_count=int(counters_payload.get("rollback_count", 0)),
    )
    approvals_payload = payload.get("approvals_granted", [])
    approvals_granted = [] if approvals_payload is None else [int(item) for item in approvals_payload]
    return HarnessState(
        schema_version=int(payload["schema_version"]),
        session_state=SessionState(payload["session_state"]),
        workflow_mode=WorkflowMode(payload["workflow_mode"]),
        current_phase=CurrentPhase(payload["current_phase"]),
        repo_profile_ref=payload.get("repo_profile_ref"),
        workspace_baseline_ref=payload.get("workspace_baseline_ref"),
        current_step_ref=payload.get("current_step_ref"),
        latest_checkpoint_ref=payload.get("latest_checkpoint_ref"),
        latest_verification_ref=payload.get("latest_verification_ref"),
        latest_review_ref=payload.get("latest_review_ref"),
        pending_approval_for=payload.get("pending_approval_for"),
        review_outcome=_load_enum(ReviewOutcome, payload.get("review_outcome")),
        closure_authorized=bool(payload.get("closure_authorized", False)),
        counters=counters,
        blocked_transition=payload.get("blocked_transition"),
        blocked_reason_ref=payload.get("blocked_reason_ref"),
        stop_condition_ref=payload.get("stop_condition_ref"),
        last_updated=str(payload["last_updated"]),
        approvals_granted=approvals_granted,
        adapter_meta=dict(payload.get("adapter_meta", {})),
    )


def read_state(state_path: str | Path) -> HarnessState:
    """Read workflow state, reconciling plan.md Current State when present.

    Auto-migrates or repairs state.json on first read so callers never see
    legacy tokens like ``"active"`` or ``"verification_entry"``. The migration
    is idempotent and writes a backup before rewriting (see
    :mod:`harness.shared.core.state_migration`). For PR5+ tasks, plan.md wins
    over state.json for fields present in Current State.
    """
    path = _normalize_path(state_path)
    migration = migrate_state_file(path)
    if migration.payload is None:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = migration.payload
    return _reconcile_state_from_plan(path, _payload_to_state(payload))


def reconcile_state_from_plan(state_path: str | Path) -> HarnessState:
    """Reconcile state.json mirror from plan.md Current State explicitly."""
    path = _normalize_path(state_path)
    state = read_state(path)
    if _state_to_payload(state) != _read_state_json_payload(path):
        _write_state_json(path, state)
    return state


def write_state(state_path: str | Path, state: HarnessState) -> None:
    """Write state.json and mirror it into plan.md Current State when present."""
    path = _normalize_path(state_path)
    has_plan_mirror = _plan_mirror_exists(path)
    _write_plan_mirror_for_state(path, state)
    try:
        _write_state_json(path, state)
    except OSError:
        if has_plan_mirror:
            return
        raise


def write_initial_state(state_path: str | Path, state: HarnessState) -> None:
    """Write the initial state during /wf-start."""
    write_state(state_path, state)


def apply_immediate_transition(state_path: str | Path, transition: DeferredStateTransition) -> None:
    """Apply an immediate transition without /wf-apply mediation."""
    state = read_state(state_path)
    approvals_granted = (
        transition.approvals_granted if transition.approvals_granted is not None else state.approvals_granted
    )
    updated = HarnessState(
        schema_version=state.schema_version,
        session_state=transition.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=transition.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=_resolve_current_step_ref(
            state.current_step_ref,
            transition.current_phase,
            transition.session_state,
        ),
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=transition.pending_approval_for,
        review_outcome=transition.review_outcome,
        closure_authorized=transition.closure_authorized,
        counters=transition.counters,
        blocked_transition=transition.blocked_transition,
        blocked_reason_ref=transition.blocked_reason_ref,
        stop_condition_ref=transition.stop_condition_ref,
        last_updated=_kst_timestamp(),
        approvals_granted=approvals_granted,
        adapter_meta=state.adapter_meta,
    )
    write_state(state_path, updated)


def apply_deferred_transition_with_apply_result(
    state_path: str | Path,
    transition: DeferredStateTransition,
    apply_result: ApplyResult,
) -> None:
    """Apply a deferred state transition after /wf-apply succeeds."""
    if apply_result.apply_status == ApplyStatus.BLOCKED:
        return

    state = read_state(state_path)
    approvals_granted = (
        transition.approvals_granted if transition.approvals_granted is not None else state.approvals_granted
    )
    current_step_ref = _resolve_current_step_ref(
        state.current_step_ref,
        transition.current_phase,
        transition.session_state,
    )
    if apply_result.current_step_ref_update_mode == "set" and _allows_current_step_ref(
        transition.current_phase,
        transition.session_state,
    ):
        current_step_ref = apply_result.resolved_current_step_ref
    elif apply_result.current_step_ref_update_mode == "clear":
        current_step_ref = None

    updated = HarnessState(
        schema_version=state.schema_version,
        session_state=transition.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=transition.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=current_step_ref,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=transition.pending_approval_for,
        review_outcome=transition.review_outcome,
        closure_authorized=transition.closure_authorized,
        counters=transition.counters,
        blocked_transition=transition.blocked_transition,
        blocked_reason_ref=transition.blocked_reason_ref,
        stop_condition_ref=transition.stop_condition_ref,
        last_updated=_kst_timestamp(),
        approvals_granted=approvals_granted,
        adapter_meta=state.adapter_meta,
    )
    write_state(state_path, updated)
