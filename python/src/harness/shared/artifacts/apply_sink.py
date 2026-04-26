"""Durable sink for /wf-apply failure and recovery records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from harness.shared.artifacts.logs_artifact import log_ref_for_path, reserve_log_path
from harness.shared.core.json_util import to_jsonable


def _kst_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def record_apply_partial_recovery(
    logs_dir: str | Path,
    reason_code: str,
    updated_artifacts: list[str],
    required_artifact_actions: list[dict[str, Any]],
    routing_basis_ref: str,
) -> str:
    """Persist a partial recovery record for APPLY_COMMIT_PARTIAL."""

    path = reserve_log_path(logs_dir, "apply-recovery")
    payload = {
        "record_type": "apply_partial_recovery",
        "status": "unresolved",
        "occurred_at": _kst_timestamp(),
        "reason_code": reason_code,
        "updated_artifacts": updated_artifacts,
        "required_artifact_actions": to_jsonable(required_artifact_actions),
        "routing_basis_ref": routing_basis_ref,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return log_ref_for_path(logs_dir, path)
