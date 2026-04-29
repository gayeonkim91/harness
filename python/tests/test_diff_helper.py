from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.shared.core.diff_helper import build_task_scoped_diff, compute_task_diff_fingerprint
from harness.shared.core.snapshot_helper import capture_workspace_baseline


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True, text=True)


def test_task_scoped_diff_uses_status_delta_when_head_is_unavailable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")

    task_root = tmp_path / "task"
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)

    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")
    diff = build_task_scoped_diff(task_root, baseline_ref)

    assert "+ ?? new-file.txt" in diff.raw_diff
    assert compute_task_diff_fingerprint(diff).startswith("sha256:")


def test_capture_workspace_baseline_requires_workspace_root(tmp_path: Path) -> None:
    try:
        capture_workspace_baseline(tmp_path / "task")
    except ValueError as exc:
        assert "workspace_root is required" in str(exc)
    else:
        raise AssertionError("capture_workspace_baseline should require workspace_root")


def test_task_diff_fingerprint_is_stable_for_same_diff(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")

    task_root = tmp_path / "task"
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    first = build_task_scoped_diff(task_root, baseline_ref)
    second = build_task_scoped_diff(task_root, baseline_ref)

    assert first.raw_diff == second.raw_diff
    assert compute_task_diff_fingerprint(first) == compute_task_diff_fingerprint(second)


def test_task_scoped_diff_includes_working_tree_diff_when_head_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Harness Test")
    tracked = workspace / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")

    task_root = tmp_path / "task"
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    tracked.write_text("after\n", encoding="utf-8")

    diff = build_task_scoped_diff(task_root, baseline_ref)

    assert "## working-tree-diff" in diff.raw_diff
    assert "-before" in diff.raw_diff
    assert "+after" in diff.raw_diff


def test_task_scoped_diff_excludes_preexisting_dirty_tracked_change(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Harness Test")
    tracked = workspace / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")
    tracked.write_text("dirty-before-start\n", encoding="utf-8")

    task_root = tmp_path / "task"
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    diff = build_task_scoped_diff(task_root, baseline_ref)

    assert diff.raw_diff == ""


def test_task_scoped_diff_records_diff_errors_in_raw_diff(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Harness Test")
    tracked = workspace / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "initial")

    task_root = tmp_path / "task"
    baseline_ref = capture_workspace_baseline(task_root, workspace_root=workspace)
    baseline_path = task_root / baseline_ref
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["vcs"]["head_commit"] = "missing-baseline-head"
    baseline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    diff = build_task_scoped_diff(task_root, baseline_ref)

    assert "## diff-error: commit-diff" in diff.raw_diff
    assert "missing-baseline-head" in diff.raw_diff
