"""Resolve /wf-start workflow mode, kind, and active repo profile locator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from harness.shared.contracts.state import WorkflowMode
from harness.shared.contracts.workflow import WorkflowKind


DEFAULT_REPO_PROFILE_REF = "contracts/repo_profile.md"
_DOC_SUFFIXES = {".adoc", ".md", ".mdx", ".rst", ".txt"}
_DOC_PATH_PARTS = {"doc", "docs", "documentation"}
_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
}
_CODE_PATH_PARTS = {
    "app",
    "cmd",
    "scripts",
    "server",
    "src",
    "test",
    "tests",
}


@dataclass(slots=True)
class StartModeResolverInput:
    """Workspace-level inputs for resolving /wf-start mode."""

    workspace_root: Path
    explicit_repo_profile_ref: str | None = None
    adoption_kind: str | None = None
    workflow_kind_hint: WorkflowKind | str | None = None
    request_path_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root)
        self.request_path_refs = [str(item) for item in self.request_path_refs]


@dataclass(slots=True)
class StartModeResolverResult:
    """Resolved /wf-start mode fields consumed by StartRuntimeInput."""

    workflow_mode: WorkflowMode
    repo_profile_ref: str | None
    adoption_kind: str | None
    workflow_kind: WorkflowKind
    workflow_kind_resolved: bool
    workflow_mode_resolved: bool
    resolution_source: str
    workflow_kind_source: str

    def to_payload(self) -> dict[str, object]:
        return {
            "workflow_mode": self.workflow_mode.value,
            "repo_profile_ref": self.repo_profile_ref,
            "adoption_kind": self.adoption_kind,
            "workflow_kind": self.workflow_kind.value,
            "workflow_kind_resolved": self.workflow_kind_resolved,
            "workflow_mode_resolved": self.workflow_mode_resolved,
            "resolution_source": self.resolution_source,
            "workflow_kind_source": self.workflow_kind_source,
        }

    def to_start_runtime_payload(self) -> dict[str, object]:
        return {
            "workflow_mode": self.workflow_mode.value,
            "repo_profile_ref": self.repo_profile_ref,
            "adoption_kind": self.adoption_kind,
            "workflow_kind": self.workflow_kind.value,
            "workflow_kind_resolved": self.workflow_kind_resolved,
            "workflow_mode_resolved": self.workflow_mode_resolved,
        }


def _profile_exists(workspace_root: Path, repo_profile_ref: str) -> bool:
    profile_path = Path(repo_profile_ref)
    if not profile_path.is_absolute():
        profile_path = workspace_root / profile_path
    return profile_path.exists()


def _normalize_workflow_kind(value: WorkflowKind | str | None) -> tuple[WorkflowKind | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, WorkflowKind):
        if value == WorkflowKind.UNKNOWN:
            return value, "workflow_kind_hint_unknown_explicit"
        return value, "workflow_kind_hint"
    normalized = str(value).strip()
    if not normalized:
        return None, None
    try:
        kind = WorkflowKind(normalized)
    except ValueError:
        return WorkflowKind.UNKNOWN, "workflow_kind_hint_invalid"
    if kind == WorkflowKind.UNKNOWN:
        return kind, "workflow_kind_hint_unknown_explicit"
    return kind, "workflow_kind_hint"


def _path_clues(path_ref: str) -> tuple[bool, bool]:
    path = Path(path_ref)
    parts = {part.lower() for part in path.parts}
    suffix = path.suffix.lower()
    docs_clue = suffix in _DOC_SUFFIXES or bool(parts & _DOC_PATH_PARTS)
    code_clue = suffix in _CODE_SUFFIXES or (not docs_clue and bool(parts & _CODE_PATH_PARTS))
    return code_clue, docs_clue


def _workflow_kind_from_path_refs(path_refs: list[str]) -> tuple[WorkflowKind | None, str | None]:
    refs = [item.strip() for item in path_refs if item.strip()]
    if not refs:
        return None, None
    clues = [_path_clues(item) for item in refs]
    has_code = any(code_clue for code_clue, _ in clues)
    has_docs = any(docs_clue for _, docs_clue in clues)
    has_unknown = any(not code_clue and not docs_clue for code_clue, docs_clue in clues)
    if has_code and has_docs:
        return WorkflowKind.UNKNOWN, "path_mixed_clue"
    if has_code:
        return WorkflowKind.RUNBOOK, "path_code_clue"
    if has_docs and not has_unknown:
        return WorkflowKind.DOCS_ONLY, "path_docs_clue"
    return None, None


def _resolve_workflow_kind(
    workflow_kind_hint: WorkflowKind | str | None,
    request_path_refs: list[str],
) -> tuple[WorkflowKind, bool, str]:
    hint, hint_source = _normalize_workflow_kind(workflow_kind_hint)
    path_kind, path_source = _workflow_kind_from_path_refs(request_path_refs)
    if hint is None:
        if path_kind is None:
            return WorkflowKind.UNKNOWN, False, "no_workflow_kind_hint"
        if path_kind == WorkflowKind.UNKNOWN:
            return WorkflowKind.UNKNOWN, False, path_source or "path_unknown_clue"
        return path_kind, True, path_source or "path_clue"
    if hint == WorkflowKind.UNKNOWN:
        return WorkflowKind.UNKNOWN, False, hint_source or "workflow_kind_hint"
    if path_kind == WorkflowKind.UNKNOWN and path_source == "path_mixed_clue":
        if hint == WorkflowKind.RUNBOOK:
            return WorkflowKind.RUNBOOK, True, hint_source or "workflow_kind_hint"
        return WorkflowKind.UNKNOWN, False, "workflow_kind_hint_path_conflict"
    if path_kind == WorkflowKind.UNKNOWN:
        return WorkflowKind.UNKNOWN, False, "workflow_kind_hint_path_conflict"
    hint_path_conflict = (
        hint == WorkflowKind.RUNBOOK
        and path_kind == WorkflowKind.DOCS_ONLY
    ) or (
        hint in {WorkflowKind.DOCS_ONLY, WorkflowKind.DISCUSSION_ONLY}
        and path_kind == WorkflowKind.RUNBOOK
    )
    if hint_path_conflict:
        return WorkflowKind.UNKNOWN, False, "workflow_kind_hint_path_conflict"
    return hint, True, hint_source or "workflow_kind_hint"


def resolve_start_mode(input_data: StartModeResolverInput) -> StartModeResolverResult:
    """Resolve guided/generic mode using explicit input and workspace convention.

    An explicit profile ref means the caller has configured guided mode; the guard
    will later validate readability and schema. Without an explicit ref, the
    fixed workspace convention is used if present, otherwise generic mode is used.
    """

    workspace_root = input_data.workspace_root
    workflow_kind, workflow_kind_resolved, workflow_kind_source = _resolve_workflow_kind(
        input_data.workflow_kind_hint,
        input_data.request_path_refs,
    )
    if input_data.explicit_repo_profile_ref:
        return StartModeResolverResult(
            workflow_mode=WorkflowMode.GUIDED,
            repo_profile_ref=input_data.explicit_repo_profile_ref,
            adoption_kind=input_data.adoption_kind,
            workflow_kind=workflow_kind,
            workflow_kind_resolved=workflow_kind_resolved,
            workflow_mode_resolved=True,
            resolution_source="explicit_repo_profile_ref",
            workflow_kind_source=workflow_kind_source,
        )

    if _profile_exists(workspace_root, DEFAULT_REPO_PROFILE_REF):
        return StartModeResolverResult(
            workflow_mode=WorkflowMode.GUIDED,
            repo_profile_ref=DEFAULT_REPO_PROFILE_REF,
            adoption_kind=input_data.adoption_kind,
            workflow_kind=workflow_kind,
            workflow_kind_resolved=workflow_kind_resolved,
            workflow_mode_resolved=True,
            resolution_source="workspace_convention",
            workflow_kind_source=workflow_kind_source,
        )

    return StartModeResolverResult(
        workflow_mode=WorkflowMode.GENERIC,
        repo_profile_ref=None,
        adoption_kind=None,
        workflow_kind=workflow_kind,
        workflow_kind_resolved=workflow_kind_resolved,
        workflow_mode_resolved=True,
        resolution_source="no_active_profile",
        workflow_kind_source=workflow_kind_source,
    )
