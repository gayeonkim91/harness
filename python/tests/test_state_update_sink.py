from __future__ import annotations

import json
from pathlib import Path

from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.artifacts.state_update_sink import (
    adopt_orphan_result_as_latest_ref,
    mark_orphan_adoption_recorded,
    mark_state_update_recovery_resolved,
    record_state_update_recovery,
)
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode


def test_state_update_recovery_can_be_marked_resolved(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    ref = record_state_update_recovery(
        logs_dir,
        namespace="verify-recovery",
        record_type="verify_state_update_recovery",
        reason_code="VERIFY_STATE_UPDATE_FAILED",
        orphan_result_ref="logs/verification/orphan.json",
        attempted_pointer_field="latest_verification_ref",
    )

    mark_state_update_recovery_resolved(tmp_path, ref, resolution="orphan_result_discarded")

    payload = json.loads((tmp_path / ref).read_text(encoding="utf-8"))
    assert payload["status"] == "resolved"
    assert payload["resolution"] == "orphan_result_discarded"
    assert payload["resolved_at"]


def _write_state(task_root: Path, *, blocked_transition: str, blocked_reason_ref: str) -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.PAUSED,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.REVIEW,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
            latest_checkpoint_ref="logs/checkpoints/checkpoint.json",
            latest_verification_ref=None,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=blocked_transition,
            blocked_reason_ref=blocked_reason_ref,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )


def test_state_update_recovery_can_record_orphan_adoption_without_state_mutation(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    orphan_ref = "logs/review/orphan.json"
    ref = record_state_update_recovery(
        logs_dir,
        namespace="review-recovery",
        record_type="review_state_update_recovery",
        reason_code="REVIEW_STATE_UPDATE_FAILED",
        orphan_result_ref=orphan_ref,
        attempted_pointer_field="latest_review_ref",
    )
    _write_state(tmp_path, blocked_transition="review_state_update", blocked_reason_ref=orphan_ref)

    mark_orphan_adoption_recorded(tmp_path, ref, orphan_ref)

    payload = json.loads((tmp_path / ref).read_text(encoding="utf-8"))
    state = read_state(tmp_path / "state.json")
    assert payload["status"] == "resolved"
    assert payload["resolution"] == "orphan_result_adopted"
    assert payload["adopted_result_ref"] == orphan_ref
    assert state.latest_review_ref is None
    assert state.blocked_transition == "review_state_update"


def test_state_update_recovery_can_adopt_orphan_as_latest_ref(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    orphan_ref = "logs/review/orphan.json"
    ref = record_state_update_recovery(
        logs_dir,
        namespace="review-recovery",
        record_type="review_state_update_recovery",
        reason_code="REVIEW_STATE_UPDATE_FAILED",
        orphan_result_ref=orphan_ref,
        attempted_pointer_field="latest_review_ref",
    )
    _write_state(tmp_path, blocked_transition="review_state_update", blocked_reason_ref=orphan_ref)

    adopted_ref = adopt_orphan_result_as_latest_ref(tmp_path, ref)

    payload = json.loads((tmp_path / ref).read_text(encoding="utf-8"))
    state = read_state(tmp_path / "state.json")
    assert adopted_ref == orphan_ref
    assert payload["status"] == "resolved"
    assert payload["resolution"] == "orphan_result_adopted"
    assert payload["adopted_result_ref"] == orphan_ref
    assert state.latest_review_ref == orphan_ref
    assert state.blocked_transition is None
    assert state.blocked_reason_ref is None
