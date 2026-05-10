"""Markdown heading indexer for partial section reads and writes."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class Section:
    """Indexed markdown section with inclusive 1-based line bounds."""

    title: str
    level: int
    start_line: int
    end_line: int


@dataclass(slots=True)
class _MutableSection:
    title: str
    level: int
    start_line: int
    end_line: int


_HEADING_PATTERN = re.compile(r"^(?P<indent> {0,3})(?P<hashes>#{1,6})(?P<rest>[ \t].*|)$")
_HEADING_CLOSING_SEQUENCE_PATTERN = re.compile(r"^(?P<title>.*?)(?:[ \t]+#+[ \t]*)?$")


def _parse_heading(line: str) -> tuple[str, int] | None:
    match = _HEADING_PATTERN.match(line)
    if match is None:
        return None

    rest = match.group("rest")
    if rest and rest[0] not in {" ", "\t"}:
        return None

    closing_match = _HEADING_CLOSING_SEQUENCE_PATTERN.match(rest)
    if closing_match is None:
        return None

    title = closing_match.group("title").strip()
    return title, len(match.group("hashes"))


def _fence_opener(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip(" ")
    if not stripped or len(line) - len(stripped) > 3:
        return None

    fence_char = stripped[0]
    if fence_char not in {"`", "~"}:
        return None

    fence_length = 0
    while fence_length < len(stripped) and stripped[fence_length] == fence_char:
        fence_length += 1
    if fence_length < 3:
        return None
    if fence_char == "`" and "`" in stripped[fence_length:]:
        return None
    return fence_char, fence_length


def _is_fence_closer(line: str, fence_char: str, minimum_length: int) -> bool:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return False

    fence_length = 0
    while fence_length < len(stripped) and stripped[fence_length] == fence_char:
        fence_length += 1
    if fence_length < minimum_length:
        return False
    return stripped[fence_length:].strip() == ""


def parse_index(text: str) -> list[Section]:
    """Parse all ATX headings into a section index.

    Returned line numbers are 1-based and inclusive. `start_line` points at the
    heading line itself, and `end_line` extends through nested content until the
    next heading of the same or higher level, or EOF.
    """

    lines = text.splitlines()
    if not lines:
        return []

    total_lines = len(lines)
    sections: list[_MutableSection] = []
    open_section_indexes: list[int] = []
    active_fence_char: str | None = None
    active_fence_length = 0

    for line_number, line in enumerate(lines, start=1):
        if active_fence_char is not None:
            if _is_fence_closer(line, active_fence_char, active_fence_length):
                active_fence_char = None
                active_fence_length = 0
            continue

        fence = _fence_opener(line)
        if fence is not None:
            active_fence_char, active_fence_length = fence
            continue

        heading = _parse_heading(line)
        if heading is None:
            continue

        title, level = heading
        while open_section_indexes and sections[open_section_indexes[-1]].level >= level:
            previous = sections[open_section_indexes.pop()]
            previous.end_line = line_number - 1

        sections.append(
            _MutableSection(
                title=title,
                level=level,
                start_line=line_number,
                end_line=total_lines,
            )
        )
        open_section_indexes.append(len(sections) - 1)

    return [
        Section(
            title=section.title,
            level=section.level,
            start_line=section.start_line,
            end_line=section.end_line,
        )
        for section in sections
    ]
