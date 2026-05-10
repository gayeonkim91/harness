"""Resolve the current semantic source for inline workflow steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.shared.contracts.actions import CurrentStepRefSnapshot
from harness.shared.core.steps_parser import STEPS_SECTION_ALIASES, StepParseResult, parse_steps
from harness.shared.core.task_paths import get_task_paths

STEPS_PLACEHOLDER_SENTINEL = "<!-- harness:steps-placeholder -->"


@dataclass(frozen=True, slots=True)
class StepArtifact:
    """Resolved physical artifact for semantic step actions."""

    path: Path
    content: str
    artifact_name: str


def _normalize_section_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def has_steps_section(content: str) -> bool:
    """Return whether content has a top-level inline Steps section."""

    in_fence = False
    for line in content.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## ") and _normalize_section_title(line[3:]) in STEPS_SECTION_ALIASES:
            return True
    return False


def has_steps_placeholder_sentinel(content: str) -> bool:
    """Return whether the inline Steps section is explicitly marked placeholder."""

    in_section = False
    in_fence = False
    for line in content.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## ") and _normalize_section_title(line[3:]) in STEPS_SECTION_ALIASES:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            return False
        if in_section and line.strip() == STEPS_PLACEHOLDER_SENTINEL:
            return True
    return False


def _has_execution_steps(parsed: StepParseResult) -> bool:
    if parsed.reason_code is not None:
        return False
    return bool(parsed.steps)


def resolve_step_artifact(task_root: str | Path) -> StepArtifact | None:
    """Resolve the physical artifact that currently owns execution steps.

    New PR7 tasks use plan.md. Existing steps.md tasks remain readable as a
    compatibility fallback when plan.md does not yet contain inline steps.
    """

    task_paths = get_task_paths(task_root)
    if task_paths.plan_path.exists():
        plan_content = task_paths.plan_path.read_text(encoding="utf-8")
        has_inline_steps = has_steps_section(plan_content)
        plan_steps = parse_steps(plan_content) if has_inline_steps else StepParseResult()
        if plan_steps.reason_code is not None:
            return StepArtifact(path=task_paths.plan_path, content=plan_content, artifact_name="plan")
        if _has_execution_steps(plan_steps) and not has_steps_placeholder_sentinel(plan_content):
            return StepArtifact(path=task_paths.plan_path, content=plan_content, artifact_name="plan")
        if not task_paths.steps_path.exists():
            return StepArtifact(path=task_paths.plan_path, content=plan_content, artifact_name="plan")
    if task_paths.steps_path.exists():
        steps_content = task_paths.steps_path.read_text(encoding="utf-8")
        return StepArtifact(path=task_paths.steps_path, content=steps_content, artifact_name="steps")
    return None


def resolve_current_go_snapshot(task_root: str | Path) -> tuple[CurrentStepRefSnapshot | None, str | None]:
    """Resolve the single current ``(go)`` marker snapshot for step phases."""

    artifact = resolve_step_artifact(task_root)
    if artifact is None:
        return None, "CHECKPOINT_CURRENT_STEP_REF_MISSING"
    parsed = parse_steps(artifact.content)
    if parsed.reason_code is not None:
        return None, parsed.reason_code
    go_steps = [step for step in parsed.steps if step.go_marker_present]
    if len(go_steps) != 1:
        return None, "CHECKPOINT_CURRENT_STEP_REF_MISSING"
    step = go_steps[0]
    return (
        CurrentStepRefSnapshot(
            step_ref=step.step_ref,
            step_text=step.text,
            go_marker_present=True,
        ),
        None,
    )
