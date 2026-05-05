"""Durable sink for result-log/state-pointer divergence records."""

from __future__ import annotations

import json
from pathlib import Path

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.state import CurrentPhase, HarnessState
from harness.shared.core.timestamp import kst_now_human, kst_now_iso


def _kst_timestamp() -> str:
    return kst_now_iso()


def record_state_update_recovery(
    logs_dir: str | Path,
    *,
    namespace: str,
    record_type: str,
    reason_code: str,
    orphan_result_ref: str,
    attempted_pointer_field: str,
) -> str:
    """Persist a recovery record when a result log exists but state pointer update failed."""

    path = reserve_log_path(logs_dir, namespace)
    payload = {
        "record_type": record_type,
        "status": "unresolved",
        "occurred_at": _kst_timestamp(),
        "reason_code": reason_code,
        "orphan_result_ref": orphan_result_ref,
        "attempted_pointer_field": attempted_pointer_field,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return log_ref_for_path(logs_dir, path)


def _resolve_recovery_path(task_root: str | Path, recovery_ref: str | Path) -> Path:
    path = Path(recovery_ref)
    if path.is_absolute():
        return path
    return Path(task_root) / path


def mark_state_update_recovery_resolved(
    task_root: str | Path,
    recovery_ref: str | Path,
    *,
    resolution: str,
    adopted_result_ref: str | None = None,
) -> None:
    """Mark a state-update recovery record resolved after explicit operator handling."""

    path = _resolve_recovery_path(task_root, recovery_ref)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "resolved"
    payload["resolved_at"] = _kst_timestamp()
    payload["resolution"] = resolution
    if adopted_result_ref is not None:
        payload["adopted_result_ref"] = adopted_result_ref
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def mark_orphan_adoption_recorded(task_root: str | Path, recovery_ref: str | Path, adopted_result_ref: str) -> None:
    """Resolve a recovery record after adoption was handled elsewhere."""

    mark_state_update_recovery_resolved(
        task_root,
        recovery_ref,
        resolution="orphan_result_adopted",
        adopted_result_ref=adopted_result_ref,
    )


def _state_with_adopted_result(state: HarnessState, pointer_field: str, adopted_result_ref: str) -> HarnessState:
    latest_verification_ref = state.latest_verification_ref
    latest_review_ref = state.latest_review_ref
    blocked_transition = state.blocked_transition
    blocked_reason_ref = state.blocked_reason_ref
    current_phase = state.current_phase

    if pointer_field == "latest_verification_ref":
        latest_verification_ref = adopted_result_ref
        if blocked_transition == "verify_state_update":
            blocked_transition = None
            blocked_reason_ref = None
            current_phase = CurrentPhase.VERIFICATION
    elif pointer_field == "latest_review_ref":
        latest_review_ref = adopted_result_ref
        if blocked_transition == "review_state_update":
            blocked_transition = None
            blocked_reason_ref = None
            current_phase = CurrentPhase.REVIEW
    else:
        raise ValueError(f"Unsupported state update recovery pointer field: {pointer_field}")

    return HarnessState(
        schema_version=state.schema_version,
        session_state=state.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=state.current_step_ref,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=latest_verification_ref,
        latest_review_ref=latest_review_ref,
        pending_approval_for=state.pending_approval_for,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters=state.counters,
        blocked_transition=blocked_transition,
        blocked_reason_ref=blocked_reason_ref,
        stop_condition_ref=state.stop_condition_ref,
        last_updated=kst_now_human(),
        approvals_granted=state.approvals_granted,
        adapter_meta=state.adapter_meta,
    )


def adopt_orphan_result_as_latest_ref(task_root: str | Path, recovery_ref: str | Path) -> str:
    """Adopt the recovery record's orphan result into state.json and mark the record resolved."""

    root = Path(task_root)
    path = _resolve_recovery_path(root, recovery_ref)
    payload = json.loads(path.read_text(encoding="utf-8"))
    orphan_result_ref = str(payload["orphan_result_ref"])
    pointer_field = str(payload["attempted_pointer_field"])
    state_path = root / "state.json"
    state = read_state(state_path)
    write_state(state_path, _state_with_adopted_result(state, pointer_field, orphan_result_ref))
    mark_orphan_adoption_recorded(root, recovery_ref, orphan_result_ref)
    return orphan_result_ref
