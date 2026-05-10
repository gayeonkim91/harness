"""plan.md artifact helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.shared.contracts.profile import (
    ConditionalVerificationGate,
    ManualVerificationCheck,
    VerificationGate,
    VerificationGateTemplate,
    VerificationToolchain,
)
from harness.shared.contracts.state import (
    CurrentPhase,
    HarnessCounters,
    HarnessState,
    ReviewOutcome,
    SessionState,
    WorkflowMode,
)
from harness.shared.core.markdown_section_index import Section, parse_index


PLAN_TEMPLATE = """# Plan: {task_name}

## References

## Goal

## Scope

## DoD

## Constraints

## Verification

## Risks / Pending

## Contract Notes

## Steps

## Working Notes
"""

CURRENT_STATE_SECTION_TITLE = "Current State"
CURRENT_STATE_SECTION_ALIASES = {
    "current state",
    "현재 상태 (current state)",
}
_NONE_TEXT_VALUES = {"", "null", "none", "n/a", "해당 없음"}
SECTION_HEADER_ALIASES = {
    "Contract Notes": {"contract notes", "계약 메모 (contract notes)", "계약 메모(contract notes)"},
    "Working Notes": {"working notes", "작업 노트 (working notes)", "작업 노트(working notes)"},
}


class PlanCurrentStateError(ValueError):
    """Raised when a present Current State section cannot be parsed."""


@dataclass(frozen=True, slots=True)
class PlanCurrentState:
    """Machine-readable subset of workflow state stored in plan.md."""

    schema_version: int | None
    session_state: SessionState | None
    workflow_mode: WorkflowMode | None
    current_phase: CurrentPhase | None
    repo_profile_ref: str | None
    workspace_baseline_ref: str | None
    current_step_ref: str | None
    latest_checkpoint_ref: str | None
    latest_verification_ref: str | None
    latest_review_ref: str | None
    pending_approval_for: str | None
    review_outcome: ReviewOutcome | None
    closure_authorized: bool | None
    counters_rework_count: int | None
    counters_rewrite_count: int | None
    counters_rollback_count: int | None
    blocked_transition: str | None
    blocked_reason_ref: str | None
    stop_condition_ref: str | None
    approvals_granted: list[int] | None
    last_updated: str | None
    present_fields: frozenset[str] = field(default_factory=frozenset)


def _normalize_path(plan_path: str | Path) -> Path:
    return Path(plan_path)


def _normalize_section_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _is_current_state_section(section: Section) -> bool:
    return section.level == 2 and _normalize_section_title(section.title) in CURRENT_STATE_SECTION_ALIASES


def _find_current_state_section(content: str) -> Section | None:
    return next((section for section in parse_index(content) if _is_current_state_section(section)), None)


def _extract_section_body(content: str, section: Section) -> list[str]:
    lines = content.splitlines()
    return lines[section.start_line : section.end_line]


def _parse_state_lines(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        normalized_key = key.strip()
        if normalized_key:
            values[normalized_key] = value.strip()
    return values


def _parse_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.lower() in _NONE_TEXT_VALUES:
        return None
    return stripped


def _parse_int(value: str | None, field_name: str) -> int:
    parsed = _parse_optional_text(value)
    if parsed is None:
        raise PlanCurrentStateError(f"Current State field {field_name!r} is required.")
    try:
        return int(parsed)
    except ValueError as exc:
        raise PlanCurrentStateError(f"Current State field {field_name!r} must be an integer.") from exc


def _parse_optional_int(value: str | None, field_name: str) -> int | None:
    if value is None:
        return None
    parsed = _parse_optional_text(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except ValueError as exc:
        raise PlanCurrentStateError(f"Current State field {field_name!r} must be an integer.") from exc


def _parse_optional_bool(value: str | None, field_name: str) -> bool | None:
    if value is None:
        return None
    parsed = _parse_optional_text(value)
    if parsed is None:
        return None
    lowered = parsed.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise PlanCurrentStateError(f"Current State field {field_name!r} must be true or false.")


def _parse_int_list(value: str | None, field_name: str) -> list[int]:
    parsed = _parse_optional_text(value)
    if parsed is None:
        return []
    if not parsed.startswith("[") or not parsed.endswith("]"):
        raise PlanCurrentStateError(f"Current State field {field_name!r} must be a bracketed integer list.")
    inner = parsed[1:-1].strip()
    if not inner:
        return []
    try:
        return [int(item.strip()) for item in inner.split(",")]
    except ValueError as exc:
        raise PlanCurrentStateError(f"Current State field {field_name!r} must contain only integers.") from exc


def _parse_optional_int_list(value: str | None, field_name: str) -> list[int] | None:
    if value is None:
        return None
    parsed = _parse_optional_text(value)
    if parsed is None:
        return None
    return _parse_int_list(parsed, field_name)


def _parse_optional_enum(enum_cls: type, value: str | None, field_name: str) -> Any:
    if value is None:
        return None
    parsed = _parse_optional_text(value)
    if parsed is None:
        return None
    try:
        return enum_cls(parsed)
    except ValueError as exc:
        raise PlanCurrentStateError(f"Current State field {field_name!r} has unsupported value {parsed!r}.") from exc


def parse_plan_current_state(content: str) -> PlanCurrentState | None:
    """Parse the plan.md Current State section when present.

    A missing section returns ``None`` for compatibility with pre-PR5 tasks.
    A present but empty section also returns ``None`` so scaffold-only drafts can
    be initialized by the state writer.
    """

    section = _find_current_state_section(content)
    if section is None:
        return None

    values = _parse_state_lines(_extract_section_body(content, section))
    if not values:
        return None

    return PlanCurrentState(
        schema_version=_parse_optional_int(values.get("schema_version"), "schema_version"),
        session_state=_parse_optional_enum(SessionState, values.get("session_state"), "session_state"),
        workflow_mode=_parse_optional_enum(WorkflowMode, values.get("workflow_mode"), "workflow_mode"),
        current_phase=_parse_optional_enum(CurrentPhase, values.get("current_phase"), "current_phase"),
        repo_profile_ref=_parse_optional_text(values.get("repo_profile_ref")),
        workspace_baseline_ref=_parse_optional_text(values.get("workspace_baseline_ref")),
        current_step_ref=_parse_optional_text(values.get("current_step_ref")),
        latest_checkpoint_ref=_parse_optional_text(values.get("latest_checkpoint_ref")),
        latest_verification_ref=_parse_optional_text(values.get("latest_verification_ref")),
        latest_review_ref=_parse_optional_text(values.get("latest_review_ref")),
        pending_approval_for=_parse_optional_text(values.get("pending_approval_for")),
        review_outcome=_parse_optional_enum(ReviewOutcome, values.get("review_outcome"), "review_outcome"),
        closure_authorized=_parse_optional_bool(values.get("closure_authorized"), "closure_authorized"),
        counters_rework_count=_parse_optional_int(values.get("counters.rework_count"), "counters.rework_count"),
        counters_rewrite_count=_parse_optional_int(values.get("counters.rewrite_count"), "counters.rewrite_count"),
        counters_rollback_count=_parse_optional_int(values.get("counters.rollback_count"), "counters.rollback_count"),
        blocked_transition=_parse_optional_text(values.get("blocked_transition")),
        blocked_reason_ref=_parse_optional_text(values.get("blocked_reason_ref")),
        stop_condition_ref=_parse_optional_text(values.get("stop_condition_ref")),
        approvals_granted=_parse_optional_int_list(values.get("approvals_granted"), "approvals_granted"),
        last_updated=_parse_optional_text(values.get("last_updated")),
        present_fields=frozenset(values),
    )


def read_plan_current_state(plan_path: str | Path) -> PlanCurrentState | None:
    """Read and parse plan.md Current State."""
    return parse_plan_current_state(read_plan(plan_path))


def plan_current_state_from_harness_state(state: HarnessState) -> PlanCurrentState:
    """Project persisted HarnessState into plan.md Current State."""
    return PlanCurrentState(
        schema_version=state.schema_version,
        session_state=state.session_state,
        workflow_mode=state.workflow_mode,
        current_phase=state.current_phase,
        repo_profile_ref=state.repo_profile_ref,
        workspace_baseline_ref=state.workspace_baseline_ref,
        current_step_ref=state.current_step_ref,
        latest_checkpoint_ref=state.latest_checkpoint_ref,
        latest_verification_ref=state.latest_verification_ref,
        latest_review_ref=state.latest_review_ref,
        pending_approval_for=state.pending_approval_for,
        review_outcome=state.review_outcome,
        closure_authorized=state.closure_authorized,
        counters_rework_count=state.counters.rework_count,
        counters_rewrite_count=state.counters.rewrite_count,
        counters_rollback_count=state.counters.rollback_count,
        blocked_transition=state.blocked_transition,
        blocked_reason_ref=state.blocked_reason_ref,
        stop_condition_ref=state.stop_condition_ref,
        approvals_granted=list(state.approvals_granted),
        last_updated=state.last_updated,
        present_fields=frozenset(
            {
                "schema_version",
                "session_state",
                "workflow_mode",
                "current_phase",
                "repo_profile_ref",
                "workspace_baseline_ref",
                "current_step_ref",
                "latest_checkpoint_ref",
                "latest_verification_ref",
                "latest_review_ref",
                "pending_approval_for",
                "review_outcome",
                "closure_authorized",
                "counters.rework_count",
                "counters.rewrite_count",
                "counters.rollback_count",
                "blocked_transition",
                "blocked_reason_ref",
                "stop_condition_ref",
                "approvals_granted",
                "last_updated",
            }
        ),
    )


def _prefer_present_optional(present: frozenset[str], field_name: str, planned: Any, existing: Any) -> Any:
    if field_name in present:
        return planned
    return existing


def _prefer_present_required(present: frozenset[str], field_name: str, planned: Any, existing: Any) -> Any:
    if field_name in present and planned is not None:
        return planned
    return existing


def apply_plan_current_state_to_harness_state(state: HarnessState, current: PlanCurrentState) -> HarnessState:
    """Return a HarnessState reconciled with plan.md as the priority source."""
    present = current.present_fields
    return HarnessState(
        schema_version=_prefer_present_required(
            present,
            "schema_version",
            current.schema_version,
            state.schema_version,
        ),
        session_state=_prefer_present_required(present, "session_state", current.session_state, state.session_state),
        workflow_mode=_prefer_present_required(present, "workflow_mode", current.workflow_mode, state.workflow_mode),
        current_phase=_prefer_present_required(present, "current_phase", current.current_phase, state.current_phase),
        repo_profile_ref=_prefer_present_optional(
            present,
            "repo_profile_ref",
            current.repo_profile_ref,
            state.repo_profile_ref,
        ),
        workspace_baseline_ref=_prefer_present_optional(
            present,
            "workspace_baseline_ref",
            current.workspace_baseline_ref,
            state.workspace_baseline_ref,
        ),
        current_step_ref=_prefer_present_optional(
            present,
            "current_step_ref",
            current.current_step_ref,
            state.current_step_ref,
        ),
        latest_checkpoint_ref=_prefer_present_optional(
            present,
            "latest_checkpoint_ref",
            current.latest_checkpoint_ref,
            state.latest_checkpoint_ref,
        ),
        latest_verification_ref=_prefer_present_optional(
            present,
            "latest_verification_ref",
            current.latest_verification_ref,
            state.latest_verification_ref,
        ),
        latest_review_ref=_prefer_present_optional(
            present,
            "latest_review_ref",
            current.latest_review_ref,
            state.latest_review_ref,
        ),
        pending_approval_for=_prefer_present_optional(
            present,
            "pending_approval_for",
            current.pending_approval_for,
            state.pending_approval_for,
        ),
        review_outcome=_prefer_present_optional(
            present,
            "review_outcome",
            current.review_outcome,
            state.review_outcome,
        ),
        closure_authorized=_prefer_present_required(
            present,
            "closure_authorized",
            current.closure_authorized,
            state.closure_authorized,
        ),
        counters=HarnessCounters(
            rework_count=_prefer_present_required(
                present,
                "counters.rework_count",
                current.counters_rework_count,
                state.counters.rework_count,
            ),
            rewrite_count=_prefer_present_required(
                present,
                "counters.rewrite_count",
                current.counters_rewrite_count,
                state.counters.rewrite_count,
            ),
            rollback_count=_prefer_present_required(
                present,
                "counters.rollback_count",
                current.counters_rollback_count,
                state.counters.rollback_count,
            ),
        ),
        blocked_transition=_prefer_present_optional(
            present,
            "blocked_transition",
            current.blocked_transition,
            state.blocked_transition,
        ),
        blocked_reason_ref=_prefer_present_optional(
            present,
            "blocked_reason_ref",
            current.blocked_reason_ref,
            state.blocked_reason_ref,
        ),
        stop_condition_ref=_prefer_present_optional(
            present,
            "stop_condition_ref",
            current.stop_condition_ref,
            state.stop_condition_ref,
        ),
        last_updated=_prefer_present_required(present, "last_updated", current.last_updated, state.last_updated),
        approvals_granted=list(current.approvals_granted)
        if "approvals_granted" in present and current.approvals_granted is not None
        else list(state.approvals_granted),
        adapter_meta=state.adapter_meta,
    )


def _render_optional(value: object | None) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _render_int_list(values: list[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"


def render_plan_current_state(current: PlanCurrentState) -> str:
    """Render a canonical Current State section."""
    closure_authorized = str(current.closure_authorized).lower() if current.closure_authorized is not None else None
    lines = [
        f"## {CURRENT_STATE_SECTION_TITLE}",
        f"- schema_version: {_render_optional(current.schema_version)}",
        f"- session_state: {_render_optional(current.session_state)}",
        f"- workflow_mode: {_render_optional(current.workflow_mode)}",
        f"- current_phase: {_render_optional(current.current_phase)}",
        f"- repo_profile_ref: {_render_optional(current.repo_profile_ref)}",
        f"- workspace_baseline_ref: {_render_optional(current.workspace_baseline_ref)}",
        f"- current_step_ref: {_render_optional(current.current_step_ref)}",
        f"- latest_checkpoint_ref: {_render_optional(current.latest_checkpoint_ref)}",
        f"- latest_verification_ref: {_render_optional(current.latest_verification_ref)}",
        f"- latest_review_ref: {_render_optional(current.latest_review_ref)}",
        f"- pending_approval_for: {_render_optional(current.pending_approval_for)}",
        f"- review_outcome: {_render_optional(current.review_outcome)}",
        f"- closure_authorized: {_render_optional(closure_authorized)}",
        f"- counters.rework_count: {_render_optional(current.counters_rework_count)}",
        f"- counters.rewrite_count: {_render_optional(current.counters_rewrite_count)}",
        f"- counters.rollback_count: {_render_optional(current.counters_rollback_count)}",
        f"- blocked_transition: {_render_optional(current.blocked_transition)}",
        f"- blocked_reason_ref: {_render_optional(current.blocked_reason_ref)}",
        f"- stop_condition_ref: {_render_optional(current.stop_condition_ref)}",
        f"- approvals_granted: {_render_int_list(current.approvals_granted or [])}",
        f"- last_updated: {_render_optional(current.last_updated)}",
    ]
    return "\n".join(lines) + "\n\n"


def _replace_current_state_section(content: str, rendered: str, section: Section) -> str:
    lines = content.splitlines()
    replacement = rendered.splitlines()
    updated = lines[: section.start_line - 1] + replacement + lines[section.end_line :]
    return "\n".join(updated) + "\n"


def _insert_current_state_section(content: str, rendered: str) -> str:
    lines = content.splitlines()
    replacement = rendered.splitlines()
    if not lines:
        return rendered

    index = parse_index(content)
    first_h1 = next((section for section in index if section.level == 1), None)
    insert_at = first_h1.start_line if first_h1 is not None else 0
    prefix = lines[:insert_at]
    suffix = lines[insert_at:]
    updated = prefix + [""] + replacement
    if suffix:
        if updated[-1] == "" and suffix[0] == "":
            suffix = suffix[1:]
        elif updated[-1] != "" and suffix[0] != "":
            updated += [""]
        updated += suffix
    return "\n".join(updated) + "\n"


def write_plan_current_state(plan_path: str | Path, current: PlanCurrentState) -> None:
    """Upsert the plan.md Current State section without rewriting other sections."""
    path = _normalize_path(plan_path)
    content = read_plan(path) if path.exists() else ""
    rendered = render_plan_current_state(current)
    section = _find_current_state_section(content)
    if section is None:
        write_plan(path, _insert_current_state_section(content, rendered))
        return
    write_plan(path, _replace_current_state_section(content, rendered, section))


def _find_section_line_range(content: str, section_header: str) -> tuple[int, int] | None:
    aliases = SECTION_HEADER_ALIASES.get(section_header, {_normalize_section_title(section_header)})
    lines = content.splitlines()
    in_fence = False
    start_index = None
    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if start_index is None:
            if line.startswith("## ") and _normalize_section_title(line[3:]) in aliases:
                start_index = index
            continue
        if line.startswith("## "):
            return start_index, index
    if start_index is None:
        return None
    return start_index, len(lines)


def append_to_section(content: str, section_header: str, entry: str) -> str:
    """Append an entry to a level-two section, honoring known section aliases."""

    section_range = _find_section_line_range(content, section_header)
    if section_range is None:
        suffix = "\n" if not content.endswith("\n") else ""
        return f"{content}{suffix}## {section_header}\n\n{entry}\n"

    _, end_index = section_range
    lines = content.splitlines()
    if entry in lines[section_range[0] + 1 : end_index]:
        return content
    updated = lines[:end_index] + [entry] + lines[end_index:]
    return "\n".join(updated) + "\n"


def scaffold_plan(task_root: str | Path, task_name: str) -> Path:
    """Create the initial plan.md scaffold for a task."""
    return scaffold_plan_with_verification(task_root, task_name, None)


def scaffold_plan_with_verification(
    task_root: str | Path,
    task_name: str,
    verification_contract: str | None,
) -> Path:
    """Create the initial plan.md scaffold for a task with an optional verification contract."""
    root = Path(task_root)
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "plan.md"
    if not plan_path.exists():
        content = PLAN_TEMPLATE.format(task_name=task_name)
        if verification_contract:
            content = content.replace("## Verification\n", f"## Verification\n{verification_contract.rstrip()}\n")
        plan_path.write_text(content, encoding="utf-8")
    return plan_path


def render_initial_verification_contract(
    *,
    adoption_kind: str | None,
    task_classification: str,
    template: VerificationGateTemplate | None,
    gate_source: str,
    toolchain: VerificationToolchain | None = None,
) -> str:
    """Render the /wf-start initialized task-local verification contract."""
    resolved_adoption_kind = adoption_kind or "unknown"
    resolved_template = template or _fallback_verification_template(resolved_adoption_kind)
    lines = [
        "- Gate Policy:",
        "  - initialized_by: wf-start",
        f"  - adoption_kind: {resolved_adoption_kind}",
        f"  - task_classification: {task_classification}",
        f"  - gate_source: {gate_source}",
        "  - last_updated_by: wf-start",
        "  - change_reason: initial verification contract",
    ]
    if toolchain is not None and toolchain.configured:
        lines.extend(
            [
                "- Toolchain Policy:",
                f"  - build_tool: {toolchain.build_tool}",
                f"  - test_tool: {_render_optional_tool(toolchain.test_tool)}",
                f"  - default_working_directory: {toolchain.working_directory}",
            ]
        )
        if toolchain.notes:
            lines.append("  - notes:")
            for note in toolchain.notes:
                note_lines = note.splitlines() or [""]
                lines.append(f"    - {note_lines[0]}")
                lines.extend(f"      {continuation}" for continuation in note_lines[1:])
    lines.append("- Required Gates:")
    lines.extend(_render_required_gates(resolved_template.required_gates))
    lines.append("- Conditional Gates:")
    lines.extend(_render_conditional_gates(resolved_template.conditional_gates))
    lines.append("- Manual Checks:")
    lines.extend(_render_manual_checks(resolved_template.manual_checks))
    return "\n".join(lines) + "\n"


def _render_optional_tool(value: str | None) -> str:
    if value is None or not value.strip():
        return "none"
    return value


def verification_template_from_toolchain(toolchain: VerificationToolchain) -> VerificationGateTemplate:
    """Project a configured repo-level toolchain into a task-local gate template.

    Toolchain notes are rendered separately in the Toolchain Policy block.
    """

    return VerificationGateTemplate(
        required_gates=list(toolchain.required_gates),
        conditional_gates=list(toolchain.conditional_gates),
        manual_checks=list(toolchain.manual_checks),
    )


def _render_required_gates(gates: list[VerificationGate]) -> list[str]:
    if not gates:
        return ["  - none"]
    lines: list[str] = []
    for gate in gates:
        lines.extend(
            [
                f"  - name: {gate.name}",
                f"    command: {gate.command}",
                f"    working_directory: {gate.working_directory}",
                f"    success_criteria: {gate.success_criteria}",
                f"    evidence: {gate.evidence}",
            ]
        )
    return lines


def _render_conditional_gates(gates: list[ConditionalVerificationGate]) -> list[str]:
    if not gates:
        return ["  - none"]
    lines: list[str] = []
    for gate in gates:
        lines.extend(
            [
                f"  - condition: {gate.condition}",
                f"    gate: {gate.gate}",
            ]
        )
    return lines


def _render_manual_checks(checks: list[ManualVerificationCheck]) -> list[str]:
    if not checks:
        return ["  - none"]
    lines: list[str] = []
    for check in checks:
        lines.extend(
            [
                f"  - check: {check.check}",
                f"    evidence: {check.evidence}",
            ]
        )
    return lines


def _fallback_verification_template(adoption_kind: str) -> VerificationGateTemplate:
    if adoption_kind == "greenfield":
        return VerificationGateTemplate(
            required_gates=[
                VerificationGate(
                    name="Task-specific smoke or regression gate",
                    command="<define before verification>",
                    working_directory="<repo root or task-defined workdir>",
                    success_criteria="Command exits 0 or documented manual check passes.",
                    evidence="Command summary, report path, or manual check notes in verification.md.",
                )
            ],
            conditional_gates=[
                ConditionalVerificationGate(
                    condition="Public behavior, API, or integration boundary is introduced.",
                    gate="Add an integration or scenario check before /wf-verify.",
                )
            ],
            manual_checks=[
                ManualVerificationCheck(
                    check="Confirm the new scaffold or behavior matches the intended task contract.",
                    evidence="Reviewed file list, entry points, and representative scenario notes.",
                )
            ],
        )
    if adoption_kind.startswith("legacy-"):
        return VerificationGateTemplate(
            required_gates=[
                VerificationGate(
                    name="Existing regression gate for touched area",
                    command="<repo-defined regression command>",
                    working_directory="<repo-defined workdir>",
                    success_criteria="No new failures relative to the task baseline.",
                    evidence="Command summary, structured report, or failure analysis in verification.md.",
                )
            ],
            conditional_gates=[
                ConditionalVerificationGate(
                    condition="Shared module, persistence, external integration, or entry flow changes.",
                    gate="Run the narrowest available downstream or integration check for that boundary.",
                )
            ],
            manual_checks=[
                ManualVerificationCheck(
                    check="Compare changed behavior with existing documented behavior and known issues.",
                    evidence="References to relevant project docs, diff summary, and unresolved risk notes.",
                )
            ],
        )
    return VerificationGateTemplate(
        required_gates=[
            VerificationGate(
                name="Task-appropriate verification gate",
                command="<define before verification>",
                working_directory="<define before verification>",
                success_criteria="The selected check proves the task-specific DoD without hiding failures.",
                evidence="Verification command summary, report path, or manual review notes.",
            )
        ],
        conditional_gates=[
            ConditionalVerificationGate(
                condition="Automated verification is unavailable or not meaningful.",
                gate="Define an explicit manual check with expected observation and evidence.",
            )
        ],
        manual_checks=[],
    )


def read_plan(plan_path: str | Path) -> str:
    """Read the raw plan artifact."""
    return _normalize_path(plan_path).read_text(encoding="utf-8")


def write_plan(plan_path: str | Path, content: str) -> None:
    """Write the raw plan artifact."""
    path = _normalize_path(plan_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_contract_note(plan_path: str | Path, note_text: str, basis_refs: list[str]) -> None:
    """Append a contract note entry to plan.md."""
    path = _normalize_path(plan_path)
    entry = f"- [contract-note] {note_text}"
    if basis_refs:
        entry += f" [basis_refs={', '.join(basis_refs)}]"
    write_plan(path, append_to_section(read_plan(path), "Contract Notes", entry))


def append_rewrite_required(plan_path: str | Path, rewrite_reason_code: str, basis_ref: str) -> None:
    """Append a rewrite-required entry to plan.md."""
    path = _normalize_path(plan_path)
    entry = f"- [rewrite-required] {rewrite_reason_code} [basis_ref={basis_ref}]"
    write_plan(path, append_to_section(read_plan(path), "Contract Notes", entry))
