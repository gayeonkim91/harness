from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from harness.shared.artifacts.plan_artifact import (
    apply_plan_current_state_to_harness_state,
    parse_plan_current_state,
    plan_current_state_from_harness_state,
    read_plan_current_state,
    render_plan_current_state,
    write_plan_current_state,
)
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode


def _state() -> HarnessState:
    return HarnessState(
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
        counters=HarnessCounters(rework_count=1),
        blocked_transition=None,
        blocked_reason_ref=None,
        stop_condition_ref=None,
        last_updated="2026-05-10 12:00:00 KST",
        approvals_granted=[1],
        adapter_meta={},
    )


def test_write_plan_current_state_replaces_only_current_state_section(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(
        "# Plan\n\n"
        "## Goal\n"
        "Keep this goal.\n\n"
        "## 현재 상태 (Current State)\n"
        "- schema_version: 2\n"
        "- session_state: draft\n"
        "- workflow_mode: generic\n"
        "- current_phase: pre-planning\n"
        "- closure_authorized: false\n"
        "- counters.rework_count: 0\n"
        "- counters.rewrite_count: 0\n"
        "- counters.rollback_count: 0\n"
        "- approvals_granted: []\n"
        "- last_updated: 2026-05-10 11:00:00 KST\n\n"
        "## Scope\n"
        "Keep this scope.\n",
        encoding="utf-8",
    )

    write_plan_current_state(plan_path, plan_current_state_from_harness_state(_state()))

    content = plan_path.read_text(encoding="utf-8")
    current = read_plan_current_state(plan_path)
    assert "Keep this goal." in content
    assert "Keep this scope." in content
    assert "## Current State" in content
    assert "## 현재 상태 (Current State)" not in content
    assert "\n\n## Scope\n" in content
    assert current is not None
    assert current.session_state == SessionState.IN_PROGRESS
    assert current.latest_checkpoint_ref == "logs/checkpoints/checkpoint.json"
    assert current.approvals_granted == [1]


def test_write_plan_current_state_inserts_after_plan_title(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n\n## Goal\nBody.\n", encoding="utf-8")

    write_plan_current_state(plan_path, plan_current_state_from_harness_state(_state()))

    content = plan_path.read_text(encoding="utf-8")
    assert content.startswith("# Plan\n\n## Current State\n")
    assert "\n## Goal\nBody.\n" in content


def test_parse_plan_current_state_ignores_display_current_step_and_latest_checkpoint_names() -> None:
    current = parse_plan_current_state(
        "## Current State\n"
        "- schema_version: 2\n"
        "- session_state: in_progress\n"
        "- workflow_mode: generic\n"
        "- current_phase: implementation\n"
        "- repo_profile_ref:\n"
        "- workspace_baseline_ref: logs/workspace-baseline.json\n"
        "- current_step: S1\n"
        "- latest_checkpoint: logs/checkpoints/checkpoint.json\n"
        "- current_step_ref: S2\n"
        "- latest_checkpoint_ref: logs/checkpoints/machine.json\n"
        "- pending_approval_for:\n"
        "- closure_authorized: false\n"
        "- counters.rework_count: 0\n"
        "- approvals_granted: [1, 2]\n"
        "- last_updated: 2026-05-10 12:00:00 KST\n"
    )

    assert current is not None
    assert current.current_step_ref == "S2"
    assert current.latest_checkpoint_ref == "logs/checkpoints/machine.json"
    assert "current_step_ref" in current.present_fields
    assert "latest_checkpoint_ref" in current.present_fields
    assert "current_step" in current.present_fields
    assert "latest_checkpoint" in current.present_fields
    assert current.counters_rework_count == 0
    assert current.counters_rewrite_count is None
    assert current.approvals_granted == [1, 2]


def test_partial_current_state_only_overrides_present_fields() -> None:
    state = _state()
    state.current_step_ref = "S0"
    current = parse_plan_current_state(
        "## 현재 상태 (Current State)\n"
        "- session_state: paused\n"
        "- current_phase:\n"
        "- current_step: 해당 없음\n"
        "- pending_approval_for:\n"
        "- latest_checkpoint: logs/checkpoints/from-plan.json\n"
        "- counters.rework_count: 3\n"
        "- approvals_granted:\n"
        "- last_updated:\n"
    )

    assert current is not None
    reconciled = apply_plan_current_state_to_harness_state(state, current)

    assert reconciled.session_state == SessionState.PAUSED
    assert reconciled.current_phase == CurrentPhase.PLAN
    assert reconciled.workflow_mode == WorkflowMode.GENERIC
    assert reconciled.workspace_baseline_ref == "logs/workspace-baseline.json"
    assert reconciled.current_step_ref == "S0"
    assert reconciled.latest_checkpoint_ref == "logs/checkpoints/checkpoint.json"
    assert reconciled.counters.rework_count == 3
    assert reconciled.counters.rewrite_count == 0
    assert reconciled.approvals_granted == [1]
    assert reconciled.last_updated == "2026-05-10 12:00:00 KST"


def test_plan_current_state_projection_is_immutable_from_source_state() -> None:
    state = _state()
    current = plan_current_state_from_harness_state(state)
    state.approvals_granted.append(2)
    state.counters.rework_count = 99

    assert current.approvals_granted == [1]
    assert current.counters_rework_count == 1
    assert replace(current, approvals_granted=[1, 2]).approvals_granted == [1, 2]


def test_plan_current_state_round_trips_all_state_fields() -> None:
    state = _state()
    state.session_state = SessionState.PAUSED
    state.current_step_ref = "S1"
    state.latest_verification_ref = "logs/verification/verification.json"
    state.blocked_transition = "wf-next"
    state.stop_condition_ref = "logs/stop.json"

    current = parse_plan_current_state(render_plan_current_state(plan_current_state_from_harness_state(state)))

    assert current is not None
    assert apply_plan_current_state_to_harness_state(state, current) == state
