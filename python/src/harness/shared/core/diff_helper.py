"""Task-scoped diff helper."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TaskScopedDiff:
    """Task-scoped diff view based on a pinned baseline."""

    baseline_ref: str
    raw_diff: str
    fingerprint_material: str


class TaskScopedDiffError(RuntimeError):
    """Raised when task-scoped diff cannot be built."""


def _run_git(workspace_root: Path, *args: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise TaskScopedDiffError("git executable is unavailable.") from exc

    if completed.returncode != 0:
        return False, completed.stdout.strip() or completed.stderr.strip()
    return True, completed.stdout


def _resolve_task_ref(task_root: str | Path, ref: str | Path) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return Path(task_root) / path


def _load_baseline(task_root: str | Path, baseline_ref: str | Path) -> dict[str, Any]:
    path = _resolve_task_ref(task_root, baseline_ref)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskScopedDiffError(f"Failed to read workspace baseline artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise TaskScopedDiffError("Workspace baseline artifact root must be a mapping.")
    return payload


def _current_status(workspace_root: Path) -> list[str]:
    ok, output = _run_git(workspace_root, "status", "--porcelain=v1")
    if not ok:
        raise TaskScopedDiffError(f"Failed to read git status: {output}")
    return output.splitlines() if output.strip() else []


def _changed_patch_section(
    label: str,
    baseline_patch: str,
    current_patch: str,
) -> str:
    baseline_patch = baseline_patch.rstrip()
    current_patch = current_patch.rstrip()
    if baseline_patch == current_patch:
        return ""
    return (
        f"## {label}\n"
        "### baseline\n"
        f"{baseline_patch}\n"
        "### current\n"
        f"{current_patch}"
    ).rstrip()


def _build_head_diff(
    workspace_root: Path,
    baseline_head: str,
    baseline_status: list[str],
    baseline_working_tree_diff: str,
    baseline_staged_diff: str,
) -> tuple[str, str]:
    current_status = _current_status(workspace_root)
    diff_parts: list[str] = []
    ok, commit_diff = _run_git(workspace_root, "diff", "--binary", baseline_head, "HEAD")
    if ok and commit_diff:
        diff_parts.append("## commit-diff\n" + commit_diff.rstrip())
    if not ok:
        diff_parts.append("## diff-error: commit-diff\n" + commit_diff.rstrip())

    ok, working_tree_diff = _run_git(workspace_root, "diff", "--binary")
    if ok:
        section = _changed_patch_section("working-tree-diff", baseline_working_tree_diff, working_tree_diff)
        if section:
            diff_parts.append(section)
    else:
        diff_parts.append("## diff-error: working-tree-diff\n" + working_tree_diff.rstrip())

    ok, staged_diff = _run_git(workspace_root, "diff", "--binary", "--cached")
    if ok:
        section = _changed_patch_section("staged-diff", baseline_staged_diff, staged_diff)
        if section:
            diff_parts.append(section)
    else:
        diff_parts.append("## diff-error: staged-diff\n" + staged_diff.rstrip())

    status_delta = _format_status_delta(baseline_status, current_status)
    if status_delta:
        diff_parts.append("## status-delta\n" + status_delta)

    raw_diff = "\n\n".join(diff_parts)
    material = json.dumps(
        {
            "baseline_head": baseline_head,
            "baseline_status": baseline_status,
            "baseline_working_tree_diff": baseline_working_tree_diff,
            "baseline_staged_diff": baseline_staged_diff,
            "current_status": current_status,
            "raw_diff": raw_diff,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return raw_diff, material


def _format_status_delta(baseline_status: list[str], current_status: list[str]) -> str:
    baseline_set = set(baseline_status)
    current_set = set(current_status)
    added = sorted(current_set - baseline_set)
    removed = sorted(baseline_set - current_set)
    lines: list[str] = []
    lines.extend(f"+ {line}" for line in added)
    lines.extend(f"- {line}" for line in removed)
    return "\n".join(lines)


def _build_status_only_diff(workspace_root: Path, baseline_status: list[str]) -> tuple[str, str]:
    current_status = _current_status(workspace_root)
    status_delta = _format_status_delta(baseline_status, current_status)
    material = json.dumps(
        {
            "baseline_status": baseline_status,
            "current_status": current_status,
            "status_delta": status_delta,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return status_delta, material


def build_task_scoped_diff(task_root: str | Path, baseline_ref: str) -> TaskScopedDiff:
    """Build the factual task-scoped diff against a baseline artifact."""
    baseline = _load_baseline(task_root, baseline_ref)
    workspace_root = Path(str(baseline.get("workspace_root", "")))
    if not workspace_root.exists():
        raise TaskScopedDiffError(f"Workspace root from baseline does not exist: {workspace_root}")

    vcs = baseline.get("vcs", {})
    if not isinstance(vcs, dict):
        raise TaskScopedDiffError("Workspace baseline artifact is missing vcs metadata.")
    if vcs.get("kind") != "git":
        raise TaskScopedDiffError("Only git baseline artifacts are supported by the current diff helper.")

    baseline_status = [str(item) for item in vcs.get("status_porcelain_v1", [])]
    baseline_working_tree_diff = str(vcs.get("working_tree_diff", ""))
    baseline_staged_diff = str(vcs.get("staged_diff", ""))
    baseline_head = vcs.get("head_commit")
    if isinstance(baseline_head, str) and baseline_head:
        raw_diff, material = _build_head_diff(
            workspace_root,
            baseline_head,
            baseline_status,
            baseline_working_tree_diff,
            baseline_staged_diff,
        )
    else:
        raw_diff, material = _build_status_only_diff(workspace_root, baseline_status)

    return TaskScopedDiff(
        baseline_ref=str(baseline_ref),
        raw_diff=raw_diff,
        fingerprint_material=material,
    )


def compute_task_diff_fingerprint(diff: TaskScopedDiff) -> str:
    """Compute a stable fingerprint for a task-scoped diff."""
    digest = hashlib.sha256(diff.fingerprint_material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
