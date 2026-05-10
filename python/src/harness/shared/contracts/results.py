"""Result contracts for shared workflow skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from harness.shared.contracts.actions import ArtifactAction, CurrentStepRefSnapshot
from harness.shared.contracts.state import CurrentPhase, DeferredStateTransition, SessionState


class JudgementCode(str, Enum):
    """Judgement codes used across checkpoint/verify/review routing."""

    GO = "GO"
    GO_WITH_NOTE = "GO_WITH_NOTE"
    REWORK = "REWORK"
    REWRITE_STEP = "REWRITE_STEP"
    REWRITE_PLAN = "REWRITE_PLAN"
    ROLLBACK = "ROLLBACK"
    HOLD = "HOLD"
    DONE = "DONE"
    DONE_WITH_NOTE = "DONE_WITH_NOTE"


class NoteTargetHint(str, Enum):
    """Targets for note propagation."""

    PLAN = "plan"
    STEPS = "steps"


class ApplyStatus(str, Enum):
    """Final apply result status."""

    APPLIED = "APPLIED"
    NOOP = "NOOP"
    BLOCKED = "BLOCKED"


class VerificationLintWarningCode(str, Enum):
    """Non-blocking lint warning codes emitted by /wf-verify.

    TEST_REPORT_SKILL_BYPASSED: a test/lint/build/static-analysis gate was summarized without
    the `skill:test-report#verification-assist` basis marker.
    AUTOFIX_COMMAND_RECORDED: verification recorded a formatter/apply command that should be a
    user-directed cleanup, not an automatic /wf-verify gate.
    """

    TEST_REPORT_SKILL_BYPASSED = "VERIFY_TEST_REPORT_SKILL_BYPASSED"
    AUTOFIX_COMMAND_RECORDED = "VERIFY_AUTOFIX_COMMAND_RECORDED"


def normalize_verification_lint_warnings(
    values: Iterable[str | VerificationLintWarningCode],
) -> list[VerificationLintWarningCode]:
    """Keep only known verification lint warning codes, preserving order."""

    seen: set[VerificationLintWarningCode] = set()
    result: list[VerificationLintWarningCode] = []
    for value in values:
        try:
            code = VerificationLintWarningCode(value)
        except ValueError:
            continue
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


@dataclass(slots=True)
class NoteSignal:
    """Note emitted by a checkpoint result."""

    note_text: str
    note_target_hint: NoteTargetHint
    note_basis_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CheckItem:
    """One evaluated checkpoint item from the phase spec."""

    item_index: int
    item_text: str
    result: str
    rationale: str
    basis_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationItem:
    """One verification item executed during /wf-verify."""

    item_key: str
    item_type: str
    label: str
    method: str
    result: str
    summary: str
    basis_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CheckpointResult:
    """Canonical /wf-checkpoint output."""

    checkpoint_ref: str
    phase: CurrentPhase
    judgement_code: JudgementCode
    summary: str
    check_items: list[CheckItem] = field(default_factory=list)
    basis_refs: list[str] = field(default_factory=list)
    note_signals: list[NoteSignal] = field(default_factory=list)
    stop_condition_code: str | None = None
    primary_cause_code: str | None = None
    reason_fingerprint: str | None = None
    current_step_ref_snapshot: CurrentStepRefSnapshot | None = None


@dataclass(slots=True)
class VerificationResult:
    """Canonical /wf-verify output."""

    verification_ref: str
    judgement_code: JudgementCode
    summary: str
    verification_items: list[VerificationItem] = field(default_factory=list)
    basis_refs: list[str] = field(default_factory=list)
    note_signals: list[NoteSignal] = field(default_factory=list)
    verified_task_diff_fingerprint: str | None = None
    stop_condition_code: str | None = None
    primary_cause_code: str | None = None
    reason_fingerprint: str | None = None
    lint_warnings: list[VerificationLintWarningCode] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lint_warnings = normalize_verification_lint_warnings(self.lint_warnings)


@dataclass(slots=True)
class ReviewResult:
    """Canonical /wf-review output."""

    review_ref: str
    judgement_code: JudgementCode
    summary: str
    out_of_scope_change: bool
    key_issues: list[str] = field(default_factory=list)
    verification_blind_spots: list[str] = field(default_factory=list)
    carry_forward_notes: list[str] = field(default_factory=list)
    basis_refs: list[str] = field(default_factory=list)
    verified_task_diff_fingerprint: str | None = None
    primary_cause_code: str | None = None
    reason_fingerprint: str | None = None


@dataclass(slots=True)
class NextResult:
    """Canonical /wf-next output."""

    next_phase: CurrentPhase
    next_session_state: SessionState
    pending_approval_for: str | None
    required_artifact_actions: list[ArtifactAction] = field(default_factory=list)
    reason_code: str | None = None
    routing_basis_ref: str = ""
    deferred_state_transition: DeferredStateTransition | None = None


@dataclass(slots=True)
class ApplyResult:
    """Canonical /wf-apply output."""

    apply_status: ApplyStatus
    reason_code: str | None
    applied_actions: list[ArtifactAction] = field(default_factory=list)
    noop_actions: list[ArtifactAction] = field(default_factory=list)
    updated_artifacts: list[str] = field(default_factory=list)
    current_step_ref_update_mode: str = "unchanged"
    resolved_current_step_ref: str | None = None
    summary: str = ""
