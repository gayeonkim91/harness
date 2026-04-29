from __future__ import annotations

import json
from pathlib import Path

from harness.shared.artifacts.apply_sink import record_apply_partial_recovery


def test_record_apply_partial_recovery_writes_unresolved_record(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"

    ref = record_apply_partial_recovery(
        logs_dir,
        reason_code="APPLY_COMMIT_PARTIAL",
        updated_artifacts=["plan"],
        required_artifact_actions=[
            {
                "target": "plan",
                "action": "plan.record_contract_note",
                "params": {"note_text": "note", "note_basis_refs": []},
                "basis_ref": "logs/checkpoints/checkpoint.json",
            }
        ],
        routing_basis_ref="logs/checkpoints/checkpoint.json",
    )

    payload = json.loads((tmp_path / ref).read_text(encoding="utf-8"))
    assert ref.startswith("logs/apply-recovery/")
    assert payload["record_type"] == "apply_partial_recovery"
    assert payload["status"] == "unresolved"
    assert payload["reason_code"] == "APPLY_COMMIT_PARTIAL"
    assert payload["updated_artifacts"] == ["plan"]
    assert payload["routing_basis_ref"] == "logs/checkpoints/checkpoint.json"
