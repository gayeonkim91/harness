"""One-shot state.json migration helpers.

Schema v1 → v2 carries these rewrites:

- ``session_state``: ``"active"`` becomes ``"in_progress"``
- legacy ``pending_approval_for="verification_entry"`` is cleared because the
  implementation → verification approval gate no longer exists
- ``approvals_granted`` is initialized when missing
- ``last_updated``: ISO-8601 with offset becomes ``YYYY-MM-dd HH:mm:ss KST``

Inputs already at v2 are returned unchanged unless they still contain PR1-era
legacy fields. A backup of the original payload is written next to the file
before any rewrite, so a botched migration can be manually reverted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


CURRENT_SCHEMA_VERSION = 2

_LEGACY_SESSION_STATE_REWRITES = {"active": "in_progress"}
_LEGACY_VERIFICATION_APPROVAL = "verification_entry"


@dataclass(slots=True)
class StateMigrationResult:
    """Outcome of a single migrate call."""

    migrated: bool
    from_version: int
    to_version: int
    backup_path: Path | None
    rewrites: list[str]
    payload: dict[str, Any] | None = None


class StateMigrationError(Exception):
    """Raised when a state.json file cannot be migrated."""


class StateKindMismatchError(StateMigrationError):
    """Raised when a non-runbook state is read through the runbook reader."""


def migrate_state_file(state_path: str | Path) -> StateMigrationResult:
    """Migrate or repair a state.json file in place when needed.

    Idempotent: a current clean file is left untouched and ``migrated=False`` is
    returned. A backup is written before any rewrite.
    """

    path = Path(state_path)
    if not path.exists():
        raise StateMigrationError(f"state file not found: {path}")

    try:
        payload_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateMigrationError(f"state file cannot be read: {path}") from exc

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise StateMigrationError(f"state file is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise StateMigrationError(f"state file root must be a JSON object: {path}")
    if payload.get("workflow_kind") == "docs_only":
        raise StateKindMismatchError(f"state file is docs_only, not runbook: {path}")

    from_version = int(payload.get("schema_version", 0))
    if from_version > CURRENT_SCHEMA_VERSION:
        return StateMigrationResult(
            migrated=False,
            from_version=from_version,
            to_version=from_version,
            backup_path=None,
            rewrites=[],
            payload=payload,
        )
    if from_version < 1:
        raise StateMigrationError(
            f"state file has unknown schema_version {from_version!r}: {path}"
        )

    if from_version == CURRENT_SCHEMA_VERSION:
        migrated_payload, rewrites = _apply_current_schema_repairs(dict(payload))
        if not rewrites:
            return StateMigrationResult(
                migrated=False,
                from_version=from_version,
                to_version=from_version,
                backup_path=None,
                rewrites=[],
                payload=migrated_payload,
            )
    else:
        migrated_payload, rewrites = _apply_v1_to_v2(dict(payload))
        migrated_payload["schema_version"] = CURRENT_SCHEMA_VERSION

    try:
        backup_path = _write_backup(path, from_version, payload_text)
        path.write_text(
            json.dumps(migrated_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise StateMigrationError(f"state file cannot be migrated: {path}") from exc

    return StateMigrationResult(
        migrated=True,
        from_version=from_version,
        to_version=CURRENT_SCHEMA_VERSION,
        backup_path=backup_path,
        rewrites=rewrites,
        payload=migrated_payload,
    )


def _write_backup(path: Path, from_version: int, payload_text: str) -> Path:
    backup_path = path.parent / f"{path.name}.v{from_version}.bak"
    backup_path.write_text(payload_text, encoding="utf-8")
    return backup_path


def _apply_v1_to_v2(payload: dict) -> tuple[dict, list[str]]:
    rewrites: list[str] = []

    session_state = payload.get("session_state")
    if isinstance(session_state, str) and session_state in _LEGACY_SESSION_STATE_REWRITES:
        payload["session_state"] = _LEGACY_SESSION_STATE_REWRITES[session_state]
        rewrites.append(f"session_state:{session_state}->{payload['session_state']}")

    _clear_legacy_verification_approval(payload, rewrites)
    _ensure_approvals_granted(payload, rewrites)
    _normalize_last_updated(payload, rewrites)

    return payload, rewrites


def _apply_current_schema_repairs(payload: dict) -> tuple[dict, list[str]]:
    rewrites: list[str] = []
    _clear_legacy_verification_approval(payload, rewrites)
    _ensure_approvals_granted(payload, rewrites)
    _normalize_last_updated(payload, rewrites)
    return payload, rewrites


def _clear_legacy_verification_approval(payload: dict, rewrites: list[str]) -> None:
    pending_approval_for = payload.get("pending_approval_for")
    if pending_approval_for != _LEGACY_VERIFICATION_APPROVAL:
        return

    payload["pending_approval_for"] = None
    rewrites.append("pending_approval_for:verification_entry->null")

    if payload.get("session_state") == "awaiting_approval":
        payload["session_state"] = "in_progress"
        rewrites.append("session_state:awaiting_approval->in_progress")


def _ensure_approvals_granted(payload: dict, rewrites: list[str]) -> None:
    if "approvals_granted" not in payload or payload["approvals_granted"] is None:
        payload["approvals_granted"] = []
        rewrites.append("approvals_granted:missing->[]")


def _normalize_last_updated(payload: dict, rewrites: list[str]) -> None:
    last_updated = payload.get("last_updated")
    if not isinstance(last_updated, str):
        return
    converted = _convert_last_updated(last_updated)
    if converted is not None and converted != last_updated:
        payload["last_updated"] = converted
        rewrites.append("last_updated:iso->kst_suffix")


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
