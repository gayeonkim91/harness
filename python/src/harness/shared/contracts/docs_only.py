"""Contracts for document-only workflow state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from harness.shared.contracts.workflow import WorkflowKind


class DocsOnlyStage(str, Enum):
    """Allowed stages for the document-only workflow."""

    DISCUSSION = "discussion"
    PROPOSAL_VISUALIZED = "proposal_visualized"
    PROPOSAL_ACCEPTED = "proposal_accepted"
    DIFF_PRESENTED = "diff_presented"
    APPLIED = "applied"


class DocsOnlyEvent(str, Enum):
    """Deterministic transition events accepted by docs_only_runtime."""

    START = "start"
    PRESENT_PROPOSAL = "present_proposal"
    ACCEPT_PROPOSAL = "accept_proposal"
    PRESENT_DIFF = "present_diff"
    APPLY = "apply"


@dataclass(slots=True)
class DocsOnlyState:
    """Persisted state.json shape for document-only tasks."""

    schema_version: int
    workflow_kind: WorkflowKind
    docs_state: DocsOnlyStage
    user_request: str
    target_doc_refs: list[str]
    proposal_ref: str | None
    diff_ref: str | None
    applied_ref: str | None
    last_event_ref: str | None
    event_history_refs: list[str]
    last_updated: str
    adapter_meta: dict[str, Any] = field(default_factory=dict)
