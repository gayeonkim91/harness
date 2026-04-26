"""Workspace baseline capture helper."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from harness.shared.artifacts.logs_artifact import log_ref_for_path


def _kst_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _run_git(workspace_root: Path, *args: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False, ""

    if completed.returncode != 0:
        return False, completed.stdout.strip() or completed.stderr.strip()
    return True, completed.stdout


def capture_workspace_baseline(task_root: str | Path, workspace_root: str | Path | None = None) -> str:
    """Capture a task-local baseline artifact and return its pinned ref."""
    if workspace_root is None:
        raise ValueError("workspace_root is required.")

    task_root_path = Path(task_root)
    task_root_path.mkdir(parents=True, exist_ok=True)
    logs_dir = task_root_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    workspace_root_path = Path(workspace_root)
    baseline_path = logs_dir / "workspace-baseline.json"

    repo_ok, repo_root = _run_git(workspace_root_path, "rev-parse", "--show-toplevel")
    head_ok, head_commit = _run_git(workspace_root_path, "rev-parse", "HEAD")
    status_ok, status_porcelain = _run_git(workspace_root_path, "status", "--porcelain=v1")
    diff_ok, working_tree_diff = _run_git(workspace_root_path, "diff", "--binary")
    staged_diff_ok, staged_diff = _run_git(workspace_root_path, "diff", "--binary", "--cached")

    payload = {
        "captured_at": _kst_timestamp(),
        "workspace_root": str(workspace_root_path.resolve()),
        "vcs": {
            "kind": "git" if repo_ok else "none",
            "repo_root": repo_root.strip() if repo_ok else None,
            "head_commit": head_commit.strip() if head_ok else None,
            "head_available": head_ok,
            "status_porcelain_v1": status_porcelain.splitlines() if status_ok and status_porcelain else [],
            "working_tree_diff": working_tree_diff if diff_ok else "",
            "staged_diff": staged_diff if staged_diff_ok else "",
        },
    }
    baseline_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return log_ref_for_path(logs_dir, baseline_path)
