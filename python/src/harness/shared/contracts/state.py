"""Canonical state contracts for the shared harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionState(str, Enum):
    """Allowed runtime session states."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED = "paused"
    DONE = "done"


class WorkflowMode(str, Enum):
    """Task workflow mode pinned in state."""

    GUIDED = "guided"
    GENERIC = "generic"


class CurrentPhase(str, Enum):
    """Shared workflow phases."""

    PRE_PLANNING = "pre-planning"
    PLAN = "plan"
    STEP = "step"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    REVIEW = "review"


class ReviewOutcome(str, Enum):
    """Review outcomes persisted in state."""

    DONE = "DONE"
    DONE_WITH_NOTE = "DONE_WITH_NOTE"
    REWORK = "REWORK"
    REWRITE_PLAN = "REWRITE_PLAN"
    HOLD = "HOLD"


@dataclass(slots=True)
class HarnessCounters:
    """Mutable remediation counters persisted in state."""

    rework_count: int = 0
    rewrite_count: int = 0
    rollback_count: int = 0


@dataclass(slots=True)
class HarnessState:
    """Canonical persisted workflow state."""

    schema_version: int
    session_state: SessionState
    workflow_mode: WorkflowMode
    current_phase: CurrentPhase
    repo_profile_ref: str | None
    workspace_baseline_ref: str | None
    current_step_ref: str | None
    latest_checkpoint_ref: str | None
    latest_verification_ref: str | None
    latest_review_ref: str | None
    pending_approval_for: str | None
    review_outcome: ReviewOutcome | None
    closure_authorized: bool
    counters: HarnessCounters
    blocked_transition: str | None
    blocked_reason_ref: str | None
    stop_condition_ref: str | None
    last_updated: str
    approvals_granted: list[int] = field(default_factory=list)
    adapter_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeferredStateTransition:
    """Deferred state mutation produced by /wf-next and applied after /wf-apply."""

    session_state: SessionState
    current_phase: CurrentPhase
    pending_approval_for: str | None
    review_outcome: ReviewOutcome | None
    closure_authorized: bool
    counters: HarnessCounters
    blocked_transition: str | None = None
    blocked_reason_ref: str | None = None
    stop_condition_ref: str | None = None
    approvals_granted: list[int] | None = None


@dataclass(slots=True)
class GuardStateMutation:
    """Typed blocked-state mutation emitted by the shared guard executor."""

    session_state: SessionState = SessionState.PAUSED
    blocked_transition: str | None = None
    blocked_reason_ref: str | None = None
    stop_condition_ref: str | None = None
    last_updated: str | None = None
