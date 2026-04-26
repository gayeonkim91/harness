"""Repo onboarding profile loader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness.shared.contracts.profile import (
    CheckpointSupplement,
    ConditionalVerificationGate,
    GuidedClassification,
    InitializationDocRule,
    ManualVerificationCheck,
    ProjectContext,
    ReadTargetKind,
    RepoProfile,
    SelectorType,
    TypedReadEntry,
    VerificationGate,
    VerificationGateTemplate,
)
from harness.shared.core.yaml_block import YamlBlockParseError, parse_yaml_block


class RepoProfileLoadError(RuntimeError):
    """Raised when a repo profile cannot be loaded or parsed."""


_YAML_BLOCK_PATTERN = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


def _extract_profile_payload(profile_text: str) -> dict[str, Any]:
    match = _YAML_BLOCK_PATTERN.search(profile_text)
    if match is None:
        raise RepoProfileLoadError("Profile markdown does not contain a fenced YAML block.")
    try:
        payload = parse_yaml_block(match.group(1))
    except YamlBlockParseError as exc:
        raise RepoProfileLoadError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise RepoProfileLoadError("Profile YAML root must be a mapping.")
    return payload


def _normalize_profile_path(repo_profile_ref: str | Path, workspace_root: str | Path | None = None) -> Path:
    path = Path(repo_profile_ref)
    if path.is_absolute():
        return path
    if workspace_root is not None:
        return Path(workspace_root) / path
    return path


def _to_typed_read_entry(payload: dict[str, Any]) -> TypedReadEntry:
    return TypedReadEntry(
        read_target_kind=ReadTargetKind(payload["read_target_kind"]),
        doc_path=str(payload["doc_path"]),
        selector_type=SelectorType(payload["selector_type"]),
        section_selector=payload["section_selector"],
        why=str(payload["why"]),
    )


def _to_guided_classification(payload: dict[str, Any]) -> GuidedClassification:
    return GuidedClassification(
        token=str(payload["token"]),
        meaning=[str(item) for item in payload.get("meaning", [])],
        default_initial_phase_hint=payload.get("default_initial_phase_hint"),
        minimum_read_set_default=[_to_typed_read_entry(item) for item in payload.get("minimum_read_set_default", [])],
        minimum_read_set_extensions=[
            _to_typed_read_entry(item) for item in payload.get("minimum_read_set_extensions", [])
        ],
    )


def _to_initialization_doc_rule(payload: dict[str, Any]) -> InitializationDocRule:
    return InitializationDocRule(
        doc_path=str(payload["doc_path"]),
        required_sections=[str(item) for item in payload.get("required_sections", [])],
        min_level_two_sections=(
            int(payload["min_level_two_sections"])
            if payload.get("min_level_two_sections") is not None
            else None
        ),
        ignored_level_two_sections=[str(item) for item in payload.get("ignored_level_two_sections", [])],
    )


def _to_project_context(payload: dict[str, Any]) -> ProjectContext:
    source = payload.get("adoption_kind_source", {})
    initialization_requirements_payload = payload.get("initialization_requirements", {})
    initialization_requirements: dict[str, list[InitializationDocRule]] = {}
    for adoption_kind, item in initialization_requirements_payload.items():
        initialization_requirements[str(adoption_kind)] = [
            _to_initialization_doc_rule(rule_payload)
            for rule_payload in item.get("doc_rules", [])
        ]
    return ProjectContext(
        adoption_kind_source_kind=str(source.get("kind", "")),
        adoption_kind_resolution_order=[str(item) for item in source.get("resolution_order", [])],
        adoption_kind_allowed=[str(item) for item in payload.get("adoption_kind_allowed", [])],
        initialization_requirements=initialization_requirements,
    )


def _validate_project_context(project_context: ProjectContext) -> None:
    allowed = set(project_context.adoption_kind_allowed)
    configured = set(project_context.initialization_requirements)
    if allowed != configured:
        raise RepoProfileLoadError(
            "project_context.adoption_kind_allowed and "
            "project_context.initialization_requirements must have identical adoption-kind keys."
        )


def _to_checkpoint_supplement(payload: dict[str, Any]) -> CheckpointSupplement:
    return CheckpointSupplement(
        supplement_id=str(payload["supplement_id"]),
        applies_to_phase=str(payload["applies_to_phase"]),
        reads=[_to_typed_read_entry(item) for item in payload.get("reads", [])],
    )


def _to_verification_gate(payload: dict[str, Any]) -> VerificationGate:
    return VerificationGate(
        name=str(payload["name"]),
        command=str(payload["command"]),
        working_directory=str(payload["working_directory"]),
        success_criteria=str(payload["success_criteria"]),
        evidence=str(payload["evidence"]),
    )


def _to_conditional_verification_gate(payload: dict[str, Any]) -> ConditionalVerificationGate:
    return ConditionalVerificationGate(
        condition=str(payload["condition"]),
        gate=str(payload["gate"]),
    )


def _to_manual_verification_check(payload: dict[str, Any]) -> ManualVerificationCheck:
    return ManualVerificationCheck(
        check=str(payload["check"]),
        evidence=str(payload["evidence"]),
    )


def _to_verification_gate_template(payload: dict[str, Any]) -> VerificationGateTemplate:
    return VerificationGateTemplate(
        required_gates=[_to_verification_gate(item) for item in payload.get("required_gates", [])],
        conditional_gates=[
            _to_conditional_verification_gate(item) for item in payload.get("conditional_gates", [])
        ],
        manual_checks=[_to_manual_verification_check(item) for item in payload.get("manual_checks", [])],
    )


def load_repo_profile(repo_profile_ref: str | Path, workspace_root: str | Path | None = None) -> RepoProfile:
    """Load a repo profile from its pinned locator."""
    path = _normalize_profile_path(repo_profile_ref, workspace_root)
    try:
        profile_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepoProfileLoadError(f"Failed to read repo profile: {path}") from exc

    payload = _extract_profile_payload(profile_text)
    try:
        guided_classifications = {
            str(name): _to_guided_classification(item)
            for name, item in payload.get("guided_classifications", {}).items()
        }
        checkpoint_supplements = {
            str(name): _to_checkpoint_supplement(item)
            for name, item in payload.get("checkpoint_supplements", {}).items()
        }
        verification_gate_templates = {
            str(name): _to_verification_gate_template(item)
            for name, item in payload.get("verification_gate_templates", {}).items()
        }
        project_context = _to_project_context(payload["project_context"]) if "project_context" in payload else None
        if project_context is not None:
            _validate_project_context(project_context)
        return RepoProfile(
            profile_id=str(payload["profile_id"]),
            profile_version=int(payload["profile_version"]),
            provenance_refs=[str(item) for item in payload.get("provenance_refs", [])],
            project_context=project_context,
            guided_classifications=guided_classifications,
            known_issue_selector_mapping=[
                _to_typed_read_entry(item) for item in payload.get("known_issue_selector_mapping", [])
            ],
            checkpoint_supplements=checkpoint_supplements,
            verification_gate_templates=verification_gate_templates,
        )
    except KeyError as exc:
        raise RepoProfileLoadError(f"Missing required profile field: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise RepoProfileLoadError(f"Invalid repo profile payload: {exc}") from exc
