"""Phase specification loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from harness.shared.core.yaml_block import YamlBlockParseError, parse_yaml_block


PHASE_DOC_FILENAMES = {
    "pre-planning": "pre-planning.md",
    "plan": "plan.md",
    "step": "step.md",
    "implementation": "implementation.md",
    "verification": "verification.md",
    "review": "review.md",
}

WORKSPACE_ROOT_MARKERS = (
    "contracts/repo_profile.md",
    "phases",
    ".git",
)

_FENCED_BLOCK_PATTERN = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n(?P<body>.*?)(?:\n(?P=fence)\s*$)", re.DOTALL | re.MULTILINE)

ALLOWED_JUDGEMENT_TOKENS = {
    "GO",
    "GO_WITH_NOTE",
    "HOLD",
    "REWORK",
    "REWRITE_STEP",
    "REWRITE_PLAN",
    "ROLLBACK",
    "DONE",
    "DONE_WITH_NOTE",
}


class PhaseSpecLoadError(ValueError):
    """Raised when a phase specification cannot be loaded or parsed."""


@dataclass(slots=True)
class PhaseSpec:
    """Structured phase specification loaded from workflow phase files."""

    phase: str
    checkpoint_items: list[str] = field(default_factory=list)
    allowed_judgements: list[str] = field(default_factory=list)


def _find_workspace_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if any((candidate / marker).exists() for marker in WORKSPACE_ROOT_MARKERS):
            return candidate
    return None


def resolve_workspace_root(workspace_root: str | Path | None = None) -> Path:
    """Resolve an explicit workspace root, climbing from nested paths when possible."""

    if workspace_root is None:
        raise PhaseSpecLoadError("workspace_root is required.")
    explicit_root = Path(workspace_root).resolve()
    discovered_root = _find_workspace_root(explicit_root)
    return discovered_root or explicit_root


def _phase_doc_path(phase: str, workspace_root: str | Path | None) -> Path:
    normalized_phase = phase.strip()
    filename = PHASE_DOC_FILENAMES.get(normalized_phase)
    if filename is None:
        raise PhaseSpecLoadError(f"Unsupported phase: {phase}")

    root = resolve_workspace_root(workspace_root)
    path = root / "phases" / filename
    if not path.exists():
        raise PhaseSpecLoadError(f"Phase spec document is missing: {path}")
    return path


def _heading_text(line: str, level: int) -> str | None:
    match = re.match(rf"^#{{{level}}}\s+(.+?)\s*#*\s*$", line.strip())
    if match is None:
        return None
    return match.group(1).strip()


def _header_matches(line: str, aliases: set[str], level: int) -> bool:
    heading = _heading_text(line, level)
    return heading is not None and heading.casefold() in {alias.casefold() for alias in aliases}


def _section_lines(lines: list[str], header_aliases: set[str], header_level: int) -> list[str]:
    in_section = False
    collected: list[str] = []

    for line in lines:
        if _header_matches(line, header_aliases, header_level):
            in_section = True
            continue
        if in_section and _heading_text(line, header_level) is not None:
            break
        if in_section:
            collected.append(line)

    if not in_section:
        raise PhaseSpecLoadError(f"Required section is missing: {sorted(header_aliases)}")
    return collected


def _bullet_values(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
    return values


def _strip_fenced_blocks(lines: list[str]) -> list[str]:
    filtered: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in lines:
        stripped = line.strip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence = True
            fence_marker = stripped[:3]
            continue
        if in_fence and stripped.startswith(fence_marker):
            in_fence = False
            fence_marker = ""
            continue
        if not in_fence:
            filtered.append(line)
    return filtered


def _as_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PhaseSpecLoadError(f"Embedded phase spec has invalid {field_name}.")
    result = [str(item).strip() for item in value]
    if any(not item for item in result):
        raise PhaseSpecLoadError(f"Embedded phase spec has empty {field_name} item.")
    return result


def _validate_allowed_judgements(values: list[str]) -> None:
    invalid = [value for value in values if value not in ALLOWED_JUDGEMENT_TOKENS]
    if invalid:
        raise PhaseSpecLoadError(f"Embedded phase spec has unsupported judgement token: {invalid}")


def _embedded_phase_spec(text: str, phase: str) -> PhaseSpec | None:
    for match in _FENCED_BLOCK_PATTERN.finditer(text):
        info_tokens = set(match.group("info").strip().casefold().split())
        if not ({"yaml", "phase-spec"} <= info_tokens or {"yml", "phase-spec"} <= info_tokens):
            continue
        body = match.group("body")
        if re.search(r"(?m)^phase_spec:\s*$", body) is None:
            continue
        try:
            payload = parse_yaml_block(body)
        except YamlBlockParseError as exc:
            raise PhaseSpecLoadError(f"Embedded phase spec YAML could not be parsed: {exc}") from exc
        if not isinstance(payload, dict):
            continue
        spec_payload = payload.get("phase_spec")
        if spec_payload is None:
            continue
        if not isinstance(spec_payload, dict):
            raise PhaseSpecLoadError("Embedded phase_spec must be a mapping.")
        spec_phase = str(spec_payload.get("phase", phase)).strip()
        if spec_phase and spec_phase != phase:
            raise PhaseSpecLoadError(f"Embedded phase spec phase mismatch: {spec_phase}")
        checkpoint_items = _as_string_list(spec_payload.get("checkpoint_items"), "checkpoint_items")
        allowed_judgements = _as_string_list(spec_payload.get("allowed_judgements"), "allowed_judgements")
        _validate_allowed_judgements(allowed_judgements)
        return PhaseSpec(
            phase=phase,
            checkpoint_items=checkpoint_items,
            allowed_judgements=allowed_judgements,
        )
    return None


def load_phase_spec(phase: str, workspace_root: str | Path | None = None) -> PhaseSpec:
    """Load a shared phase spec from phases."""

    normalized_phase = phase.strip()
    path = _phase_doc_path(normalized_phase, workspace_root)
    content = path.read_text(encoding="utf-8")
    embedded = _embedded_phase_spec(content, normalized_phase)
    if embedded is not None:
        return embedded

    lines = _strip_fenced_blocks(content.splitlines())
    checkpoint_lines = _section_lines(lines, {"Checkpoint", "체크포인트"}, 2)
    checkpoint_items = _bullet_values(_section_lines(checkpoint_lines, {"확인 항목", "Check Items"}, 3))
    allowed_judgements = _bullet_values(_section_lines(checkpoint_lines, {"판정", "Judgements", "Judgments"}, 3))

    if not checkpoint_items:
        raise PhaseSpecLoadError(f"Phase spec has no checkpoint items: {path}")
    if not allowed_judgements:
        raise PhaseSpecLoadError(f"Phase spec has no allowed judgements: {path}")

    return PhaseSpec(
        phase=normalized_phase,
        checkpoint_items=checkpoint_items,
        allowed_judgements=allowed_judgements,
    )
