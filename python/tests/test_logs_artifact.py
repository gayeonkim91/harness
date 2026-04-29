from __future__ import annotations

from pathlib import Path

from harness.shared.artifacts.logs_artifact import (
    append_checkpoint_log,
    append_review_log,
    append_verification_log,
    resolve_latest_checkpoint_ref,
    resolve_latest_review_ref,
    resolve_latest_verification_ref,
)


def test_append_checkpoint_log_writes_entry_and_resolves_latest(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"

    first_ref = append_checkpoint_log(logs_dir, '{"summary":"first"}')
    second_ref = append_checkpoint_log(logs_dir, '{"summary":"second"}')

    assert not Path(first_ref).is_absolute()
    assert (tmp_path / first_ref).exists()
    assert (tmp_path / second_ref).exists()
    assert (tmp_path / second_ref).read_text(encoding="utf-8").endswith("\n")
    assert resolve_latest_checkpoint_ref(logs_dir) == second_ref


def test_resolve_latest_refs_return_none_for_empty_logs(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"

    assert resolve_latest_checkpoint_ref(logs_dir) is None
    assert resolve_latest_verification_ref(logs_dir) is None
    assert resolve_latest_review_ref(logs_dir) is None


def test_append_verification_and_review_logs_use_separate_namespaces(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"

    verification_ref = append_verification_log(logs_dir, "{}")
    review_ref = append_review_log(logs_dir, "{}")

    assert "logs/verification/" in verification_ref
    assert "logs/review/" in review_ref
    assert resolve_latest_verification_ref(logs_dir) == verification_ref
    assert resolve_latest_review_ref(logs_dir) == review_ref
