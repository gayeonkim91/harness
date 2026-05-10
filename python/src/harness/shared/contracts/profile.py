"""Repo profile contracts consumed by the shared harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReadTargetKind(str, Enum):
    """Supported read target kinds."""

    DOC_SECTION = "doc_section"
    ARTIFACT_VIEW = "artifact_view"
    STATE_FIELD = "state_field"
    DERIVED_INPUT = "derived_input"


class SelectorType(str, Enum):
    """Supported selector types for typed read entries."""

    HEADER_PATH = "header_path"
    HEADER_SET = "header_set"
    WILDCARD = "wildcard"
    FIELD_NAME = "field_name"
    VIRTUAL = "virtual"


@dataclass(slots=True)
class TypedReadEntry:
    """Structured read entry returned by guided profiles."""

    read_target_kind: ReadTargetKind
    doc_path: str
    selector_type: SelectorType
    section_selector: str | list[str]
    why: str


@dataclass(slots=True)
class GuidedClassification:
    """Guided classification definition loaded from the repo profile."""

    token: str
    meaning: list[str] = field(default_factory=list)
    default_initial_phase_hint: str | None = None
    minimum_read_set_default: list[TypedReadEntry] = field(default_factory=list)
    minimum_read_set_extensions: list[TypedReadEntry] = field(default_factory=list)


@dataclass(slots=True)
class InitializationDocRule:
    """Required initialization doc rule for a given adoption kind."""

    doc_path: str
    required_sections: list[str] = field(default_factory=list)
    min_level_two_sections: int | None = None
    ignored_level_two_sections: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectContext:
    """Project adoption context resolved before guided workflow starts."""

    adoption_kind_source_kind: str
    adoption_kind_resolution_order: list[str] = field(default_factory=list)
    adoption_kind_allowed: list[str] = field(default_factory=list)
    initialization_requirements: dict[str, list[InitializationDocRule]] = field(default_factory=dict)


@dataclass(slots=True)
class CheckpointSupplement:
    """Repo-specific checkpoint supplement definition."""

    supplement_id: str
    applies_to_phase: str
    reads: list[TypedReadEntry] = field(default_factory=list)


@dataclass(slots=True)
class VerificationGate:
    """Initial verification gate definition supplied by a repo profile."""

    name: str
    command: str
    working_directory: str
    success_criteria: str
    evidence: str


@dataclass(slots=True)
class ConditionalVerificationGate:
    """Conditional verification gate definition supplied by a repo profile."""

    condition: str
    gate: str


@dataclass(slots=True)
class ManualVerificationCheck:
    """Manual verification check definition supplied by a repo profile."""

    check: str
    evidence: str


@dataclass(slots=True)
class VerificationGateTemplate:
    """Initial task-local verification contract template."""

    required_gates: list[VerificationGate] = field(default_factory=list)
    conditional_gates: list[ConditionalVerificationGate] = field(default_factory=list)
    manual_checks: list[ManualVerificationCheck] = field(default_factory=list)


@dataclass(slots=True)
class VerificationToolchain:
    """Repo-level build/test/gate toolchain chosen during onboarding."""

    configured: bool
    build_tool: str
    test_tool: str | None = None
    working_directory: str = "."
    required_gates: list[VerificationGate] = field(default_factory=list)
    conditional_gates: list[ConditionalVerificationGate] = field(default_factory=list)
    manual_checks: list[ManualVerificationCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepoProfile:
    """Loaded repo onboarding profile."""

    profile_id: str
    profile_version: int
    provenance_refs: list[str] = field(default_factory=list)
    project_context: ProjectContext | None = None
    guided_classifications: dict[str, GuidedClassification] = field(default_factory=dict)
    known_issue_selector_mapping: list[TypedReadEntry] = field(default_factory=list)
    checkpoint_supplements: dict[str, CheckpointSupplement] = field(default_factory=dict)
    verification_gate_templates: dict[str, VerificationGateTemplate] = field(default_factory=dict)
    verification_toolchain: VerificationToolchain | None = None
