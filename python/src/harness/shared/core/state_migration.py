"""One-shot state.json migration helpers.

Schema v1 → v2 carries two rewrites:

- ``session_state``: ``"active"`` becomes ``"in_progress"``
- ``last_updated``: ISO-8601 with offset becomes ``YYYY-MM-dd HH:mm:ss KST``

The ``pending_approval_for`` ``"verification_entry"`` → ``"plan_to_implementation"``
rewrite is deferred until the approval-router PR lands together. Rewriting the
token here while the router still expects the legacy value would break approval
routing for migrated tasks.

Inputs already at v2 are returned unchanged. A backup of the original payload is
written next to the file before any rewrite, so a botched migration can be
manually reverted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


CURRENT_SCHEMA_VERSION = 2

_LEGACY_SESSION_STATE_REWRITES = {"active": "in_progress"}


@dataclass(slots=True)
class StateMigrationResult:
    """Outcome of a single migrate call."""

    migrated: bool
    from_version: int
    to_version: int
    backup_path: Path | None
    rewrites: list[str]


class StateMigrationError(Exception):
    """Raised when a state.json file cannot be migrated."""


def migrate_state_file(state_path: str | Path) -> StateMigrationResult:
    """Migrate a state.json file in place if its schema_version is below current.

    Idempotent: a v2+ file is left untouched and ``migrated=False`` is returned.
    A backup is written before any rewrite.
    """

    path = Path(state_path)
    if not path.exists():
        raise StateMigrationError(f"state file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateMigrationError(f"state file is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise StateMigrationError(f"state file root must be a JSON object: {path}")

    from_version = int(payload.get("schema_version", 0))
    if from_version >= CURRENT_SCHEMA_VERSION:
        return StateMigrationResult(
            migrated=False,
            from_version=from_version,
            to_version=from_version,
            backup_path=None,
            rewrites=[],
        )
    if from_version < 1:
        raise StateMigrationError(
            f"state file has unknown schema_version {from_version!r}: {path}"
        )

    backup_path = _write_backup(path, from_version)
    migrated_payload, rewrites = _apply_v1_to_v2(payload)
    migrated_payload["schema_version"] = CURRENT_SCHEMA_VERSION
    path.write_text(
        json.dumps(migrated_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    return StateMigrationResult(
        migrated=True,
        from_version=from_version,
        to_version=CURRENT_SCHEMA_VERSION,
        backup_path=backup_path,
        rewrites=rewrites,
    )


def _write_backup(path: Path, from_version: int) -> Path:
    backup_path = path.parent / f"{path.name}.v{from_version}.bak"
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def _apply_v1_to_v2(payload: dict) -> tuple[dict, list[str]]:
    rewrites: list[str] = []

    session_state = payload.get("session_state")
    if isinstance(session_state, str) and session_state in _LEGACY_SESSION_STATE_REWRITES:
        payload["session_state"] = _LEGACY_SESSION_STATE_REWRITES[session_state]
        rewrites.append(f"session_state:{session_state}->{payload['session_state']}")

    last_updated = payload.get("last_updated")
    if isinstance(last_updated, str):
        converted = _convert_last_updated(last_updated)
        if converted is not None and converted != last_updated:
            payload["last_updated"] = converted
            rewrites.append("last_updated:iso->kst_suffix")

    return payload, rewrites


def _convert_last_updated(value: str) -> str | None:
    """Convert ISO-8601 (with offset) to ``YYYY-MM-dd HH:mm:ss KST``.

    Returns ``None`` when the value cannot be parsed; the original string is
    then preserved untouched (we never invent a timestamp).
    """

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    else:
        parsed = parsed.astimezone(ZoneInfo("Asia/Seoul"))
    return parsed.strftime("%Y-%m-%d %H:%M:%S KST")
