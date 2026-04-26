"""Symbolic artifact action contracts consumed by /wf-apply."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactTarget(str, Enum):
    """Supported artifact targets."""

    PLAN = "plan"
    STEPS = "steps"


class SelectionMode(str, Enum):
    """Supported step selection modes."""

    NEXT_PENDING_AFTER_CURRENT = "next_pending_after_current"
    FIRST_PENDING = "first_pending"
    EXPLICIT_STEP_REF = "explicit_step_ref"


@dataclass(slots=True)
class CurrentStepRefSnapshot:
    """Resolved current step context passed from /wf-next to /wf-apply."""

    step_ref: str
    step_text: str
    go_marker_present: bool


@dataclass(slots=True)
class SelectionBasis:
    """Selection policy for steps.select_next_go_step."""

    mode: SelectionMode
    explicit_step_ref: str | None = None


@dataclass(slots=True)
class ArtifactAction:
    """Symbolic action emitted by /wf-next."""

    target: ArtifactTarget
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    basis_ref: str = ""
