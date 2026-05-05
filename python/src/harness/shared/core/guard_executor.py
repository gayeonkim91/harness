"""Shared guard executor entrypoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from harness.shared.contracts.profile import RepoProfile
from harness.shared.core.phase_spec_loader import PhaseSpecLoadError, resolve_workspace_root
from harness.shared.core.repo_profile_loader import RepoProfileLoadError, load_repo_profile
from harness.shared.core.start_mode_resolver import DEFAULT_REPO_PROFILE_REF
from harness.shared.contracts.state import CurrentPhase, GuardStateMutation, HarnessState, SessionState, WorkflowMode
from harness.shared.contracts.workflow import WorkflowKind


CHECKPOINT_PHASES = {
    CurrentPhase.PRE_PLANNING,
    CurrentPhase.PLAN,
    CurrentPhase.STEP,
    CurrentPhase.IMPLEMENTATION,
}


def _has_header(content: str, header: str) -> bool:
    pattern = re.compile(rf"^##\s+{re.escape(header)}\s*$")
    return any(pattern.match(line) for line in content.splitlines())


def _count_level_two_headers(content: str, ignored_headers: set[str]) -> int:
    return sum(
        1
        for line in content.splitlines()
        if line.startswith("## ") and line[3:].strip() not in ignored_headers
    )


def _detect_start_init_reason(task_root: Path) -> str | None:
    if not task_root.exists():
        return None

    artifact_presence = [
        (task_root / "plan.md").exists(),
        (task_root / "steps.md").exists(),
        (task_root / "state.json").exists(),
        (task_root / "logs").is_dir(),
    ]
    present_count = sum(artifact_presence)
    if present_count == 4:
        return "START_TASK_ALREADY_INITIALIZED"
    if 0 < present_count < 4:
        return "START_TASK_INIT_PARTIAL"
    return None


@dataclass(slots=True)
class GuardInput:
    """Normalized guard input passed by adapters and shared skills."""

    action: str
    task_root: Path
    state: HarnessState | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuardDecision:
    """Guard allow/block result."""

    allow: bool
    reason_code: str | None = None
    message_summary: str | None = None
    applied_state_mutation: GuardStateMutation | None = None
    repo_profile: RepoProfile | None = None


def run_guard(input_data: GuardInput) -> GuardDecision:
    """Execute the shared guard pipeline.

    The concrete rule bundles will be added per skill in later steps.
    """
    if input_data.action == "wf-checkpoint":
        return _run_checkpoint_guard(input_data)
    if input_data.action == "wf-verify":
        return _run_verify_guard(input_data)
    if input_data.action == "wf-review":
        return _run_review_guard(input_data)

    if input_data.action != "wf-start":
        return GuardDecision(allow=True)

    user_request = str(input_data.context.get("user_request", "")).strip()
    if not user_request:
        return GuardDecision(
            allow=False,
            reason_code="START_REQUEST_MISSING",
            message_summary="`/wf-start` requires a non-empty user request.",
        )

    init_reason = _detect_start_init_reason(input_data.task_root)
    if init_reason is not None:
        return GuardDecision(
            allow=False,
            reason_code=init_reason,
            message_summary="`/wf-start` cannot reinitialize an existing or partially initialized task root.",
        )

    workflow_mode_resolved = bool(input_data.context.get("workflow_mode_resolved", False))
    if not workflow_mode_resolved:
        return GuardDecision(
            allow=False,
            reason_code="START_WORKFLOW_MODE_UNRESOLVED",
            message_summary="`/wf-start` requires a workflow_mode resolved by shared mode_resolver.",
        )

    workflow_kind = str(input_data.context.get("workflow_kind", WorkflowKind.UNKNOWN.value))
    workflow_kind_resolved = bool(input_data.context.get("workflow_kind_resolved", False))
    if workflow_kind != WorkflowKind.RUNBOOK.value or not workflow_kind_resolved:
        return GuardDecision(
            allow=False,
            reason_code="START_NOT_RUNBOOK",
            message_summary="`/wf-start` only creates artifacts for a resolved runbook workflow.",
        )

    try:
        workspace_root = resolve_workspace_root(input_data.context.get("workspace_root"))
    except PhaseSpecLoadError:
        return GuardDecision(
            allow=False,
            reason_code="START_WORKSPACE_ROOT_MISSING",
            message_summary="`/wf-start` requires an explicit workspace_root.",
        )

    workflow_mode = str(input_data.context.get("workflow_mode", "generic"))
    if workflow_mode != "guided":
        if (workspace_root / DEFAULT_REPO_PROFILE_REF).exists() or input_data.context.get("repo_profile_ref"):
            return GuardDecision(
                allow=False,
                reason_code="START_WORKFLOW_MODE_CONFLICT",
                message_summary="Generic mode is invalid while an active repo profile is available.",
            )
        return GuardDecision(allow=True)

    repo_profile_ref = input_data.context.get("repo_profile_ref")
    if not repo_profile_ref:
        return GuardDecision(
            allow=False,
            reason_code="START_REPO_PROFILE_UNAVAILABLE",
            message_summary="Guided mode requires a readable repo profile ref.",
        )

    try:
        repo_profile = load_repo_profile(Path(repo_profile_ref), workspace_root=workspace_root)
    except RepoProfileLoadError:
        return GuardDecision(
            allow=False,
            reason_code="START_REPO_PROFILE_UNAVAILABLE",
            message_summary="Guided mode repo profile could not be loaded.",
        )

    adoption_kind = str(input_data.context.get("adoption_kind", "")).strip()
    project_context = repo_profile.project_context
    if not adoption_kind or project_context is None or adoption_kind not in project_context.adoption_kind_allowed:
        return GuardDecision(
            allow=False,
            reason_code="START_PROJECT_CONTEXT_UNRESOLVED",
            message_summary="Guided mode requires a resolved project adoption kind.",
        )

    initialization_rules = project_context.initialization_requirements.get(adoption_kind, [])
    for rule in initialization_rules:
        candidate = workspace_root / rule.doc_path
        if not candidate.exists():
            return GuardDecision(
                allow=False,
                reason_code="START_INIT_REQUIRED_DOCS_MISSING",
                message_summary=f"Required initialization doc is missing: {rule.doc_path}",
            )
        content = candidate.read_text(encoding="utf-8")
        for header in rule.required_sections:
            if not _has_header(content, header):
                return GuardDecision(
                    allow=False,
                    reason_code="START_INIT_REQUIRED_DOCS_MISSING",
                    message_summary=f"Initialization doc is missing required section `{header}` in {rule.doc_path}.",
                )
        if rule.min_level_two_sections is not None:
            ignored_headers = set(rule.ignored_level_two_sections)
            if _count_level_two_headers(content, ignored_headers) < rule.min_level_two_sections:
                return GuardDecision(
                    allow=False,
                    reason_code="START_INIT_REQUIRED_DOCS_MISSING",
                    message_summary=(
                        f"Initialization doc `{rule.doc_path}` must contain at least "
                        f"{rule.min_level_two_sections} level-two sections excluding "
                        f"{sorted(ignored_headers)}."
                    ),
                )

    return GuardDecision(allow=True, repo_profile=repo_profile)


def _run_checkpoint_guard(input_data: GuardInput) -> GuardDecision:
    state = input_data.state
    if state is None:
        return GuardDecision(
            allow=False,
            reason_code="STATE_ARTIFACT_MISSING",
            message_summary="`/wf-checkpoint` requires an initialized state.json artifact.",
        )

    requested_phase = input_data.context.get("phase")
    if requested_phase is not None and str(requested_phase) != state.current_phase.value:
        return GuardDecision(
            allow=False,
            reason_code="CHECKPOINT_PHASE_MISMATCH",
            message_summary="`/wf-checkpoint` phase must match state.json.current_phase.",
        )

    if state.current_phase not in CHECKPOINT_PHASES:
        return GuardDecision(
            allow=False,
            reason_code="CHECKPOINT_PHASE_UNSUPPORTED",
            message_summary="`/wf-checkpoint` only supports pre-planning, plan, step, and implementation.",
        )

    task_root = input_data.task_root
    if not (task_root / "plan.md").exists():
        return GuardDecision(
            allow=False,
            reason_code="PLAN_ARTIFACT_MISSING",
            message_summary="`/wf-checkpoint` requires plan.md.",
        )

    if state.current_phase in {CurrentPhase.STEP, CurrentPhase.IMPLEMENTATION} and not state.current_step_ref:
        return GuardDecision(
            allow=False,
            reason_code="CHECKPOINT_CURRENT_STEP_REF_MISSING",
            message_summary="`/wf-checkpoint` requires current_step_ref for step-bearing phases.",
        )

    if state.workflow_mode == WorkflowMode.GUIDED:
        if not state.repo_profile_ref:
            return GuardDecision(
                allow=False,
                reason_code="CHECKPOINT_REPO_PROFILE_UNAVAILABLE",
                message_summary="Guided checkpoint requires a readable repo profile ref.",
            )
        try:
            workspace_root = resolve_workspace_root(input_data.context.get("workspace_root"))
        except PhaseSpecLoadError:
            return GuardDecision(
                allow=False,
                reason_code="CHECKPOINT_REPO_PROFILE_UNAVAILABLE",
                message_summary="Guided checkpoint workspace root could not be resolved.",
            )
        try:
            repo_profile = load_repo_profile(Path(state.repo_profile_ref), workspace_root=workspace_root)
        except RepoProfileLoadError:
            return GuardDecision(
                allow=False,
                reason_code="CHECKPOINT_REPO_PROFILE_UNAVAILABLE",
                message_summary="Guided checkpoint repo profile could not be loaded.",
            )
        return GuardDecision(allow=True, repo_profile=repo_profile)

    return GuardDecision(allow=True)


def _missing_state_decision(action: str) -> GuardDecision:
    return GuardDecision(
        allow=False,
        reason_code="STATE_ARTIFACT_MISSING",
        message_summary=f"`/{action}` requires an initialized state.json artifact.",
    )


def _run_verify_guard(input_data: GuardInput) -> GuardDecision:
    state = input_data.state
    if state is None:
        return _missing_state_decision("wf-verify")

    plan_path = input_data.task_root / "plan.md"
    if state.current_phase != CurrentPhase.VERIFICATION:
        return GuardDecision(False, "VERIFY_PHASE_MISMATCH", "`/wf-verify` requires verification phase.")
    if state.session_state != SessionState.IN_PROGRESS:
        return GuardDecision(False, "VERIFY_SESSION_STATE_INVALID", "`/wf-verify` requires in_progress session.")
    if state.pending_approval_for is not None:
        return GuardDecision(False, "VERIFY_PENDING_APPROVAL_INVALID", "`/wf-verify` requires no pending approval.")
    if state.current_step_ref is not None:
        return GuardDecision(False, "VERIFY_CURRENT_STEP_REF_INVALID", "`/wf-verify` requires no current step ref.")
    if not state.workspace_baseline_ref:
        return GuardDecision(False, "VERIFY_WORKSPACE_BASELINE_MISSING", "`/wf-verify` requires workspace baseline.")
    if not plan_path.exists():
        return GuardDecision(False, "PLAN_ARTIFACT_MISSING", "`/wf-verify` requires plan.md.")
    if not state.latest_verification_ref and not state.latest_checkpoint_ref:
        return GuardDecision(False, "VERIFY_BASIS_REF_MISSING", "`/wf-verify` requires a checkpoint or verification basis.")
    return GuardDecision(True)


def _run_review_guard(input_data: GuardInput) -> GuardDecision:
    state = input_data.state
    if state is None:
        return _missing_state_decision("wf-review")

    plan_path = input_data.task_root / "plan.md"
    if state.current_phase != CurrentPhase.REVIEW:
        return GuardDecision(False, "REVIEW_PHASE_MISMATCH", "`/wf-review` requires review phase.")
    if state.session_state != SessionState.IN_PROGRESS:
        return GuardDecision(False, "REVIEW_SESSION_STATE_INVALID", "`/wf-review` requires in_progress session.")
    if state.pending_approval_for is not None:
        return GuardDecision(False, "REVIEW_PENDING_APPROVAL_INVALID", "`/wf-review` requires no pending approval.")
    if state.current_step_ref is not None:
        return GuardDecision(False, "REVIEW_CURRENT_STEP_REF_INVALID", "`/wf-review` requires no current step ref.")
    if not state.workspace_baseline_ref:
        return GuardDecision(False, "REVIEW_WORKSPACE_BASELINE_MISSING", "`/wf-review` requires workspace baseline.")
    if not plan_path.exists():
        return GuardDecision(False, "PLAN_ARTIFACT_MISSING", "`/wf-review` requires plan.md.")
    if not state.latest_verification_ref:
        return GuardDecision(False, "REVIEW_VERIFICATION_REF_MISSING", "`/wf-review` requires latest verification ref.")
    return GuardDecision(True)
