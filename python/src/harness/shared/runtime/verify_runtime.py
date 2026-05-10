"""Deterministic persistence helper used by /wf-verify."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.artifacts.state_update_sink import record_state_update_recovery
from harness.shared.contracts.results import JudgementCode, NoteSignal, NoteTargetHint, VerificationItem, VerificationResult
from harness.shared.contracts.state import CurrentPhase, HarnessState, SessionState
from harness.shared.core.diff_helper import TaskScopedDiffError, build_task_scoped_diff, compute_task_diff_fingerprint
from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.json_util import to_jsonable
from harness.shared.core.phase_spec_loader import PhaseSpec, PhaseSpecLoadError, load_phase_spec, resolve_workspace_root
from harness.shared.core.state_migration import StateMigrationError
from harness.shared.core.task_paths import get_task_paths
from harness.shared.core.timestamp import kst_now_human, kst_now_iso


FAILURE_JUDGEMENTS = {
    JudgementCode.REWORK,
    JudgementCode.REWRITE_STEP,
    JudgementCode.REWRITE_PLAN,
    JudgementCode.ROLLBACK,
    JudgementCode.HOLD,
}

VALID_ITEM_RESULTS = {"PASS", "FAIL", "NOT_RUN"}
VALID_ITEM_TYPES = {"cleanup", "gate", "extra"}


@dataclass(slots=True)
class VerifyRuntimeInput:
    """Normalized verify result persistence input."""

    task_root: Path
    verification_result: VerificationResult
    workspace_root: Path | None = None
    caller_summary_hint: str | None = None
    candidate_basis_refs: list[str] | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root)
        if isinstance(self.verification_result, dict):
            self.verification_result = _normalize_verification_result(self.verification_result)
        if self.candidate_basis_refs is None:
            self.candidate_basis_refs = []


def persist_verify_runtime(input_data: VerifyRuntimeInput) -> dict[str, object]:
    """Persist verification result/log and update state.latest_verification_ref."""

    task_paths = get_task_paths(input_data.task_root)
    try:
        workspace_root = resolve_workspace_root(input_data.workspace_root)
    except PhaseSpecLoadError:
        return _blocked_verify_output("VERIFY_WORKSPACE_ROOT_MISSING", "`/wf-verify` requires an explicit workspace_root.")

    if not task_paths.state_path.exists():
        return _blocked_verify_output("STATE_ARTIFACT_MISSING", "`/wf-verify` requires an initialized state.json artifact.")
    try:
        state = read_state(task_paths.state_path)
    except (StateMigrationError, KeyError, TypeError, ValueError):
        return _blocked_verify_output(
            "STATE_ARTIFACT_INVALID",
            "`/wf-verify` requires a valid runbook state.json artifact.",
        )

    guard_decision = run_guard(GuardInput(action="wf-verify", task_root=task_paths.task_root, state=state))
    if not guard_decision.allow:
        return _blocked_verify_output(guard_decision.reason_code or "VERIFY_GUARD_BLOCKED", guard_decision.message_summary)

    try:
        phase_spec = load_phase_spec(CurrentPhase.VERIFICATION.value, workspace_root=workspace_root)
    except PhaseSpecLoadError:
        return _blocked_verify_output("VERIFY_PHASE_SPEC_UNAVAILABLE", "Verification phase spec could not be loaded.")

    result = input_data.verification_result
    invalid_reason = _validate_verification_result(result, phase_spec)
    if invalid_reason is not None:
        return _blocked_verify_output(invalid_reason)

    try:
        diff = build_task_scoped_diff(task_paths.task_root, state.workspace_baseline_ref or "")
    except TaskScopedDiffError:
        return _blocked_verify_output("VERIFY_DIFF_UNAVAILABLE", "Task-scoped diff could not be built for verification.")
    result.verified_task_diff_fingerprint = compute_task_diff_fingerprint(diff)

    verification_path = reserve_log_path(task_paths.logs_dir, "verification")
    verification_ref = log_ref_for_path(task_paths.logs_dir, verification_path)
    result.verification_ref = verification_ref
    payload = to_jsonable(result)
    payload["persisted_at"] = _kst_timestamp()
    verification_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    try:
        write_state(task_paths.state_path, _with_latest_verification_ref(state, verification_ref))
    except OSError:
        recovery_ref = None
        recovery_record_persisted = True
        try:
            recovery_ref = record_state_update_recovery(
                task_paths.logs_dir,
                namespace="verify-recovery",
                record_type="verify_state_update_recovery",
                reason_code="VERIFY_STATE_UPDATE_FAILED",
                orphan_result_ref=verification_ref,
                attempted_pointer_field="latest_verification_ref",
            )
        except OSError:
            recovery_record_persisted = False
        blocked_state_persisted = True
        try:
            write_state(task_paths.state_path, _with_verify_state_update_blocked_state(state, verification_ref))
        except OSError:
            blocked_state_persisted = False
        blocked = _blocked_verify_output(
            "VERIFY_STATE_UPDATE_FAILED",
            "Verification result log was written, but latest_verification_ref could not be updated.",
        )
        blocked["verification_ref"] = verification_ref
        blocked["verified_task_diff_fingerprint"] = result.verified_task_diff_fingerprint
        blocked["recovery_ref"] = recovery_ref
        blocked["recovery_record_persisted"] = recovery_record_persisted
        blocked["blocked_state_persisted"] = blocked_state_persisted
        return blocked

    return {
        "verification_ref": verification_ref,
        "latest_verification_ref": verification_ref,
        "verified_task_diff_fingerprint": result.verified_task_diff_fingerprint,
        "reason_code": None,
    }


def _kst_timestamp() -> str:
    return kst_now_iso()


def _blocked_verify_output(reason_code: str, message_summary: str | None = None) -> dict[str, object]:
    return {
        "verification_ref": None,
        "latest_verification_ref": None,
        "verified_task_diff_fingerprint": None,
        "reason_code": reason_code,
        "message_summary": message_summary or f"Verification blocked: {reason_code}",
    }


def _validate_verification_result(result: VerificationResult, phase_spec: PhaseSpec) -> str | None:
    if not result.summary.strip():
        return "VERIFY_RESULT_CONTRACT_INVALID"
    if result.judgement_code.value not in phase_spec.allowed_judgements:
        return "VERIFY_JUDGEMENT_INVALID"
    if result.judgement_code == JudgementCode.GO_WITH_NOTE and not result.note_signals:
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if result.judgement_code != JudgementCode.GO_WITH_NOTE and result.note_signals:
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if any(note.note_target_hint != NoteTargetHint.PLAN for note in result.note_signals):
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if result.judgement_code in FAILURE_JUDGEMENTS and (
        not result.primary_cause_code or not result.reason_fingerprint
    ):
        return "VERIFY_REASON_REQUIRED"
    if not result.verification_items:
        return "VERIFY_RESULT_CONTRACT_INVALID"
    for item in result.verification_items:
        if (
            not item.item_key.strip()
            or item.item_type not in VALID_ITEM_TYPES
            or not item.label.strip()
            or not item.method.strip()
            or item.result not in VALID_ITEM_RESULTS
            or not item.summary.strip()
        ):
            return "VERIFY_ITEM_INVALID"
    return None


def _with_latest_verification_ref(state: HarnessState, verification_ref: str) -> HarnessState:
    blocked_transition = None if state.blocked_transition == "verify_state_update" else state.blocked_transition
    blocked_reason_ref = None if state.blocked_transition == "verify_state_update" else state.blocked_reason_ref
    return HarnessState(
        schema_version=state.schema_version,
        session_state=state.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=state.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=state.current_step_ref,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=verification_ref,
        latest_review_ref=state.latest_review_ref,
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


def _with_verify_state_update_blocked_state(state: HarnessState, verification_ref: str) -> HarnessState:
    return HarnessState(
        schema_version=state.schema_version,
        session_state=SessionState.PAUSED,
        workflow_mode=state.workflow_mode,
        current_phase=CurrentPhase.VERIFICATION,
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
        blocked_transition="verify_state_update",
        blocked_reason_ref=verification_ref,
        stop_condition_ref=state.stop_condition_ref,
        last_updated=kst_now_human(),
        approvals_granted=state.approvals_granted,
        adapter_meta=state.adapter_meta,
    )


def _normalize_verification_result(payload: dict[str, Any]) -> VerificationResult:
    return VerificationResult(
        verification_ref=str(payload.get("verification_ref", "")),
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
                basis_refs=[str(ref) for ref in item.get("basis_refs", [])],
            )
            for item in payload.get("verification_items", [])
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
        verified_task_diff_fingerprint=payload.get("verified_task_diff_fingerprint"),
        stop_condition_code=payload.get("stop_condition_code"),
        primary_cause_code=payload.get("primary_cause_code"),
        reason_fingerprint=payload.get("reason_fingerprint"),
    )
