from __future__ import annotations

import json
from pathlib import Path

from harness.shared.artifacts.state_artifact import read_state, write_state
from harness.shared.contracts.actions import CurrentStepRefSnapshot
from harness.shared.contracts.results import CheckItem, CheckpointResult, JudgementCode, NoteSignal, NoteTargetHint
from harness.shared.contracts.state import (
    CurrentPhase,
    HarnessCounters,
    HarnessState,
    SessionState,
    WorkflowMode,
)
from harness.shared.core.phase_spec_loader import load_phase_spec
from harness.shared.runtime.checkpoint_runtime import CheckpointRuntimeInput, persist_checkpoint_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_state(
    task_root: Path,
    phase: CurrentPhase = CurrentPhase.PLAN,
    current_step_ref: str | None = None,
    workflow_mode: WorkflowMode = WorkflowMode.GENERIC,
    repo_profile_ref: str | None = None,
) -> None:
    write_state(
        task_root / "state.json",
        HarnessState(
            schema_version=1,
            session_state=SessionState.ACTIVE,
            workflow_mode=workflow_mode,
            current_phase=phase,
            repo_profile_ref=repo_profile_ref,
            workspace_baseline_ref="logs/workspace-baseline.json",
            current_step_ref=current_step_ref,
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


def _plan_check_items(with_missing_first_basis: bool = False) -> list[CheckItem]:
    return _check_items("plan", with_missing_first_basis=with_missing_first_basis)


def _check_items(phase: str, with_missing_first_basis: bool = False) -> list[CheckItem]:
    items: list[CheckItem] = []
    for index, item_text in enumerate(load_phase_spec(phase, workspace_root=REPO_ROOT).checkpoint_items, start=1):
        basis_refs = [] if with_missing_first_basis and index == 1 else [f"plan.md#item-{index}"]
        items.append(
            CheckItem(
                item_index=index,
                item_text=item_text,
                result="YES",
                rationale=f"Evidence is present for item {index}.",
                basis_refs=basis_refs,
            )
        )
    return items


def _plan_check_items_with_paraphrased_text() -> list[CheckItem]:
    items = _plan_check_items()
    items[0].item_text = "Goal, Context, Expected Outcome alignment was checked."
    return items


def test_persist_checkpoint_runtime_writes_log_and_updates_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Plan is ready.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    checkpoint_ref = result["checkpoint_ref"]
    state = read_state(task_root / "state.json")
    payload = json.loads((task_root / str(checkpoint_ref)).read_text(encoding="utf-8"))

    assert result["reason_code"] is None
    assert state.latest_checkpoint_ref == checkpoint_ref
    assert not Path(str(checkpoint_ref)).is_absolute()
    assert state.last_updated != "2026-04-19T22:00:00+09:00"
    assert payload["checkpoint_ref"] == checkpoint_ref
    assert payload["phase"] == "plan"
    assert payload["judgement_code"] == "GO"
    assert len(payload["check_items"]) == 6
    assert payload["check_items"][0]["basis_refs"] == ["plan.md#item-1"]


def test_persist_checkpoint_runtime_records_guard_loaded_profile_context(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(
        task_root,
        workflow_mode=WorkflowMode.GUIDED,
        repo_profile_ref="contracts/repo_profile.md",
    )

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Plan is ready.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    payload = json.loads((task_root / str(result["checkpoint_ref"])).read_text(encoding="utf-8"))

    assert result["reason_code"] is None
    assert payload["repo_profile_context"] == {
        "profile_id": "workspace-default",
        "profile_version": 7,
        "applicable_checkpoint_supplements": [],
    }


def test_persist_checkpoint_runtime_allows_non_exact_item_text(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Plan is ready.",
                check_items=_plan_check_items_with_paraphrased_text(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] is None


def test_persist_checkpoint_runtime_blocks_phase_mismatch_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.IMPLEMENTATION,
                judgement_code=JudgementCode.GO,
                summary="Wrong phase.",
                basis_refs=["steps.md#s1"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_PHASE_MISMATCH"
    assert result["checkpoint_ref"] is None
    assert not (task_root / "logs" / "checkpoints").exists()
    assert read_state(task_root / "state.json").latest_checkpoint_ref is None


def test_persist_checkpoint_runtime_blocks_missing_state_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="No state.",
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "STATE_ARTIFACT_MISSING"
    assert result["message_summary"] == "`/wf-checkpoint` requires an initialized state.json artifact."
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_requires_workspace_root_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="No workspace root.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_WORKSPACE_ROOT_MISSING"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_invalid_judgement_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.DONE,
                summary="Done is not a checkpoint judgement.",
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_JUDGEMENT_INVALID"
    assert result["checkpoint_ref"] is None
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_empty_summary_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary=" ",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_RESULT_CONTRACT_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_note_signal_mismatch_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO_WITH_NOTE,
                summary="Missing note signal.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_NOTE_SIGNALS_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_note_target_invalid_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO_WITH_NOTE,
                summary="Wrong note target.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
                note_signals=[
                    NoteSignal(
                        note_text="Step-level follow-up.",
                        note_target_hint=NoteTargetHint.STEPS,
                        note_basis_refs=["steps.md#s1"],
                    )
                ],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_NOTE_TARGET_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_requires_reason_for_hold_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.HOLD,
                summary="Blocked.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_REASON_REQUIRED"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_snapshot_in_plan_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Unexpected snapshot.",
                check_items=_plan_check_items(),
                basis_refs=["plan.md#goal"],
                current_step_ref_snapshot=CurrentStepRefSnapshot(
                    step_ref="S1",
                    step_text="Do it.",
                    go_marker_present=True,
                ),
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_snapshot_mismatch_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root, phase=CurrentPhase.IMPLEMENTATION, current_step_ref="S1")

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.IMPLEMENTATION,
                judgement_code=JudgementCode.GO,
                summary="Wrong snapshot.",
                check_items=_check_items("implementation"),
                basis_refs=["steps.md#s2"],
                current_step_ref_snapshot=CurrentStepRefSnapshot(
                    step_ref="S2",
                    step_text="Do it.",
                    go_marker_present=True,
                ),
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_unsupported_phase_without_log(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root, phase=CurrentPhase.REVIEW)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.REVIEW,
                judgement_code=JudgementCode.DONE,
                summary="Unsupported.",
                check_items=_check_items("review"),
                basis_refs=["review.md#summary"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_PHASE_UNSUPPORTED"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_blocks_unavailable_phase_spec_without_log(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=workspace_root,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="No phase spec.",
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_PHASE_SPEC_UNAVAILABLE"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_requires_complete_phase_check_items(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Incomplete check.",
                check_items=_plan_check_items()[:-1],
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_CHECK_ITEMS_INCOMPLETE"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_requires_yes_basis_refs(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Missing item evidence.",
                check_items=_plan_check_items(with_missing_first_basis=True),
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_CHECK_ITEM_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_persist_checkpoint_runtime_rejects_unknown_check_item_result(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    (task_root / "logs").mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    _write_state(task_root)
    check_items = _plan_check_items()
    check_items[0].result = "MAYBE"

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="Invalid item result.",
                check_items=check_items,
                basis_refs=["plan.md#goal"],
            ),
        )
    )

    assert result["reason_code"] == "CHECKPOINT_CHECK_ITEM_INVALID"
    assert not (task_root / "logs" / "checkpoints").exists()


def test_checkpoint_runtime_input_accepts_json_payload(tmp_path: Path) -> None:
    input_data = CheckpointRuntimeInput(
        task_root=tmp_path,
        checkpoint_result={
            "checkpoint_ref": "",
            "phase": "plan",
            "judgement_code": "GO",
            "summary": "Ready.",
            "check_items": [],
            "basis_refs": [],
            "note_signals": [],
            "stop_condition_code": None,
            "primary_cause_code": None,
            "reason_fingerprint": None,
            "current_step_ref_snapshot": None,
        },
    )

    assert input_data.checkpoint_result.phase == CurrentPhase.PLAN
    assert input_data.checkpoint_result.judgement_code == JudgementCode.GO
