"""plan.md artifact helpers."""

from __future__ import annotations

from pathlib import Path

from harness.shared.contracts.profile import (
    ConditionalVerificationGate,
    ManualVerificationCheck,
    VerificationGate,
    VerificationGateTemplate,
)


PLAN_TEMPLATE = """# Plan: {task_name}

## References

## Goal

## Scope

## DoD

## Constraints

## Verification

## Risks / Pending

## Contract Notes
"""


def _normalize_path(plan_path: str | Path) -> Path:
    return Path(plan_path)


def _append_to_section(content: str, section_header: str, entry: str) -> str:
    marker = f"## {section_header}\n"
    if marker not in content:
        suffix = "\n" if not content.endswith("\n") else ""
        return f"{content}{suffix}{marker}\n{entry}\n"

    start = content.index(marker) + len(marker)
    remainder = content[start:]
    next_header_rel = remainder.find("\n## ")
    if next_header_rel == -1:
        section_body = remainder
        tail = ""
    else:
        section_body = remainder[:next_header_rel]
        tail = remainder[next_header_rel:]

    updated_body = section_body
    if updated_body and not updated_body.endswith("\n"):
        updated_body += "\n"
    updated_body += f"{entry}\n"
    return f"{content[:start]}{updated_body}{tail}"


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
        "- Required Gates:",
    ]
    lines.extend(_render_required_gates(resolved_template.required_gates))
    lines.append("- Conditional Gates:")
    lines.extend(_render_conditional_gates(resolved_template.conditional_gates))
    lines.append("- Manual Checks:")
    lines.extend(_render_manual_checks(resolved_template.manual_checks))
    return "\n".join(lines) + "\n"


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
    write_plan(path, _append_to_section(read_plan(path), "Contract Notes", entry))


def append_rewrite_required(plan_path: str | Path, rewrite_reason_code: str, basis_ref: str) -> None:
    """Append a rewrite-required entry to plan.md."""
    path = _normalize_path(plan_path)
    entry = f"- [rewrite-required] {rewrite_reason_code} [basis_ref={basis_ref}]"
    write_plan(path, _append_to_section(read_plan(path), "Contract Notes", entry))
