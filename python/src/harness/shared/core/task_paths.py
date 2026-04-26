"""Canonical task path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TaskPaths:
    """Canonical artifact paths under a task root."""

    task_root: Path
    plan_path: Path
    steps_path: Path
    state_path: Path
    logs_dir: Path


def get_task_paths(task_root: str | Path) -> TaskPaths:
    """Return canonical workflow artifact paths for a task root."""

    root = Path(task_root)
    return TaskPaths(
        task_root=root,
        plan_path=root / "plan.md",
        steps_path=root / "steps.md",
        state_path=root / "state.json",
        logs_dir=root / "logs",
    )
