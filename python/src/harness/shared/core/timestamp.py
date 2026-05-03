"""Shared timestamp helpers.

`last_updated` style values (state.json, plan.md Current State) must use the
human-readable KST suffix form ``YYYY-MM-dd HH:mm:ss KST``. Audit-trail
timestamps embedded inside log files (``occurred_at``, ``persisted_at``,
``captured_at``) keep their ISO-8601 form for now.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def kst_now_human() -> str:
    """Return the current KST time formatted as ``YYYY-MM-dd HH:mm:ss KST``."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


def kst_now_iso() -> str:
    """Return the current KST time as ISO-8601 with offset."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
