"""Canonical parser for steps.md execution steps."""

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


@dataclass(slots=True)
class StepParseResult:
    steps: list[ParsedStep] = field(default_factory=list)
    reason_code: str | None = None


STEP_PATTERN = re.compile(r"^- \[(?P<mark>[ xX])\]\s+(?P<body>.*?)\s+\[step_ref=(?P<ref>[^\]]+)\]\s*$")
GO_MARKER = " (go)"


def parse_steps(content: str) -> StepParseResult:
    """Parse canonical top-level execution steps from the Steps section."""

    steps: list[ParsedStep] = []
    refs: set[str] = set()
    go_count = 0
    in_section = False
    in_fence = False
    lines = content.splitlines()

    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if line == "## Steps":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.strip():
            continue
        if line[:1].isspace():
            continue

        match = STEP_PATTERN.match(line)
        if match is None:
            return StepParseResult(reason_code="APPLY_STEP_REF_INVALID")
        step_ref = match.group("ref")
        if step_ref in refs:
            return StepParseResult(reason_code="APPLY_STEP_REF_INVALID")
        refs.add(step_ref)

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
