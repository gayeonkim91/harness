"""Deterministic persistence helper used by /wf-verify."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.artifacts.state_update_sink import record_state_update_recovery
from harness.shared.contracts.results import (
    JudgementCode,
    NoteSignal,
    NoteTargetHint,
    VerificationItem,
    VerificationLintWarningCode,
    VerificationResult,
    normalize_verification_lint_warnings,
)
from harness.shared.contracts.state import CurrentPhase, HarnessState, SessionState
from harness.shared.core.diff_helper import TaskScopedDiffError, build_task_scoped_diff, compute_task_diff_fingerprint
from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.json_util import to_jsonable
from harness.shared.core.phase_spec_loader import PhaseSpec, PhaseSpecLoadError, load_phase_spec, resolve_workspace_root
from harness.shared.core.state_migration import StateMigrationError
from harness.shared.core.task_paths import get_task_paths
from harness.shared.core.timestamp import kst_now_human, kst_now_iso
from harness.shared.core.verification_gate_selector import is_autofix_command
from harness.shared.integrations.test_report_skill_bridge import uses_test_report_verification_assist


FAILURE_JUDGEMENTS = {
    JudgementCode.REWORK,
    JudgementCode.REWRITE_STEP,
    JudgementCode.REWRITE_PLAN,
    JudgementCode.ROLLBACK,
    JudgementCode.HOLD,
}

VALID_ITEM_RESULTS = {"PASS", "FAIL", "NOT_RUN"}
VALID_ITEM_TYPES = {"cleanup", "gate", "extra"}

_PYTHON_TRACEBACK_PATTERN = re.compile(r"Traceback \(most recent call last\):")
_JAVA_CAUSED_BY_PATTERN = re.compile(r"(?m)^Caused by:\s+[\w.$]+")
_STACK_FRAME_PATTERN = re.compile(r"(?m)^\s+at\s+.+\(.+:\d+(?::\d+)?\)")
_TEST_REPORT_CANDIDATE_PATTERN = re.compile(
    r"\b(?:test|pytest|gradlew?|junit|lint|build|checkstyle|mvnw?|maven|surefire|failsafe|"
    r"ruff|mypy|pyright|tsc|eslint|jest|vitest|typecheck|type-check|static-analysis)\b|--noemit\b"
)
EnumValue = TypeVar("EnumValue", bound=Enum)


@dataclass(slots=True)
class VerifyRuntimeInput:
    """Normalized verify result persistence input.

    candidate_basis_refs is accepted for CLI compatibility and exploration hints,
    but lint suppression only trusts persisted VerificationResult basis refs.
    """

    task_root: Path
    verification_result: VerificationResult | dict[str, Any]
    workspace_root: Path | None = None
    caller_summary_hint: str | None = None
    candidate_basis_refs: list[str] | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root)
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

    try:
        result = _coerce_verification_result(input_data.verification_result)
    except ValueError as exc:
        return _blocked_verify_output("VERIFY_RESULT_CONTRACT_INVALID", str(exc))

    invalid_reason = _validate_verification_result(result, phase_spec)
    if invalid_reason is not None:
        return _blocked_verify_output(invalid_reason)
    lint_block_reason = _validate_verification_lint(task_paths.task_root, result)
    if lint_block_reason is not None:
        message_summary = "Verification result must summarize failures with report refs instead of raw console stack traces."
        if lint_block_reason == "VERIFY_VERIFICATION_DOC_UNREADABLE":
            message_summary = "verification.md exists but could not be read for lint validation."
        return _blocked_verify_output(
            lint_block_reason,
            message_summary,
        )
    result.lint_warnings = normalize_verification_lint_warnings(
        [
            *result.lint_warnings,
            *_verification_lint_warnings(result),
        ]
    )

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
        blocked["lint_warnings"] = _lint_warning_values(result.lint_warnings)
        blocked["recovery_ref"] = recovery_ref
        blocked["recovery_record_persisted"] = recovery_record_persisted
        blocked["blocked_state_persisted"] = blocked_state_persisted
        return blocked

    return {
        "verification_ref": verification_ref,
        "latest_verification_ref": verification_ref,
        "verified_task_diff_fingerprint": result.verified_task_diff_fingerprint,
        "lint_warnings": _lint_warning_values(result.lint_warnings),
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
    if not _has_text(result.summary):
        return "VERIFY_RESULT_CONTRACT_INVALID"
    if result.judgement_code.value not in phase_spec.allowed_judgements:
        return "VERIFY_JUDGEMENT_INVALID"
    if result.judgement_code == JudgementCode.GO_WITH_NOTE and not result.note_signals:
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if result.judgement_code != JudgementCode.GO_WITH_NOTE and result.note_signals:
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if any(note.note_target_hint != NoteTargetHint.PLAN for note in result.note_signals):
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if any(not _has_text(note.note_text) for note in result.note_signals):
        return "VERIFY_NOTE_SIGNALS_INVALID"
    if result.judgement_code in FAILURE_JUDGEMENTS and (
        not _has_text(result.primary_cause_code) or not _has_text(result.reason_fingerprint)
    ):
        return "VERIFY_REASON_REQUIRED"
    if not result.verification_items:
        return "VERIFY_RESULT_CONTRACT_INVALID"
    for item in result.verification_items:
        if (
            not _has_text(item.item_key)
            or item.item_type not in VALID_ITEM_TYPES
            or not _has_text(item.label)
            or not _has_text(item.method)
            or item.result not in VALID_ITEM_RESULTS
            or not _has_text(item.summary)
        ):
            return "VERIFY_ITEM_INVALID"
    return None


def _lint_warning_values(warnings: list[VerificationLintWarningCode]) -> list[str]:
    return [warning.value for warning in warnings]


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _contains_console_stack_trace(text: str) -> bool:
    if _PYTHON_TRACEBACK_PATTERN.search(text):
        return True
    stack_frame_count = len(_STACK_FRAME_PATTERN.findall(text))
    if stack_frame_count >= 2:
        return True
    return bool(_JAVA_CAUSED_BY_PATTERN.search(text) and stack_frame_count >= 1)


def _verification_text_fields(result: VerificationResult) -> list[str]:
    fields = [result.summary]
    fields.extend(item.summary for item in result.verification_items)
    fields.extend(item.method for item in result.verification_items)
    fields.extend(note.note_text for note in result.note_signals)
    return fields


def _validate_verification_lint(task_root: Path, result: VerificationResult) -> str | None:
    for value in _verification_text_fields(result):
        if _contains_console_stack_trace(value):
            return "VERIFY_CONSOLE_STACK_TRACE_BLOCKED"

    verification_doc = task_root / "verification.md"
    if verification_doc.exists() and verification_doc.is_file():
        try:
            content = verification_doc.read_text(encoding="utf-8")
        except OSError:
            return "VERIFY_VERIFICATION_DOC_UNREADABLE"
        if _contains_console_stack_trace(content):
            return "VERIFY_CONSOLE_STACK_TRACE_BLOCKED"
    return None


def _item_looks_like_test_report_candidate(item: VerificationItem) -> bool:
    if item.item_type not in {"gate", "extra"}:
        return False
    text = " ".join([item.item_key, item.item_type, item.label, item.method]).lower()
    return bool(_TEST_REPORT_CANDIDATE_PATTERN.search(text))


def _verification_lint_warnings(result: VerificationResult) -> list[VerificationLintWarningCode]:
    warnings: list[VerificationLintWarningCode] = []
    for item in result.verification_items:
        if is_autofix_command(item.method):
            warnings.append(VerificationLintWarningCode.AUTOFIX_COMMAND_RECORDED)
        item_basis_refs = [*result.basis_refs, *item.basis_refs]
        if _item_looks_like_test_report_candidate(item) and not uses_test_report_verification_assist(item_basis_refs):
            warnings.append(VerificationLintWarningCode.TEST_REPORT_SKILL_BYPASSED)
    return normalize_verification_lint_warnings(warnings)


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


def _required_dict_string(payload: dict[str, Any], key: str, field_name: str) -> str:
    """Read a required string from CLI/dict input; content validation happens later."""

    if key not in payload:
        raise ValueError(f"{field_name} is required.")
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value


def _optional_dict_string(payload: dict[str, Any], key: str, field_name: str) -> str | None:
    """Read an optional string from CLI/dict input; explicit null means unset."""

    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when present.")
    return value


def _dict_string_with_default(payload: dict[str, Any], key: str, field_name: str, default: str) -> str:
    """Read an optional string with a missing-key default; explicit null is invalid."""

    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when present.")
    return value


def _optional_dict_list(payload: dict[str, Any], key: str, field_name: str) -> list[Any]:
    """Read an optional list from CLI/dict input; explicit null is invalid."""

    if key not in payload:
        return []
    value = payload[key]
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list when present.")
    return value


def _optional_dict_string_list(payload: dict[str, Any], key: str, field_name: str) -> list[str]:
    """Read an optional string list from CLI/dict input; elements are not coerced."""

    values = _optional_dict_list(payload, key, field_name)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise ValueError(f"{field_name}[{index}] must be a string.")
        result.append(value)
    return result


def _required_dict_enum(enum_type: type[EnumValue], value: Any, field_name: str) -> EnumValue:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}.") from exc


def _normalize_verification_item(payload: dict[str, Any], index: int) -> VerificationItem:
    field_prefix = f"verification_result.verification_items[{index}]"
    if not isinstance(payload, dict):
        raise ValueError(f"{field_prefix} must be a mapping.")
    return VerificationItem(
        item_key=_required_dict_string(payload, "item_key", f"{field_prefix}.item_key"),
        item_type=_required_dict_string(payload, "item_type", f"{field_prefix}.item_type"),
        label=_required_dict_string(payload, "label", f"{field_prefix}.label"),
        method=_required_dict_string(payload, "method", f"{field_prefix}.method"),
        result=_required_dict_string(payload, "result", f"{field_prefix}.result"),
        summary=_required_dict_string(payload, "summary", f"{field_prefix}.summary"),
        basis_refs=_optional_dict_string_list(payload, "basis_refs", f"{field_prefix}.basis_refs"),
    )


def _normalize_note_signal(payload: dict[str, Any], index: int) -> NoteSignal:
    field_prefix = f"verification_result.note_signals[{index}]"
    if not isinstance(payload, dict):
        raise ValueError(f"{field_prefix} must be a mapping.")
    note_target_hint = _required_dict_string(payload, "note_target_hint", f"{field_prefix}.note_target_hint")
    return NoteSignal(
        note_text=_required_dict_string(payload, "note_text", f"{field_prefix}.note_text"),
        note_target_hint=_required_dict_enum(NoteTargetHint, note_target_hint, f"{field_prefix}.note_target_hint"),
        note_basis_refs=_optional_dict_string_list(payload, "note_basis_refs", f"{field_prefix}.note_basis_refs"),
    )


def _coerce_verification_result(value: VerificationResult | dict[str, Any]) -> VerificationResult:
    if isinstance(value, VerificationResult):
        return value
    if isinstance(value, dict):
        return _normalize_verification_result(value)
    raise ValueError("verification_result must be a mapping.")


def _normalize_verification_result(payload: dict[str, Any]) -> VerificationResult:
    judgement_code = _required_dict_string(payload, "judgement_code", "verification_result.judgement_code")
    return VerificationResult(
        verification_ref=_dict_string_with_default(
            payload,
            "verification_ref",
            "verification_result.verification_ref",
            "",
        ),
        judgement_code=_required_dict_enum(JudgementCode, judgement_code, "verification_result.judgement_code"),
        summary=_required_dict_string(payload, "summary", "verification_result.summary"),
        verification_items=[
            _normalize_verification_item(item, index)
            for index, item in enumerate(
                _optional_dict_list(
                    payload,
                    "verification_items",
                    "verification_result.verification_items",
                )
            )
        ],
        basis_refs=_optional_dict_string_list(payload, "basis_refs", "verification_result.basis_refs"),
        note_signals=[
            _normalize_note_signal(note, index)
            for index, note in enumerate(
                _optional_dict_list(
                    payload,
                    "note_signals",
                    "verification_result.note_signals",
                )
            )
        ],
        verified_task_diff_fingerprint=_optional_dict_string(
            payload,
            "verified_task_diff_fingerprint",
            "verification_result.verified_task_diff_fingerprint",
        ),
        stop_condition_code=_optional_dict_string(
            payload,
            "stop_condition_code",
            "verification_result.stop_condition_code",
        ),
        primary_cause_code=_optional_dict_string(
            payload,
            "primary_cause_code",
            "verification_result.primary_cause_code",
        ),
        reason_fingerprint=_optional_dict_string(
            payload,
            "reason_fingerprint",
            "verification_result.reason_fingerprint",
        ),
        lint_warnings=normalize_verification_lint_warnings(
            _optional_dict_string_list(payload, "lint_warnings", "verification_result.lint_warnings")
        ),
    )
