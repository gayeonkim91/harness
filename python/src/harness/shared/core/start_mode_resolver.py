"""Resolve /wf-start workflow mode and active repo profile locator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.shared.contracts.state import WorkflowMode


DEFAULT_REPO_PROFILE_REF = "contracts/repo_profile.md"


@dataclass(slots=True)
class StartModeResolverInput:
    """Workspace-level inputs for resolving /wf-start mode."""

    workspace_root: Path
    explicit_repo_profile_ref: str | None = None
    adoption_kind: str | None = None

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root)


@dataclass(slots=True)
class StartModeResolverResult:
    """Resolved /wf-start mode fields consumed by StartRuntimeInput."""

    workflow_mode: WorkflowMode
    repo_profile_ref: str | None
    adoption_kind: str | None
    workflow_mode_resolved: bool
    resolution_source: str

    def to_payload(self) -> dict[str, object]:
        return {
            "workflow_mode": self.workflow_mode.value,
            "repo_profile_ref": self.repo_profile_ref,
            "adoption_kind": self.adoption_kind,
            "workflow_mode_resolved": self.workflow_mode_resolved,
            "resolution_source": self.resolution_source,
        }

    def to_start_runtime_payload(self) -> dict[str, object]:
        return {
            "workflow_mode": self.workflow_mode.value,
            "repo_profile_ref": self.repo_profile_ref,
            "adoption_kind": self.adoption_kind,
            "workflow_mode_resolved": self.workflow_mode_resolved,
        }


def _profile_exists(workspace_root: Path, repo_profile_ref: str) -> bool:
    profile_path = Path(repo_profile_ref)
    if not profile_path.is_absolute():
        profile_path = workspace_root / profile_path
    return profile_path.exists()


def resolve_start_mode(input_data: StartModeResolverInput) -> StartModeResolverResult:
    """Resolve guided/generic mode using explicit input and workspace convention.

    An explicit profile ref means the caller has configured guided mode; the guard
    will later validate readability and schema. Without an explicit ref, the
    fixed workspace convention is used if present, otherwise generic mode is used.
    """

    workspace_root = input_data.workspace_root
    if input_data.explicit_repo_profile_ref:
        return StartModeResolverResult(
            workflow_mode=WorkflowMode.GUIDED,
            repo_profile_ref=input_data.explicit_repo_profile_ref,
            adoption_kind=input_data.adoption_kind,
            workflow_mode_resolved=True,
            resolution_source="explicit_repo_profile_ref",
        )

    if _profile_exists(workspace_root, DEFAULT_REPO_PROFILE_REF):
        return StartModeResolverResult(
            workflow_mode=WorkflowMode.GUIDED,
            repo_profile_ref=DEFAULT_REPO_PROFILE_REF,
            adoption_kind=input_data.adoption_kind,
            workflow_mode_resolved=True,
            resolution_source="workspace_convention",
        )

    return StartModeResolverResult(
        workflow_mode=WorkflowMode.GENERIC,
        repo_profile_ref=None,
        adoption_kind=None,
        workflow_mode_resolved=True,
        resolution_source="no_active_profile",
    )
