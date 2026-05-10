from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from harness.shared.artifacts.plan_artifact import plan_current_state_from_harness_state, write_plan_current_state
from harness.shared.artifacts.state_artifact import (
    apply_deferred_transition_with_apply_result,
    apply_immediate_transition,
    read_state,
    reconcile_state_from_plan,
    write_state,
)
import harness.shared.artifacts.state_artifact as state_artifact
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
            session_state=SessionState.IN_PROGRESS,
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
            session_state=SessionState.IN_PROGRESS,
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
            session_state=SessionState.IN_PROGRESS,
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
            session_state=SessionState.IN_PROGRESS,
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for=None,
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
    assert state.pending_approval_for is None
    assert state.current_step_ref is None


def test_apply_deferred_transition_ignores_set_for_non_step_phase(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    write_state(
        state_path,
        HarnessState(
            schema_version=1,
            session_state=SessionState.IN_PROGRESS,
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
            session_state=SessionState.IN_PROGRESS,
            current_phase=CurrentPhase.VERIFICATION,
            pending_approval_for=None,
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
            session_state=SessionState.IN_PROGRESS,
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
            session_state=SessionState.IN_PROGRESS,
            current_phase=CurrentPhase.REVIEW,
            pending_approval_for=None,
            review_outcome=None,
            closure_authorized=False,
            counters=HarnessCounters(),
        ),
    )

    assert read_state(state_path).current_step_ref is None


def test_write_state_upserts_plan_current_state_mirror(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n\n## Goal\nBody.\n", encoding="utf-8")

    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
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
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[1],
            adapter_meta={},
        ),
    )

    content = plan_path.read_text(encoding="utf-8")
    assert "## Current State" in content
    assert "- latest_checkpoint_ref: logs/checkpoints/checkpoint.json" in content
    assert "- approvals_granted: [1]" in content


def test_read_state_uses_plan_current_state_without_writing_state_json(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
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
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )
    current = plan_current_state_from_harness_state(read_state(state_path))
    write_plan_current_state(
        plan_path,
        replace(
            current,
            session_state=SessionState.PAUSED,
            current_phase=CurrentPhase.REVIEW,
            current_step_ref=None,
            latest_checkpoint_ref="logs/checkpoints/from-plan.json",
            counters_rework_count=2,
            blocked_transition="manual-pause",
            blocked_reason_ref="plan.md#current-state",
            approvals_granted=[1, 2],
            last_updated="2026-05-10 13:00:00 KST",
        ),
    )

    reconciled = read_state(state_path)

    assert reconciled.session_state == SessionState.PAUSED
    assert reconciled.current_phase == CurrentPhase.REVIEW
    assert reconciled.latest_checkpoint_ref == "logs/checkpoints/from-plan.json"
    assert reconciled.counters.rework_count == 2
    assert reconciled.approvals_granted == [1, 2]
    assert read_state(state_path).last_updated == "2026-05-10 13:00:00 KST"
    assert json.loads(state_path.read_text(encoding="utf-8"))["current_phase"] == "plan"


def test_explicit_reconcile_state_from_plan_updates_state_json_mirror(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
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
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )
    current = plan_current_state_from_harness_state(read_state(state_path))
    write_plan_current_state(plan_path, replace(current, current_phase=CurrentPhase.REVIEW))

    reconciled = reconcile_state_from_plan(state_path)

    assert reconciled.current_phase == CurrentPhase.REVIEW
    assert json.loads(state_path.read_text(encoding="utf-8"))["current_phase"] == "review"


def test_explicit_reconcile_state_from_plan_skips_write_when_mirror_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
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
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )

    def fail_json_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected state.json write")

    monkeypatch.setattr(state_artifact, "_write_state_json", fail_json_write)

    reconciled = reconcile_state_from_plan(state_path)

    assert reconciled.current_phase == CurrentPhase.PLAN


def test_write_state_updates_plan_before_state_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
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
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )
    original_payload = json.loads(state_path.read_text(encoding="utf-8"))

    def fail_plan_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated plan write failure")

    monkeypatch.setattr(state_artifact, "write_plan_current_state", fail_plan_write)

    with pytest.raises(OSError):
        write_state(
            state_path,
            HarnessState(
                schema_version=2,
                session_state=SessionState.PAUSED,
                workflow_mode=WorkflowMode.GENERIC,
                current_phase=CurrentPhase.REVIEW,
                repo_profile_ref=None,
                workspace_baseline_ref="logs/workspace-baseline.json",
                current_step_ref=None,
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
                last_updated="2026-05-10 13:00:00 KST",
                approvals_granted=[],
                adapter_meta={},
            ),
        )

    assert json.loads(state_path.read_text(encoding="utf-8")) == original_payload


def test_write_state_treats_state_json_failure_as_mirror_failure_when_plan_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.md"
    state_path = tmp_path / "state.json"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    write_state(
        state_path,
        HarnessState(
            schema_version=2,
            session_state=SessionState.IN_PROGRESS,
            workflow_mode=WorkflowMode.GENERIC,
            current_phase=CurrentPhase.PLAN,
            repo_profile_ref=None,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=None,
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
            last_updated="2026-05-10 12:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )
    original_payload = json.loads(state_path.read_text(encoding="utf-8"))

    def fail_json_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated state.json mirror failure")

    monkeypatch.setattr(state_artifact, "_write_state_json", fail_json_write)

    write_state(
        state_path,
        HarnessState(
            schema_version=2,
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
            blocked_transition=None,
            blocked_reason_ref=None,
            stop_condition_ref=None,
            last_updated="2026-05-10 13:00:00 KST",
            approvals_granted=[],
            adapter_meta={},
        ),
    )

    assert json.loads(state_path.read_text(encoding="utf-8")) == original_payload
    assert read_state(state_path).current_phase == CurrentPhase.REVIEW
    assert read_state(state_path).latest_checkpoint_ref == "logs/checkpoints/checkpoint.json"


def test_write_state_raises_state_json_failure_when_plan_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"

    def fail_json_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated state.json canonical failure")

    monkeypatch.setattr(state_artifact, "_write_state_json", fail_json_write)

    with pytest.raises(OSError):
        write_state(
            state_path,
            HarnessState(
                schema_version=2,
                session_state=SessionState.PAUSED,
                workflow_mode=WorkflowMode.GENERIC,
                current_phase=CurrentPhase.REVIEW,
                repo_profile_ref=None,
                workspace_baseline_ref="logs/workspace-baseline.json",
                current_step_ref=None,
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
                last_updated="2026-05-10 13:00:00 KST",
                approvals_granted=[],
                adapter_meta={},
            ),
        )
