from __future__ import annotations

from pathlib import Path

from harness.shared.artifacts.state_artifact import (
    apply_deferred_transition_with_apply_result,
    apply_immediate_transition,
    read_state,
    write_state,
)
from harness.shared.contracts.results import ApplyResult, ApplyStatus
from harness.shared.contracts.state import (
    CurrentPhase,
    DeferredStateTransition,
    HarnessCounters,
    HarnessState,
    WorkflowMode,
    SessionState,
)


def test_apply_deferred_transition_sets_current_step_ref_from_apply_result(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    write_state(
        state_path,
        HarnessState(
            schema_version=1,
            session_state=SessionState.ACTIVE,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.IMPLEMENTATION,
            repo_profile_ref=None,
            workspace_baseline_ref="baseline.json",
            current_step_ref="S0",
            latest_checkpoint_ref=None,
            latest_verification_ref=None,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    apply_deferred_transition_with_apply_result(
        state_path,
        DeferredStateTransition(
            session_state=SessionState.ACTIVE,
            current_phase=CurrentPhase.IMPLEMENTATION,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(rewrite_count=1),
        ),
        ApplyResult(
            apply_status=ApplyStatus.APPLIED,
            reason_code=None,
            current_step_ref_update_mode="set",
            resolved_current_step_ref="S1",
        ),
    )

    state = read_state(state_path)
    assert state.current_step_ref == "S1"
    assert state.counters.rewrite_count == 1


def test_apply_deferred_transition_applies_noop_result(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    write_state(
        state_path,
        HarnessState(
            schema_version=1,
            session_state=SessionState.ACTIVE,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.IMPLEMENTATION,
            repo_profile_ref=None,
            workspace_baseline_ref="baseline.json",
            current_step_ref="S0",
            latest_checkpoint_ref=None,
            latest_verification_ref=None,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    apply_deferred_transition_with_apply_result(
        state_path,
        DeferredStateTransition(
            session_state=SessionState.ACTIVE,
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for="verification_entry",
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
        ),
        ApplyResult(
            apply_status=ApplyStatus.NOOP,
            reason_code=None,
            current_step_ref_update_mode="unchanged",
            resolved_current_step_ref=None,
        ),
    )

    state = read_state(state_path)
    assert state.current_phase == CurrentPhase.VERIFICATION
    assert state.pending_approval_for == "verification_entry"
    assert state.current_step_ref is None


def test_apply_deferred_transition_ignores_set_for_non_step_phase(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    write_state(
        state_path,
        HarnessState(
            schema_version=1,
            session_state=SessionState.ACTIVE,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.IMPLEMENTATION,
            repo_profile_ref=None,
            workspace_baseline_ref="baseline.json",
            current_step_ref="S0",
            latest_checkpoint_ref=None,
            latest_verification_ref=None,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    apply_deferred_transition_with_apply_result(
        state_path,
        DeferredStateTransition(
            session_state=SessionState.AWAITING_APPROVAL,
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for="verification_entry",
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
        ),
        ApplyResult(
            apply_status=ApplyStatus.APPLIED,
            reason_code=None,
            current_step_ref_update_mode="set",
            resolved_current_step_ref="S1",
        ),
    )

    state = read_state(state_path)
    assert state.current_phase == CurrentPhase.VERIFICATION
    assert state.current_step_ref is None


def test_apply_immediate_transition_clears_current_step_ref_for_non_step_phases(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    write_state(
        state_path,
        HarnessState(
            schema_version=1,
            session_state=SessionState.ACTIVE,
            workflow_mode=WorkflowMode.GUIDED,
            current_phase=CurrentPhase.IMPLEMENTATION,
            repo_profile_ref=None,
            workspace_baseline_ref="baseline.json",
            current_step_ref="S1",
            latest_checkpoint_ref=None,
            latest_verification_ref=None,
            latest_review_ref=None,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-04-19T22:00:00+09:00",
            adapter_meta={},
        ),
    )

    apply_immediate_transition(
        state_path,
        DeferredStateTransition(
            session_state=SessionState.ACTIVE,
            current_phase=CurrentPhase.REVIEW,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
        ),
    )

    assert read_state(state_path).current_step_ref is None
