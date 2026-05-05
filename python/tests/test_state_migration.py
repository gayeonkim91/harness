from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.artifacts.state_artifact import read_state
from harness.shared.contracts.state import SessionState
from harness.shared.core.state_migration import (
    CURRENT_SCHEMA_VERSION,
    StateMigrationError,
    migrate_state_file,
)


def _v1_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "session_state": "active",
        "workflow_mode": "generic",
        "current_phase": "verification",
        "repo_profile_ref": None,
        "workspace_baseline_ref": "logs/workspace-baseline.json",
        "current_step_ref": None,
        "latest_checkpoint_ref": None,
        "latest_verification_ref": None,
        "latest_review_ref": None,
        "pending_approval_for": "verification_entry",
        "review_outcome": None,
        "closure_authorized": False,
        "counters": {"rework_count": 0, "rewrite_count": 0, "rollback_count": 0},
        "blocked_transition": None,
        "blocked_reason_ref": None,
        "stop_condition_ref": None,
        "last_updated": "2026-04-19T22:00:00+09:00",
        "adapter_meta": {},
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_migrate_v1_rewrites_session_state_and_timestamp(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload())

    result = migrate_state_file(state_path)

    assert result.migrated is True
    assert result.from_version == 1
    assert result.to_version == CURRENT_SCHEMA_VERSION
    assert "session_state:active->in_progress" in result.rewrites
    assert "last_updated:iso->kst_suffix" in result.rewrites

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["session_state"] == "in_progress"
    assert migrated["last_updated"] == "2026-04-19 22:00:00 KST"


def test_migrate_v1_clears_removed_verification_entry_gate(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(
        state_path,
        _v1_payload(
            session_state="awaiting_approval",
            current_phase="verification",
            pending_approval_for="verification_entry",
        ),
    )

    result = migrate_state_file(state_path)
    migrated = json.loads(state_path.read_text(encoding="utf-8"))

    assert migrated["pending_approval_for"] is None
    assert migrated["session_state"] == "in_progress"
    assert "pending_approval_for:verification_entry->null" in result.rewrites
    assert "session_state:awaiting_approval->in_progress" in result.rewrites
    assert migrated["approvals_granted"] == []


def test_migrate_writes_backup_with_v1_suffix(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    original = _v1_payload()
    _write(state_path, original)

    result = migrate_state_file(state_path)

    assert result.backup_path is not None
    assert result.backup_path.name == "state.json.v1.bak"
    assert result.backup_path.exists()
    backup_payload = json.loads(result.backup_path.read_text(encoding="utf-8"))
    assert backup_payload["schema_version"] == 1
    assert backup_payload["session_state"] == "active"
    assert backup_payload["last_updated"] == "2026-04-19T22:00:00+09:00"


def test_migrate_v2_is_noop(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    payload = _v1_payload(
        schema_version=2,
        session_state="in_progress",
        pending_approval_for=None,
        approvals_granted=[],
        last_updated="2026-04-19 22:00:00 KST",
    )
    _write(state_path, payload)

    result = migrate_state_file(state_path)

    assert result.migrated is False
    assert result.backup_path is None
    assert result.rewrites == []
    assert json.loads(state_path.read_text(encoding="utf-8")) == payload


def test_migrate_v2_repairs_pr1_legacy_verification_entry(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(
        state_path,
        _v1_payload(
            schema_version=2,
            session_state="awaiting_approval",
            current_phase="verification",
            pending_approval_for="verification_entry",
            last_updated="2026-04-19 22:00:00 KST",
        ),
    )

    result = migrate_state_file(state_path)
    migrated = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.migrated is True
    assert result.from_version == 2
    assert result.to_version == 2
    assert result.backup_path is not None
    assert result.backup_path.name == "state.json.v2.bak"
    assert migrated["schema_version"] == 2
    assert migrated["session_state"] == "in_progress"
    assert migrated["pending_approval_for"] is None
    assert migrated["current_phase"] == "verification"
    assert migrated["approvals_granted"] == []
    assert "pending_approval_for:verification_entry->null" in result.rewrites


def test_migrate_v2_repairs_iso_timestamp(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(
        state_path,
        _v1_payload(
            schema_version=2,
            session_state="in_progress",
            pending_approval_for=None,
            approvals_granted=[],
            last_updated="2026-04-19T22:00:00+09:00",
        ),
    )

    result = migrate_state_file(state_path)
    migrated = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.migrated is True
    assert migrated["last_updated"] == "2026-04-19 22:00:00 KST"
    assert "last_updated:iso->kst_suffix" in result.rewrites


def test_migrate_then_read_state_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload(pending_approval_for="closure"))

    migrate_state_file(state_path)
    state = read_state(state_path)

    assert state.schema_version == 2
    assert state.session_state is SessionState.IN_PROGRESS
    assert state.pending_approval_for == "closure"
    assert state.last_updated == "2026-04-19 22:00:00 KST"


def test_read_state_auto_repairs_pr1_v2_legacy_verification_entry(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(
        state_path,
        _v1_payload(
            schema_version=2,
            session_state="awaiting_approval",
            current_phase="verification",
            pending_approval_for="verification_entry",
            last_updated="2026-04-19 22:00:00 KST",
        ),
    )

    state = read_state(state_path)
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))

    assert state.session_state is SessionState.IN_PROGRESS
    assert state.pending_approval_for is None
    assert on_disk["session_state"] == "in_progress"
    assert on_disk["pending_approval_for"] is None
    assert (state_path.parent / "state.json.v2.bak").exists()


def test_migrate_unparseable_timestamp_left_untouched(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload(last_updated="not-a-timestamp"))

    result = migrate_state_file(state_path)
    migrated = json.loads(state_path.read_text(encoding="utf-8"))

    assert migrated["last_updated"] == "not-a-timestamp"
    assert "last_updated:iso->kst_suffix" not in result.rewrites


def test_migrate_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(StateMigrationError):
        migrate_state_file(tmp_path / "missing.json")


def test_migrate_unknown_schema_version_raises(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload(schema_version=0))

    with pytest.raises(StateMigrationError):
        migrate_state_file(state_path)


def test_read_state_auto_migrates_literal_v1_json(tmp_path: Path) -> None:
    # Regression: a legacy v1 state.json on disk (with the literal "active"
    # token and ISO timestamp) must be readable without manual migration.
    # read_state() upgrades it in place on first read.
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload())

    state = read_state(state_path)

    assert state.schema_version == 2
    assert state.session_state is SessionState.IN_PROGRESS
    assert state.last_updated == "2026-04-19 22:00:00 KST"

    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 2
    assert on_disk["session_state"] == "in_progress"
    assert (state_path.parent / "state.json.v1.bak").exists()


def test_read_state_second_read_does_not_remigrate(tmp_path: Path) -> None:
    # After auto-migration the backup must not be overwritten on subsequent
    # reads — otherwise we'd lose the original v1 snapshot.
    state_path = tmp_path / "state.json"
    _write(state_path, _v1_payload())

    read_state(state_path)
    backup_path = state_path.parent / "state.json.v1.bak"
    backup_mtime = backup_path.stat().st_mtime

    read_state(state_path)

    assert backup_path.stat().st_mtime == backup_mtime
