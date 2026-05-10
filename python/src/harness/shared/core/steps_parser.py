"""Canonical parser for inline execution steps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedStep:
    line_index: int
    mark: str
    text: str
    step_ref: str
    go_marker_present: bool
    legacy_step_ref: str | None = None


@dataclass(slots=True)
class StepParseResult:
    steps: list[ParsedStep] = field(default_factory=list)
    reason_code: str | None = None


STEP_PATTERN = re.compile(
    r"^- \[(?P<mark>[ xX])\]\s+(?P<body>.*?)(?:\s+\[step_ref=(?P<ref>[^\]]+)\])?\s*$"
)
GO_MARKER = " (go)"
STEPS_SECTION_ALIASES = {
    "steps",
    "진행 단계 (steps)",
    "진행 단계(steps)",
}


def _normalize_section_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def parse_steps(content: str) -> StepParseResult:
    """Parse top-level execution steps from the inline Steps section.

    PR7 makes ``(go)`` marker location the current-step identity. Legacy
    ``[step_ref=...]`` markers remain readable, but new inline steps do not
    need to carry a machine id. For no-ref steps, ``step_ref`` is an ephemeral
    document-order locator used only inside one routing/apply round trip.
    """

    steps: list[ParsedStep] = []
    refs: set[str] = set()
    go_count = 0
    in_section = False
    in_fence = False
    in_html_comment = False
    lines = content.splitlines()

    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if line.startswith("## ") and _normalize_section_title(line[3:]) in STEPS_SECTION_ALIASES:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.strip():
            continue
        stripped = line.strip()
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_html_comment = True
            continue
        if line[:1].isspace():
            continue

        match = STEP_PATTERN.match(line)
        if match is None:
            return StepParseResult(reason_code="APPLY_STEP_REF_INVALID")
        legacy_step_ref = match.group("ref")
        step_ref = legacy_step_ref or f"step:{len(steps) + 1}"
        if legacy_step_ref is not None and legacy_step_ref in refs:
            return StepParseResult(reason_code="APPLY_STEP_REF_INVALID")
        if legacy_step_ref is not None:
            refs.add(legacy_step_ref)

        body = match.group("body")
        go_present = body.endswith(GO_MARKER)
        step_text = body[: -len(GO_MARKER)] if go_present else body
        go_count += 1 if go_present else 0
        steps.append(
            ParsedStep(
                line_index=index,
                mark=match.group("mark"),
                text=step_text.strip(),
                step_ref=step_ref,
                go_marker_present=go_present,
                legacy_step_ref=legacy_step_ref,
            )
        )

    if go_count > 1:
        return StepParseResult(reason_code="APPLY_GO_CARDINALITY_INVALID")
    return StepParseResult(steps=steps)


def find_step(steps: list[ParsedStep], step_ref: str) -> ParsedStep | None:
    for step in steps:
        if step.step_ref == step_ref:
            return step
    return None
