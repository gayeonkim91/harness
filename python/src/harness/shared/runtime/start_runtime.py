"""Deterministic helper for the non-LLM part of /wf-start."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from harness.shared.contracts.profile import ReadTargetKind, RepoProfile, SelectorType, TypedReadEntry
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode
from harness.shared.artifacts.plan_artifact import render_initial_verification_contract, scaffold_plan_with_verification
from harness.shared.artifacts.state_artifact import write_initial_state
from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.phase_spec_loader import PhaseSpecLoadError, resolve_workspace_root
from harness.shared.core.repo_profile_loader import RepoProfileLoadError, load_repo_profile
from harness.shared.artifacts.steps_artifact import scaffold_steps
from harness.shared.core.snapshot_helper import capture_workspace_baseline
from harness.shared.core.start_mode_resolver import StartModeResolverInput, resolve_start_mode
from harness.shared.core.task_paths import get_task_paths


@dataclass(slots=True)
class StartRuntimeInput:
    """Resolved inputs produced by the /wf-start skill prompt."""

    task_root: Path
    task_name: str
    workflow_mode: WorkflowMode
    repo_profile_ref: str | None
    task_classification: str
    initial_phase: CurrentPhase
    minimum_read_set: list[TypedReadEntry] = field(default_factory=list)
    phase_doc_ref: str = ""
    user_request: str = ""
    adoption_kind: str | None = None
    workspace_root: Path | None = None
    workflow_mode_resolved: bool = False
    explicit_repo_profile_ref: str | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        if isinstance(self.workflow_mode, str):
            self.workflow_mode = WorkflowMode(self.workflow_mode)
        if isinstance(self.initial_phase, str):
            self.initial_phase = CurrentPhase(self.initial_phase)
        if self.workspace_root is not None:
            self.workspace_root = Path(self.workspace_root)
        self.minimum_read_set = [_normalize_read_entry(entry) for entry in self.minimum_read_set]


def _kst_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _normalize_read_entry(entry: TypedReadEntry | dict[str, Any]) -> TypedReadEntry:
    if isinstance(entry, TypedReadEntry):
        return entry
    if not isinstance(entry, dict):
        raise ValueError("minimum_read_set entries must be TypedReadEntry instances or mapping payloads.")
    try:
        return TypedReadEntry(
            read_target_kind=ReadTargetKind(entry["read_target_kind"]),
            doc_path=str(entry["doc_path"]),
            selector_type=SelectorType(entry["selector_type"]),
            section_selector=entry["section_selector"],
            why=str(entry["why"]),
        )
    except KeyError as exc:
        raise ValueError(f"minimum_read_set entry is missing required field: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"minimum_read_set entry is invalid: {exc}") from exc


def _blocked_start_output(reason_code: str) -> dict[str, object]:
    return {
        "task_classification": None,
        "initial_phase": None,
        "minimum_read_set": [],
        "repo_profile_ref": None,
        "phase_doc_ref": None,
        "created_artifacts": [],
        "reason_code": reason_code,
    }


def _validate_initial_phase(initial_phase: CurrentPhase) -> str | None:
    if initial_phase not in {CurrentPhase.PRE_PLANNING, CurrentPhase.PLAN}:
        return "START_INITIAL_PHASE_INVALID"
    return None


def _read_entry_key(entry: TypedReadEntry) -> str:
    return str(
        {
            "read_target_kind": entry.read_target_kind.value,
            "doc_path": entry.doc_path,
            "selector_type": entry.selector_type.value,
            "section_selector": entry.section_selector,
            "why": entry.why,
        }
    )


def _validate_guided_profile_input(
    input_data: StartRuntimeInput,
    workspace_root: Path,
    repo_profile: RepoProfile | None,
) -> str | None:
    if input_data.workflow_mode != WorkflowMode.GUIDED:
        return None
    if not input_data.repo_profile_ref:
        return "START_REPO_PROFILE_UNAVAILABLE"
    if repo_profile is None:
        try:
            repo_profile = load_repo_profile(input_data.repo_profile_ref, workspace_root=workspace_root)
        except RepoProfileLoadError:
            return "START_REPO_PROFILE_UNAVAILABLE"

    classification = repo_profile.guided_classifications.get(input_data.task_classification)
    if classification is None:
        return "START_CLASSIFICATION_INVALID"
    allowed_read_set = classification.minimum_read_set_default + classification.minimum_read_set_extensions
    allowed_keys = {_read_entry_key(entry) for entry in allowed_read_set}
    if any(_read_entry_key(entry) not in allowed_keys for entry in input_data.minimum_read_set):
        return "START_MINIMUM_READ_SET_INVALID"
    return None


def _resolve_mode_input(input_data: StartRuntimeInput, workspace_root: Path) -> None:
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=workspace_root,
            explicit_repo_profile_ref=input_data.explicit_repo_profile_ref or input_data.repo_profile_ref,
            adoption_kind=input_data.adoption_kind,
        )
    )
    input_data.workflow_mode = resolved.workflow_mode
    input_data.repo_profile_ref = resolved.repo_profile_ref
    input_data.adoption_kind = resolved.adoption_kind
    input_data.workflow_mode_resolved = resolved.workflow_mode_resolved


def execute_start_runtime(input_data: StartRuntimeInput) -> dict[str, object]:
    """Create artifacts and persist initial state from prompt-resolved values.

    Classification and initial-phase judgement belong to the skill prompt.
    This helper only owns deterministic scaffold/state work.
    """

    task_root = Path(input_data.task_root)
    try:
        workspace_root = resolve_workspace_root(input_data.workspace_root)
    except PhaseSpecLoadError:
        return _blocked_start_output("START_WORKSPACE_ROOT_MISSING")
    _resolve_mode_input(input_data, workspace_root)
    guard_decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=task_root,
            context={
                "user_request": input_data.user_request,
                "workflow_mode": input_data.workflow_mode.value,
                "repo_profile_ref": input_data.repo_profile_ref,
                "adoption_kind": input_data.adoption_kind,
                "workspace_root": workspace_root,
                "workflow_mode_resolved": input_data.workflow_mode_resolved,
            },
        )
    )
    if not guard_decision.allow:
        return _blocked_start_output(guard_decision.reason_code or "START_GUARD_BLOCKED")

    phase_reason = _validate_initial_phase(input_data.initial_phase)
    if phase_reason is not None:
        return _blocked_start_output(phase_reason)

    profile_reason = _validate_guided_profile_input(input_data, workspace_root, guard_decision.repo_profile)
    if profile_reason is not None:
        return _blocked_start_output(profile_reason)

    task_paths = get_task_paths(task_root)
    try:
        task_paths.task_root.mkdir(parents=True, exist_ok=True)
        verification_template = None
        gate_source = "generic fallback"
        if guard_decision.repo_profile is not None and input_data.adoption_kind is not None:
            verification_template = guard_decision.repo_profile.verification_gate_templates.get(input_data.adoption_kind)
            if verification_template is not None:
                gate_source = "repo_profile.verification_gate_templates"
        verification_contract = render_initial_verification_contract(
            adoption_kind=input_data.adoption_kind,
            task_classification=input_data.task_classification,
            template=verification_template,
            gate_source=gate_source,
        )
        plan_path = scaffold_plan_with_verification(task_paths.task_root, input_data.task_name, verification_contract)
        steps_path = scaffold_steps(task_paths.task_root)
        task_paths.logs_dir.mkdir(parents=True, exist_ok=True)
        baseline_ref = capture_workspace_baseline(task_paths.task_root, workspace_root=workspace_root)
    except OSError:
        return _blocked_start_output("START_TASK_ROOT_UNWRITABLE")
    initial_state = HarnessState(
        schema_version=1,
        session_state=SessionState.ACTIVE,
        workflow_mode=input_data.workflow_mode,
        current_phase=input_data.initial_phase,
        repo_profile_ref=input_data.repo_profile_ref,
        workspace_baseline_ref=baseline_ref,
        current_step_ref=None,
        latest_checkpoint_ref=None,
        latest_verification_ref=None,
        latest_review_ref=None,
        pending_approval_for=None,
        review_outcome=None,
        closure_authorized=False,
        counters=HarnessCounters(),
        blocked_transition=None,
        blocked_reason_ref=None,
        stop_condition_ref=None,
        last_updated=_kst_timestamp(),
        adapter_meta={},
    )
    write_initial_state(task_paths.state_path, initial_state)

    minimum_read_set: list[dict[str, Any]] = []
    for entry in input_data.minimum_read_set:
        minimum_read_set.append(
            {
                "read_target_kind": entry.read_target_kind.value,
                "doc_path": entry.doc_path,
                "selector_type": entry.selector_type.value,
                "section_selector": entry.section_selector,
                "why": entry.why,
            }
        )

    return {
        "task_classification": input_data.task_classification,
        "initial_phase": input_data.initial_phase.value,
        "minimum_read_set": minimum_read_set,
        "repo_profile_ref": input_data.repo_profile_ref,
        "phase_doc_ref": input_data.phase_doc_ref,
        "created_artifacts": [
            str(plan_path),
            str(steps_path),
            str(task_paths.state_path),
            str(task_paths.logs_dir),
        ],
        "reason_code": None,
    }
