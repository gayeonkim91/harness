"""Deterministic persistence helper used by /wf-review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.artifacts.state_update_sink import record_state_update_recovery
from harness.shared.contracts.results import JudgementCode, ReviewResult
from harness.shared.contracts.state import CurrentPhase, HarnessState, SessionState
from harness.shared.core.diff_helper import TaskScopedDiffError, build_task_scoped_diff, compute_task_diff_fingerprint
from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.json_util import to_jsonable
from harness.shared.core.phase_spec_loader import PhaseSpec, PhaseSpecLoadError, load_phase_spec, resolve_workspace_root
from harness.shared.core.state_migration import StateMigrationError
from harness.shared.core.task_paths import TaskPaths
from harness.shared.core.task_paths import get_task_paths
from harness.shared.core.timestamp import kst_now_human, kst_now_iso


FAILURE_REVIEW_JUDGEMENTS = {
    JudgementCode.REWORK,
    JudgementCode.REWRITE_PLAN,
    JudgementCode.HOLD,
}


@dataclass(slots=True)
class ReviewRuntimeInput:
    """Normalized review result persistence input."""

    task_root: Path
    review_result: ReviewResult
    workspace_root: Path | None = None
    caller_summary_hint: str | None = None
    candidate_basis_refs: list[str] | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root)
        if isinstance(self.review_result, dict):
            self.review_result = _normalize_review_result(self.review_result)
        if self.candidate_basis_refs is None:
            self.candidate_basis_refs = []


def persist_review_runtime(input_data: ReviewRuntimeInput) -> dict[str, object]:
    """Persist review result/log and update state.latest_review_ref."""

    task_paths = get_task_paths(input_data.task_root)
    try:
        workspace_root = resolve_workspace_root(input_data.workspace_root)
    except PhaseSpecLoadError:
        return _blocked_review_output("REVIEW_WORKSPACE_ROOT_MISSING", "`/wf-review` requires an explicit workspace_root.")

    if not task_paths.state_path.exists():
        return _blocked_review_output("STATE_ARTIFACT_MISSING", "`/wf-review` requires an initialized state.json artifact.")
    try:
        state = read_state(task_paths.state_path)
    except (StateMigrationError, KeyError, TypeError, ValueError):
        return _blocked_review_output(
            "STATE_ARTIFACT_INVALID",
            "`/wf-review` requires a valid runbook state.json artifact.",
        )

    guard_decision = run_guard(GuardInput(action="wf-review", task_root=task_paths.task_root, state=state))
    if not guard_decision.allow:
        return _blocked_review_output(guard_decision.reason_code or "REVIEW_GUARD_BLOCKED", guard_decision.message_summary)

    try:
        phase_spec = load_phase_spec(CurrentPhase.REVIEW.value, workspace_root=workspace_root)
    except PhaseSpecLoadError:
        return _blocked_review_output("REVIEW_PHASE_SPEC_UNAVAILABLE", "Review phase spec could not be loaded.")

    try:
        verification_payload = _read_latest_verification(task_paths.task_root, state.latest_verification_ref or "")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _blocked_review_output("REVIEW_VERIFICATION_REF_UNREADABLE", "Latest verification result could not be read.")
    try:
        current_diff = build_task_scoped_diff(task_paths.task_root, state.workspace_baseline_ref or "")
    except TaskScopedDiffError:
        return _blocked_review_output("REVIEW_DIFF_UNAVAILABLE", "Task-scoped diff could not be built for review.")

    current_fingerprint = compute_task_diff_fingerprint(current_diff)
    if verification_payload["verified_task_diff_fingerprint"] != current_fingerprint:
        return _blocked_review_output("REVIEW_VERIFICATION_STALE", "Current task diff no longer matches latest verification.")

    result = input_data.review_result
    invalid_reason = _validate_review_result(result, phase_spec)
    if invalid_reason is not None:
        failure_ref = _record_review_failure(task_paths, state, invalid_reason, result)
        blocked = _blocked_review_output(invalid_reason)
        blocked["review_failure_ref"] = failure_ref
        return blocked

    review_path = reserve_log_path(task_paths.logs_dir, "review")
    review_ref = log_ref_for_path(task_paths.logs_dir, review_path)
    result.review_ref = review_ref
    result.verified_task_diff_fingerprint = current_fingerprint
    payload = to_jsonable(result)
    payload["persisted_at"] = _kst_timestamp()
    review_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    try:
        write_state(task_paths.state_path, _with_latest_review_ref(state, review_ref))
    except OSError:
        recovery_ref = None
        recovery_record_persisted = True
        try:
            recovery_ref = record_state_update_recovery(
                task_paths.logs_dir,
                namespace="review-recovery",
                record_type="review_state_update_recovery",
                reason_code="REVIEW_STATE_UPDATE_FAILED",
                orphan_result_ref=review_ref,
                attempted_pointer_field="latest_review_ref",
            )
        except OSError:
            recovery_record_persisted = False
        blocked_state_persisted = True
        try:
            write_state(task_paths.state_path, _with_review_state_update_blocked_state(state, review_ref))
        except OSError:
            blocked_state_persisted = False
        blocked = _blocked_review_output(
            "REVIEW_STATE_UPDATE_FAILED",
            "Review result log was written, but latest_review_ref could not be updated.",
        )
        blocked["review_ref"] = review_ref
        blocked["verified_task_diff_fingerprint"] = current_fingerprint
        blocked["recovery_ref"] = recovery_ref
        blocked["recovery_record_persisted"] = recovery_record_persisted
        blocked["blocked_state_persisted"] = blocked_state_persisted
        return blocked

    return {
        "review_ref": review_ref,
        "latest_review_ref": review_ref,
        "verified_task_diff_fingerprint": current_fingerprint,
        "reason_code": None,
    }


def _kst_timestamp() -> str:
    return kst_now_iso()


def _blocked_review_output(reason_code: str, message_summary: str | None = None) -> dict[str, object]:
    return {
        "review_ref": None,
        "latest_review_ref": None,
        "verified_task_diff_fingerprint": None,
        "reason_code": reason_code,
        "message_summary": message_summary or f"Review blocked: {reason_code}",
    }


def _read_latest_verification(task_root: Path, verification_ref: str) -> dict[str, Any]:
    path = Path(verification_ref)
    if not path.is_absolute():
        path = task_root / path
    payload = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = payload.get("verified_task_diff_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ValueError("verified_task_diff_fingerprint is required.")
    return {"verified_task_diff_fingerprint": fingerprint}


def _validate_review_result(result: ReviewResult, phase_spec: PhaseSpec) -> str | None:
    if not result.summary.strip():
        return "REVIEW_RESULT_CONTRACT_INVALID"
    if result.judgement_code.value not in phase_spec.allowed_judgements:
        return "REVIEW_JUDGEMENT_INVALID"
    if result.out_of_scope_change and result.judgement_code in {JudgementCode.DONE, JudgementCode.DONE_WITH_NOTE}:
        return "REVIEW_OUT_OF_SCOPE_INVALID"
    if result.judgement_code == JudgementCode.DONE_WITH_NOTE and not result.carry_forward_notes:
        return "REVIEW_CARRY_FORWARD_NOTES_INVALID"
    if result.judgement_code in FAILURE_REVIEW_JUDGEMENTS and not result.key_issues:
        return "REVIEW_KEY_ISSUES_REQUIRED"
    if result.judgement_code in FAILURE_REVIEW_JUDGEMENTS and (
        not result.primary_cause_code or not result.reason_fingerprint
    ):
        return "REVIEW_REASON_REQUIRED"
    return None


def _record_review_failure(
    task_paths: TaskPaths,
    state: HarnessState,
    reason_code: str,
    result: ReviewResult,
) -> str:
    failure_path = reserve_log_path(task_paths.logs_dir, "review-failures")
    failure_ref = log_ref_for_path(task_paths.logs_dir, failure_path)
    payload = {
        "record_type": "review_failure",
        "status": "blocked",
        "occurred_at": _kst_timestamp(),
        "reason_code": reason_code,
        "review_output": to_jsonable(result),
    }
    failure_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    write_state(task_paths.state_path, _with_review_blocked_state(state, failure_ref))
    return failure_ref


def _with_latest_review_ref(state: HarnessState, review_ref: str) -> HarnessState:
    clear_block = state.blocked_transition in {"review_execution", "review_state_update"}
    blocked_transition = None if clear_block else state.blocked_transition
    blocked_reason_ref = None if clear_block else state.blocked_reason_ref
    return HarnessState(
        schema_version=state.schema_version,
        session_state=state.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=state.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=state.current_step_ref,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=review_ref,
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


def _with_review_blocked_state(state: HarnessState, blocked_reason_ref: str) -> HarnessState:
    return HarnessState(
        schema_version=state.schema_version,
        session_state=SessionState.PAUSED,
        workflow_mode=state.workflow_mode,
        current_phase=CurrentPhase.REVIEW,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=None,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=None,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters=state.counters,
        blocked_transition="review_execution",
        blocked_reason_ref=blocked_reason_ref,
        stop_condition_ref=state.stop_condition_ref,
        last_updated=kst_now_human(),
        approvals_granted=state.approvals_granted,
        adapter_meta=state.adapter_meta,
    )


def _with_review_state_update_blocked_state(state: HarnessState, review_ref: str) -> HarnessState:
    return HarnessState(
        schema_version=state.schema_version,
        session_state=SessionState.PAUSED,
        workflow_mode=state.workflow_mode,
        current_phase=CurrentPhase.REVIEW,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=None,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=None,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters=state.counters,
        blocked_transition="review_state_update",
        blocked_reason_ref=review_ref,
        stop_condition_ref=state.stop_condition_ref,
        last_updated=kst_now_human(),
        approvals_granted=state.approvals_granted,
        adapter_meta=state.adapter_meta,
    )


def _normalize_review_result(payload: dict[str, Any]) -> ReviewResult:
    return ReviewResult(
        review_ref=str(payload.get("review_ref", "")),
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
