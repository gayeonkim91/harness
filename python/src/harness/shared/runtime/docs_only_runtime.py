"""Deterministic helper for document-only workflow state transitions."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.contracts.approval import ApprovalPoint
from harness.shared.contracts.docs_only import DocsOnlyEvent, DocsOnlyStage, DocsOnlyState
from harness.shared.contracts.workflow import WorkflowKind
from harness.shared.core.task_paths import get_task_paths
from harness.shared.core.timestamp import kst_now_human, kst_now_iso


DOCS_ONLY_SCHEMA_VERSION = 1

RUNBOOK_APPROVAL_EVENTS = {"GO", "GO_WITH_NOTE", "DONE", "DONE_WITH_NOTE"}
RUNBOOK_APPROVAL_POINTS = {point.value for point in ApprovalPoint}
TRANSITIONS = {
    DocsOnlyEvent.PRESENT_PROPOSAL: (DocsOnlyStage.DISCUSSION, DocsOnlyStage.PROPOSAL_VISUALIZED),
    DocsOnlyEvent.ACCEPT_PROPOSAL: (DocsOnlyStage.PROPOSAL_VISUALIZED, DocsOnlyStage.PROPOSAL_ACCEPTED),
    DocsOnlyEvent.PRESENT_DIFF: (DocsOnlyStage.PROPOSAL_ACCEPTED, DocsOnlyStage.DIFF_PRESENTED),
    DocsOnlyEvent.APPLY: (DocsOnlyStage.DIFF_PRESENTED, DocsOnlyStage.APPLIED),
}


class DocsOnlyRunbookApprovalError(ValueError):
    """Raised when runbook approval state leaks into docs-only state."""


@dataclass(slots=True)
class DocsOnlyRuntimeInput:
    """Structured input for the document-only runtime helper."""

    task_root: Path
    event: DocsOnlyEvent | str
    workflow_kind: WorkflowKind | str | None = None
    workflow_kind_resolved: bool = False
    user_request: str = ""
    target_doc_refs: list[str] | None = None
    summary: str = ""
    artifact_ref: str | None = None
    evidence_refs: list[str] | None = None
    adapter_meta: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        self.event = _coerce_event(self.event)
        self.workflow_kind = _coerce_workflow_kind(self.workflow_kind)
        self.target_doc_refs = [str(item) for item in (self.target_doc_refs or [])]
        self.evidence_refs = [str(item) for item in (self.evidence_refs or [])]
        self.adapter_meta = dict(self.adapter_meta or {})


def execute_docs_only_runtime(input_data: DocsOnlyRuntimeInput) -> dict[str, object]:
    """Create or advance a docs-only task without runbook artifacts."""

    if _is_runbook_approval_event(input_data.event):
        return _blocked_output("DOCS_ONLY_RUNBOOK_APPROVAL_BLOCKED")
    if not isinstance(input_data.event, DocsOnlyEvent):
        return _blocked_output("DOCS_ONLY_EVENT_INVALID")
    if input_data.event == DocsOnlyEvent.START:
        return _start_docs_only(input_data)
    return _advance_docs_only(input_data)


def _start_docs_only(input_data: DocsOnlyRuntimeInput) -> dict[str, object]:
    task_paths = get_task_paths(input_data.task_root)
    if not input_data.workflow_kind_resolved:
        return _blocked_output("DOCS_ONLY_KIND_UNRESOLVED")
    if input_data.workflow_kind != WorkflowKind.DOCS_ONLY:
        return _blocked_output("DOCS_ONLY_KIND_INVALID")
    if not input_data.user_request.strip():
        return _blocked_output("DOCS_ONLY_REQUEST_MISSING")
    if task_paths.plan_path.exists() or task_paths.steps_path.exists():
        return _blocked_output("DOCS_ONLY_RUNBOOK_ARTIFACT_PRESENT")
    if task_paths.state_path.exists():
        return _blocked_output("DOCS_ONLY_ALREADY_INITIALIZED")

    event_path = None
    try:
        task_paths.task_root.mkdir(parents=True, exist_ok=True)
        event_ref, event_path, event_payload = _build_event_log(
            task_paths.logs_dir,
            event=DocsOnlyEvent.START,
            previous_stage=None,
            next_stage=DocsOnlyStage.DISCUSSION,
            summary=input_data.summary.strip() or input_data.user_request,
            artifact_ref=input_data.artifact_ref,
            evidence_refs=input_data.evidence_refs or [],
        )
        state = DocsOnlyState(
            schema_version=DOCS_ONLY_SCHEMA_VERSION,
            workflow_kind=WorkflowKind.DOCS_ONLY,
            docs_state=DocsOnlyStage.DISCUSSION,
            user_request=input_data.user_request.strip(),
            target_doc_refs=list(input_data.target_doc_refs or []),
            proposal_ref=None,
            diff_ref=None,
            applied_ref=None,
            last_event_ref=event_ref,
            event_history_refs=[event_ref],
            last_updated=kst_now_human(),
            adapter_meta=dict(input_data.adapter_meta or {}),
        )
        _write_event_log_payload(event_path, event_payload)
        _write_docs_state(task_paths.state_path, state)
    except OSError:
        if event_path is not None:
            _remove_file(event_path)
        return _blocked_output("DOCS_ONLY_TASK_ROOT_UNWRITABLE")

    return {
        "workflow_kind": WorkflowKind.DOCS_ONLY.value,
        "previous_docs_state": None,
        "docs_state": DocsOnlyStage.DISCUSSION.value,
        "state_ref": "state.json",
        "event_ref": event_ref,
        "created_artifacts": [
            str(task_paths.state_path),
            str(task_paths.logs_dir),
            str(task_paths.task_root / event_ref),
        ],
        "reason_code": None,
    }


def _advance_docs_only(input_data: DocsOnlyRuntimeInput) -> dict[str, object]:
    task_paths = get_task_paths(input_data.task_root)
    if not task_paths.state_path.exists():
        return _blocked_output("DOCS_ONLY_STATE_MISSING")
    if not input_data.summary.strip():
        return _blocked_output("DOCS_ONLY_SUMMARY_MISSING")

    try:
        state = _read_docs_state(task_paths.state_path)
    except DocsOnlyRunbookApprovalError:
        return _blocked_output("DOCS_ONLY_RUNBOOK_APPROVAL_BLOCKED")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return _blocked_output("DOCS_ONLY_STATE_INVALID")

    transition = TRANSITIONS.get(input_data.event)
    if transition is None:
        return _blocked_output("DOCS_ONLY_EVENT_INVALID")
    expected_stage, next_stage = transition
    if state.docs_state != expected_stage:
        return _blocked_output("DOCS_ONLY_TRANSITION_INVALID", docs_state=state.docs_state.value)

    event_path = None
    try:
        event_ref, event_path, event_payload = _build_event_log(
            task_paths.logs_dir,
            event=input_data.event,
            previous_stage=state.docs_state,
            next_stage=next_stage,
            summary=input_data.summary,
            artifact_ref=input_data.artifact_ref,
            evidence_refs=input_data.evidence_refs or [],
        )
        updated = _with_transition(
            state,
            input_data.event,
            next_stage,
            input_data.artifact_ref or event_ref,
            event_ref,
            input_data.adapter_meta or {},
        )
        _write_event_log_payload(event_path, event_payload)
        _write_docs_state(task_paths.state_path, updated)
    except OSError:
        if event_path is not None:
            _remove_file(event_path)
        return _blocked_output("DOCS_ONLY_STATE_UPDATE_FAILED", docs_state=state.docs_state.value)

    return {
        "workflow_kind": WorkflowKind.DOCS_ONLY.value,
        "previous_docs_state": state.docs_state.value,
        "docs_state": next_stage.value,
        "state_ref": "state.json",
        "event_ref": event_ref,
        "created_artifacts": [str(task_paths.task_root / event_ref)],
        "reason_code": None,
    }


def _coerce_event(value: DocsOnlyEvent | str) -> DocsOnlyEvent | str:
    if isinstance(value, DocsOnlyEvent):
        return value
    normalized = str(value).strip()
    try:
        return DocsOnlyEvent(normalized)
    except ValueError:
        return normalized


def _coerce_workflow_kind(value: WorkflowKind | str | None) -> WorkflowKind | str | None:
    if value is None or isinstance(value, WorkflowKind):
        return value
    normalized = str(value).strip()
    try:
        return WorkflowKind(normalized)
    except ValueError:
        return normalized


def _is_runbook_approval_event(value: DocsOnlyEvent | str) -> bool:
    return isinstance(value, str) and value.strip().upper() in RUNBOOK_APPROVAL_EVENTS


def _build_event_log(
    logs_dir: Path,
    *,
    event: DocsOnlyEvent,
    previous_stage: DocsOnlyStage | None,
    next_stage: DocsOnlyStage,
    summary: str,
    artifact_ref: str | None,
    evidence_refs: list[str],
) -> tuple[str, Path, dict[str, Any]]:
    path = reserve_log_path(logs_dir, "docs-only")
    event_ref = log_ref_for_path(logs_dir, path)
    payload = {
        "record_type": "docs_only_event",
        "event": event.value,
        "previous_docs_state": previous_stage.value if previous_stage is not None else None,
        "next_docs_state": next_stage.value,
        "summary": summary.strip(),
        "artifact_ref": artifact_ref,
        "evidence_refs": evidence_refs,
        "occurred_at": kst_now_iso(),
    }
    return event_ref, path, payload


def _write_event_log_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _remove_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink()


def _state_to_payload(state: DocsOnlyState) -> dict[str, Any]:
    payload = asdict(state)
    payload["workflow_kind"] = state.workflow_kind.value
    payload["docs_state"] = state.docs_state.value
    return payload


def _write_docs_state(state_path: Path, state: DocsOnlyState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(_state_to_payload(state), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _read_docs_state(state_path: Path) -> DocsOnlyState:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("docs-only state root must be a JSON object.")
    if _has_runbook_approval_payload(payload):
        raise DocsOnlyRunbookApprovalError("runbook approval payload is invalid for docs-only state.")
    schema_version = int(payload["schema_version"])
    if schema_version != DOCS_ONLY_SCHEMA_VERSION:
        raise ValueError("unsupported docs-only schema_version.")
    workflow_kind = WorkflowKind(payload["workflow_kind"])
    if workflow_kind != WorkflowKind.DOCS_ONLY:
        raise ValueError("state.json is not a docs-only task state.")
    return DocsOnlyState(
        schema_version=schema_version,
        workflow_kind=workflow_kind,
        docs_state=DocsOnlyStage(payload["docs_state"]),
        user_request=str(payload["user_request"]),
        target_doc_refs=[str(item) for item in payload.get("target_doc_refs", [])],
        proposal_ref=payload.get("proposal_ref"),
        diff_ref=payload.get("diff_ref"),
        applied_ref=payload.get("applied_ref"),
        last_event_ref=payload.get("last_event_ref"),
        event_history_refs=[str(item) for item in payload.get("event_history_refs", [])],
        last_updated=str(payload["last_updated"]),
        adapter_meta=dict(payload.get("adapter_meta", {})),
    )


def _has_runbook_approval_payload(payload: dict[str, Any]) -> bool:
    if payload.get("session_state") == "awaiting_approval":
        return True
    pending = payload.get("pending_approval_for")
    return pending is not None and str(pending) in RUNBOOK_APPROVAL_POINTS


def _with_transition(
    state: DocsOnlyState,
    event: DocsOnlyEvent,
    next_stage: DocsOnlyStage,
    artifact_ref: str,
    event_ref: str,
    adapter_meta: dict[str, Any],
) -> DocsOnlyState:
    proposal_ref = state.proposal_ref
    diff_ref = state.diff_ref
    applied_ref = state.applied_ref
    if event == DocsOnlyEvent.PRESENT_PROPOSAL:
        proposal_ref = artifact_ref
    elif event == DocsOnlyEvent.PRESENT_DIFF:
        diff_ref = artifact_ref
    elif event == DocsOnlyEvent.APPLY:
        applied_ref = artifact_ref

    return DocsOnlyState(
        schema_version=state.schema_version,
        workflow_kind=state.workflow_kind,
        docs_state=next_stage,
        user_request=state.user_request,
        target_doc_refs=list(state.target_doc_refs),
        proposal_ref=proposal_ref,
        diff_ref=diff_ref,
        applied_ref=applied_ref,
        last_event_ref=event_ref,
        event_history_refs=state.event_history_refs + [event_ref],
        last_updated=kst_now_human(),
        adapter_meta=_merge_adapter_meta(state.adapter_meta, adapter_meta),
    )


def _merge_adapter_meta(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if not incoming:
        return dict(existing)
    merged = dict(existing)
    merged.update(incoming)
    return merged


def _blocked_output(
    reason_code: str,
    *,
    docs_state: str | None = None,
    message_summary: str | None = None,
) -> dict[str, object]:
    return {
        "workflow_kind": WorkflowKind.DOCS_ONLY.value,
        "previous_docs_state": docs_state,
        "docs_state": docs_state,
        "state_ref": None,
        "event_ref": None,
        "created_artifacts": [],
        "reason_code": reason_code,
        "message_summary": message_summary or f"Docs-only workflow blocked: {reason_code}",
    }
