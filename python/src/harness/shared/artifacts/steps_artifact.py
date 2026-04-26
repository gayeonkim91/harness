"""steps.md artifact helpers."""

from __future__ import annotations

from pathlib import Path

from harness.shared.contracts.actions import CurrentStepRefSnapshot


STEPS_TEMPLATE = """# Steps

## Steps

## Working Notes
"""


def _normalize_path(steps_path: str | Path) -> Path:
    return Path(steps_path)


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


def scaffold_steps(task_root: str | Path) -> Path:
    """Create the initial steps.md scaffold for a task."""
    root = Path(task_root)
    root.mkdir(parents=True, exist_ok=True)
    steps_path = root / "steps.md"
    if not steps_path.exists():
        steps_path.write_text(STEPS_TEMPLATE, encoding="utf-8")
    return steps_path


def read_steps(steps_path: str | Path) -> str:
    """Read the raw steps artifact."""
    return _normalize_path(steps_path).read_text(encoding="utf-8")


def write_steps(steps_path: str | Path, content: str) -> None:
    """Write the raw steps artifact."""
    path = _normalize_path(steps_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_working_note(
    steps_path: str | Path,
    snapshot: CurrentStepRefSnapshot,
    note_text: str,
    basis_refs: list[str],
) -> None:
    """Append a working note entry to steps.md."""
    step_ref = snapshot.step_ref
    entry = f"- [step_ref={step_ref}] {note_text}"
    if basis_refs:
        entry += f" [basis_refs={', '.join(basis_refs)}]"
    path = _normalize_path(steps_path)
    write_steps(path, _append_to_section(read_steps(path), "Working Notes", entry))


def append_rewrite_required(
    steps_path: str | Path,
    snapshot: CurrentStepRefSnapshot,
    rewrite_reason_code: str,
    basis_ref: str,
) -> None:
    """Append a rewrite-required entry to steps.md."""
    step_ref = snapshot.step_ref
    entry = f"- [step_ref={step_ref}] rewrite-required:{rewrite_reason_code} [basis_ref={basis_ref}]"
    path = _normalize_path(steps_path)
    write_steps(path, _append_to_section(read_steps(path), "Working Notes", entry))
