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
    VerificationToolchain,
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


def _optional_mapping(payload: dict[str, Any], key: str, field_name: str) -> dict[str, Any]:
    """Return a mapping default only when the key is absent; explicit null is invalid."""

    if key not in payload:
        return {}
    value = payload[key]
    if not isinstance(value, dict):
        raise RepoProfileLoadError(f"{field_name} must be a mapping when present.")
    return value


def _optional_list(payload: dict[str, Any], key: str, field_name: str) -> list[Any]:
    """Return a list default only when the key is absent; explicit null is invalid."""

    if key not in payload:
        return []
    value = payload[key]
    if not isinstance(value, list):
        raise RepoProfileLoadError(f"{field_name} must be a list when present.")
    return value


def _required_string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise RepoProfileLoadError(f"{field_name} must be a non-empty string.")
    if not value.strip():
        raise RepoProfileLoadError(f"{field_name} must be a non-empty string.")
    return value


def _required_string(payload: dict[str, Any], key: str, field_name: str) -> str:
    if key not in payload:
        raise RepoProfileLoadError(f"{field_name} is required.")
    return _required_string_value(payload[key], field_name)


def _required_int(payload: dict[str, Any], key: str, field_name: str) -> int:
    if key not in payload:
        raise RepoProfileLoadError(f"{field_name} is required.")
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RepoProfileLoadError(f"{field_name} must be an integer.")
    return value


def _optional_int(payload: dict[str, Any], key: str, field_name: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    return _required_int(payload, key, field_name)


def _optional_string_list(payload: dict[str, Any], key: str, field_name: str) -> list[str]:
    values = _optional_list(payload, key, field_name)
    return [
        _required_string_value(item, f"{field_name}[{index}]")
        for index, item in enumerate(values)
    ]


def _required_section_selector(payload: dict[str, Any], key: str, field_name: str) -> str | list[str]:
    if key not in payload:
        raise RepoProfileLoadError(f"{field_name} is required.")
    value = payload[key]
    if isinstance(value, str):
        return _required_string_value(value, field_name)
    if isinstance(value, list):
        if not value:
            raise RepoProfileLoadError(f"{field_name} list must not be empty.")
        return [
            _required_string_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise RepoProfileLoadError(f"{field_name} must be a non-empty string or list of strings.")


def _optional_string(payload: dict[str, Any], key: str, field_name: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise RepoProfileLoadError(f"{field_name} must be a string when present.")
    return value


def _string_keyed_items(payload: dict[str, Any], field_name: str) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, value in payload.items():
        items.append((_required_string_value(key, f"{field_name} key"), value))
    return items


def _required_mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Validate that an existing value is a mapping."""

    if not isinstance(value, dict):
        raise RepoProfileLoadError(f"{field_name} must be a mapping.")
    return value


def _read_target_kind(payload: dict[str, Any]) -> ReadTargetKind:
    value = _required_string(payload, "read_target_kind", "typed read read_target_kind")
    try:
        return ReadTargetKind(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ReadTargetKind)
        raise RepoProfileLoadError(f"typed read read_target_kind must be one of: {allowed}.") from exc


def _selector_type(payload: dict[str, Any]) -> SelectorType:
    value = _required_string(payload, "selector_type", "typed read selector_type")
    try:
        return SelectorType(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in SelectorType)
        raise RepoProfileLoadError(f"typed read selector_type must be one of: {allowed}.") from exc


def _normalize_profile_path(repo_profile_ref: str | Path, workspace_root: str | Path | None = None) -> Path:
    path = Path(repo_profile_ref)
    if path.is_absolute():
        return path
    if workspace_root is not None:
        return Path(workspace_root) / path
    return path


def _to_typed_read_entry(payload: dict[str, Any]) -> TypedReadEntry:
    payload = _required_mapping(payload, "typed read entry")
    return TypedReadEntry(
        read_target_kind=_read_target_kind(payload),
        doc_path=_required_string(payload, "doc_path", "typed read doc_path"),
        selector_type=_selector_type(payload),
        section_selector=_required_section_selector(payload, "section_selector", "typed read section_selector"),
        why=_required_string(payload, "why", "typed read why"),
    )


def _to_guided_classification(payload: dict[str, Any]) -> GuidedClassification:
    payload = _required_mapping(payload, "guided classification")
    return GuidedClassification(
        token=_required_string(payload, "token", "guided classification token"),
        meaning=_optional_string_list(payload, "meaning", "guided classification meaning"),
        default_initial_phase_hint=_optional_string(
            payload,
            "default_initial_phase_hint",
            "guided classification default_initial_phase_hint",
        ),
        minimum_read_set_default=[
            _to_typed_read_entry(item)
            for item in _optional_list(
                payload,
                "minimum_read_set_default",
                "guided classification minimum_read_set_default",
            )
        ],
        minimum_read_set_extensions=[
            _to_typed_read_entry(item)
            for item in _optional_list(
                payload,
                "minimum_read_set_extensions",
                "guided classification minimum_read_set_extensions",
            )
        ],
    )


def _to_initialization_doc_rule(payload: dict[str, Any]) -> InitializationDocRule:
    payload = _required_mapping(payload, "initialization doc rule")
    return InitializationDocRule(
        doc_path=_required_string(payload, "doc_path", "initialization doc rule doc_path"),
        required_sections=_optional_string_list(
            payload,
            "required_sections",
            "initialization doc rule required_sections",
        ),
        min_level_two_sections=_optional_int(
            payload,
            "min_level_two_sections",
            "initialization doc rule min_level_two_sections",
        ),
        ignored_level_two_sections=_optional_string_list(
            payload,
            "ignored_level_two_sections",
            "initialization doc rule ignored_level_two_sections",
        ),
    )


def _to_project_context(payload: dict[str, Any]) -> ProjectContext:
    payload = _required_mapping(payload, "project_context")
    source = _optional_mapping(payload, "adoption_kind_source", "project_context.adoption_kind_source")
    initialization_requirements_payload = _optional_mapping(
        payload,
        "initialization_requirements",
        "project_context.initialization_requirements",
    )
    initialization_requirements: dict[str, list[InitializationDocRule]] = {}
    for adoption_kind, item in _string_keyed_items(
        initialization_requirements_payload,
        "project_context.initialization_requirements",
    ):
        if not isinstance(item, dict):
            raise RepoProfileLoadError("project_context.initialization_requirements entries must be mappings.")
        initialization_requirements[adoption_kind] = [
            _to_initialization_doc_rule(rule_payload)
            for rule_payload in _optional_list(
                item,
                "doc_rules",
                "project_context.initialization_requirements doc_rules",
            )
        ]
    return ProjectContext(
        adoption_kind_source_kind=_required_string(
            source,
            "kind",
            "project_context.adoption_kind_source.kind",
        ),
        adoption_kind_resolution_order=_optional_string_list(
            source,
            "resolution_order",
            "project_context.adoption_kind_source.resolution_order",
        ),
        adoption_kind_allowed=_optional_string_list(
            payload,
            "adoption_kind_allowed",
            "project_context.adoption_kind_allowed",
        ),
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
    payload = _required_mapping(payload, "checkpoint supplement")
    return CheckpointSupplement(
        supplement_id=_required_string(payload, "supplement_id", "checkpoint supplement supplement_id"),
        applies_to_phase=_required_string(payload, "applies_to_phase", "checkpoint supplement applies_to_phase"),
        reads=[
            _to_typed_read_entry(item)
            for item in _optional_list(payload, "reads", "checkpoint supplement reads")
        ],
    )


def _to_verification_gate(payload: dict[str, Any]) -> VerificationGate:
    payload = _required_mapping(payload, "verification gate")
    return VerificationGate(
        name=_required_string(payload, "name", "verification gate name"),
        command=_required_string(payload, "command", "verification gate command"),
        working_directory=_required_string(payload, "working_directory", "verification gate working_directory"),
        success_criteria=_required_string(payload, "success_criteria", "verification gate success_criteria"),
        evidence=_required_string(payload, "evidence", "verification gate evidence"),
    )


def _to_conditional_verification_gate(payload: dict[str, Any]) -> ConditionalVerificationGate:
    payload = _required_mapping(payload, "conditional verification gate")
    return ConditionalVerificationGate(
        condition=_required_string(payload, "condition", "conditional verification gate condition"),
        gate=_required_string(payload, "gate", "conditional verification gate gate"),
    )


def _to_manual_verification_check(payload: dict[str, Any]) -> ManualVerificationCheck:
    payload = _required_mapping(payload, "manual verification check")
    return ManualVerificationCheck(
        check=_required_string(payload, "check", "manual verification check check"),
        evidence=_required_string(payload, "evidence", "manual verification check evidence"),
    )


def _to_verification_gate_template(payload: dict[str, Any]) -> VerificationGateTemplate:
    payload = _required_mapping(payload, "verification gate template")
    return VerificationGateTemplate(
        required_gates=[
            _to_verification_gate(item)
            for item in _optional_list(payload, "required_gates", "verification gate template required_gates")
        ],
        conditional_gates=[
            _to_conditional_verification_gate(item)
            for item in _optional_list(payload, "conditional_gates", "verification gate template conditional_gates")
        ],
        manual_checks=[
            _to_manual_verification_check(item)
            for item in _optional_list(payload, "manual_checks", "verification gate template manual_checks")
        ],
    )


def _strict_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise RepoProfileLoadError(f"{field_name} must be a boolean true/false value.")


def _to_verification_toolchain(payload: dict[str, Any]) -> VerificationToolchain:
    payload = _required_mapping(payload, "verification_toolchain")
    if "configured" not in payload:
        raise RepoProfileLoadError("verification_toolchain.configured is required.")
    configured = _strict_bool(payload["configured"], "verification_toolchain.configured")
    if not configured:
        return VerificationToolchain(
            configured=False,
            build_tool="",
            test_tool=None,
            working_directory=".",
        )
    return VerificationToolchain(
        configured=configured,
        build_tool=_required_string(payload, "build_tool", "verification_toolchain.build_tool"),
        test_tool=_optional_string(payload, "test_tool", "verification_toolchain.test_tool"),
        working_directory=(
            _required_string(payload, "working_directory", "verification_toolchain.working_directory")
            if "working_directory" in payload
            else "."
        ),
        required_gates=[
            _to_verification_gate(item)
            for item in _optional_list(payload, "required_gates", "verification_toolchain.required_gates")
        ],
        conditional_gates=[
            _to_conditional_verification_gate(item)
            for item in _optional_list(payload, "conditional_gates", "verification_toolchain.conditional_gates")
        ],
        manual_checks=[
            _to_manual_verification_check(item)
            for item in _optional_list(payload, "manual_checks", "verification_toolchain.manual_checks")
        ],
        notes=_optional_string_list(payload, "notes", "verification_toolchain.notes"),
    )


def _validate_verification_toolchain(toolchain: VerificationToolchain | None) -> None:
    if toolchain is None or not toolchain.configured:
        return
    if not toolchain.required_gates:
        raise RepoProfileLoadError("verification_toolchain.configured=true requires at least one required gate.")
    for index, gate in enumerate(toolchain.required_gates, start=1):
        required_fields = {
            "name": gate.name,
            "command": gate.command,
            "working_directory": gate.working_directory,
            "success_criteria": gate.success_criteria,
            "evidence": gate.evidence,
        }
        for field_name, value in required_fields.items():
            if not value.strip():
                raise RepoProfileLoadError(
                    "verification_toolchain.configured=true requires "
                    f"required_gates[{index}].{field_name} to be non-empty."
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
        guided_classifications_payload = _optional_mapping(
            payload,
            "guided_classifications",
            "guided_classifications",
        )
        checkpoint_supplements_payload = _optional_mapping(
            payload,
            "checkpoint_supplements",
            "checkpoint_supplements",
        )
        verification_gate_templates_payload = _optional_mapping(
            payload,
            "verification_gate_templates",
            "verification_gate_templates",
        )
        guided_classifications = {
            name: _to_guided_classification(item)
            for name, item in _string_keyed_items(guided_classifications_payload, "guided_classifications")
        }
        checkpoint_supplements = {
            name: _to_checkpoint_supplement(item)
            for name, item in _string_keyed_items(checkpoint_supplements_payload, "checkpoint_supplements")
        }
        verification_gate_templates = {
            name: _to_verification_gate_template(item)
            for name, item in _string_keyed_items(
                verification_gate_templates_payload,
                "verification_gate_templates",
            )
        }
        verification_toolchain = (
            _to_verification_toolchain(payload["verification_toolchain"])
            if "verification_toolchain" in payload
            else None
        )
        project_context = (
            _to_project_context(payload["project_context"])
            if "project_context" in payload
            else None
        )
        if project_context is not None:
            _validate_project_context(project_context)
        _validate_verification_toolchain(verification_toolchain)
        return RepoProfile(
            profile_id=_required_string(payload, "profile_id", "profile_id"),
            profile_version=_required_int(payload, "profile_version", "profile_version"),
            provenance_refs=_optional_string_list(payload, "provenance_refs", "provenance_refs"),
            project_context=project_context,
            guided_classifications=guided_classifications,
            known_issue_selector_mapping=[
                _to_typed_read_entry(item)
                for item in _optional_list(
                    payload,
                    "known_issue_selector_mapping",
                    "known_issue_selector_mapping",
                )
            ],
            checkpoint_supplements=checkpoint_supplements,
            verification_gate_templates=verification_gate_templates,
            verification_toolchain=verification_toolchain,
        )
    except KeyError as exc:
        raise RepoProfileLoadError(f"Missing required profile field: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise RepoProfileLoadError(f"Invalid repo profile payload: {exc}") from exc
