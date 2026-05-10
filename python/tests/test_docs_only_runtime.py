from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

from harness.runtime_cli import main
from harness.shared.contracts.results import CheckItem, CheckpointResult, JudgementCode
from harness.shared.contracts.state import CurrentPhase
from harness.shared.runtime.checkpoint_runtime import CheckpointRuntimeInput, persist_checkpoint_runtime
from harness.shared.runtime.docs_only_runtime import DocsOnlyRuntimeInput, execute_docs_only_runtime
from harness.shared.runtime.next_runtime import NextRuntimeInput, execute_next_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def _docs_event(task_root: Path, event: str, summary: str = "event summary", artifact_ref: str | None = None):
    return execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event=event,
            summary=summary,
            artifact_ref=artifact_ref,
        )
    )


def test_docs_only_start_creates_state_without_runbook_artifacts(tmp_path: Path) -> None:
    task_root = tmp_path / "task"

    result = execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="README 문서만 정리",
            target_doc_refs=["README.md"],
            summary="문서 정리 논의를 시작한다.",
        )
    )

    payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    assert result["reason_code"] is None
    assert result["docs_state"] == "discussion"
    assert payload["schema_version"] == 1
    assert payload["workflow_kind"] == "docs_only"
    assert payload["docs_state"] == "discussion"
    assert payload["target_doc_refs"] == ["README.md"]
    assert payload["last_event_ref"].startswith("logs/docs-only/")
    assert (task_root / payload["last_event_ref"]).exists()
    assert not (task_root / "plan.md").exists()
    assert not (task_root / "steps.md").exists()


def test_docs_only_transition_sequence_records_stage_refs(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )

    proposal = _docs_event(task_root, "present_proposal", artifact_ref="logs/proposal.md")
    accepted = _docs_event(task_root, "accept_proposal")
    diff = _docs_event(task_root, "present_diff", artifact_ref="logs/diff.patch")
    applied = _docs_event(task_root, "apply", artifact_ref="README.md")

    payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    assert proposal["previous_docs_state"] == "discussion"
    assert proposal["docs_state"] == "proposal_visualized"
    assert accepted["docs_state"] == "proposal_accepted"
    assert diff["docs_state"] == "diff_presented"
    assert applied["docs_state"] == "applied"
    assert payload["proposal_ref"] == "logs/proposal.md"
    assert payload["diff_ref"] == "logs/diff.patch"
    assert payload["applied_ref"] == "README.md"
    assert len(payload["event_history_refs"]) == 5


def test_docs_only_blocks_skipped_transition(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )

    result = _docs_event(task_root, "present_diff")

    assert result["reason_code"] == "DOCS_ONLY_TRANSITION_INVALID"
    assert result["docs_state"] == "discussion"


def test_docs_only_rejects_non_object_state_json(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "state.json").write_text("[]\n", encoding="utf-8")

    result = _docs_event(task_root, "present_proposal")

    assert result["reason_code"] == "DOCS_ONLY_STATE_INVALID"


def test_docs_only_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )
    payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    (task_root / "state.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = _docs_event(task_root, "present_proposal")

    assert result["reason_code"] == "DOCS_ONLY_STATE_INVALID"


def test_docs_only_start_reports_runbook_artifact_before_existing_state(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (task_root / "state.json").write_text("{}\n", encoding="utf-8")

    result = execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )

    assert result["reason_code"] == "DOCS_ONLY_RUNBOOK_ARTIFACT_PRESENT"


def test_docs_only_transition_merges_adapter_meta(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
            adapter_meta={"adapter": "codex", "attempt": 1},
        )
    )

    result = execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="present_proposal",
            summary="proposal",
            adapter_meta={"attempt": 2, "surface": "skill"},
        )
    )

    payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    assert result["reason_code"] is None
    assert payload["adapter_meta"] == {"adapter": "codex", "attempt": 2, "surface": "skill"}


def test_docs_only_state_update_failure_removes_orphan_event_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import harness.shared.runtime.docs_only_runtime as docs_only_runtime

    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )
    original_payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))

    def fail_state_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated state write failure")

    monkeypatch.setattr(docs_only_runtime, "_write_docs_state", fail_state_write)

    result = _docs_event(task_root, "present_proposal")
    current_payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    log_files = sorted((task_root / "logs/docs-only").glob("*.json"))

    assert result["reason_code"] == "DOCS_ONLY_STATE_UPDATE_FAILED"
    assert current_payload == original_payload
    assert len(log_files) == 1


def test_docs_only_blocks_runbook_approval_event(tmp_path: Path) -> None:
    result = execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=tmp_path / "task",
            event="GO",
            summary="runbook 승인 토큰",
        )
    )

    assert result["reason_code"] == "DOCS_ONLY_RUNBOOK_APPROVAL_BLOCKED"
    assert not (tmp_path / "task").exists()


def test_docs_only_blocks_awaiting_approval_state_payload(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    (task_root / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow_kind": "docs_only",
                "docs_state": "proposal_visualized",
                "session_state": "awaiting_approval",
                "pending_approval_for": "plan_to_implementation",
                "user_request": "문서 변경",
                "target_doc_refs": [],
                "proposal_ref": None,
                "diff_ref": None,
                "applied_ref": None,
                "last_event_ref": None,
                "event_history_refs": [],
                "last_updated": "2026-05-10 12:00:00 KST",
                "adapter_meta": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _docs_event(task_root, "accept_proposal")

    assert result["reason_code"] == "DOCS_ONLY_RUNBOOK_APPROVAL_BLOCKED"


def test_runbook_next_blocks_docs_only_state_without_rewriting(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )
    original_payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))

    result = execute_next_runtime(
        NextRuntimeInput(
            task_root=task_root,
            source="approval",
            current_phase=CurrentPhase.PLAN,
            pending_approval_for=None,
            resolved_result_ref=None,
            judgement_code=JudgementCode.DONE,
        )
    )

    assert result.reason_code == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_payload
    assert not (task_root / "state.json.v1.bak").exists()


def test_runbook_checkpoint_blocks_docs_only_state_without_rewriting(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    execute_docs_only_runtime(
        DocsOnlyRuntimeInput(
            task_root=task_root,
            event="start",
            workflow_kind="docs_only",
            workflow_kind_resolved=True,
            user_request="문서 변경",
        )
    )
    original_payload = json.loads((task_root / "state.json").read_text(encoding="utf-8"))

    result = persist_checkpoint_runtime(
        CheckpointRuntimeInput(
            task_root=task_root,
            workspace_root=REPO_ROOT,
            checkpoint_result=CheckpointResult(
                checkpoint_ref="",
                phase=CurrentPhase.PLAN,
                judgement_code=JudgementCode.GO,
                summary="checkpoint",
                check_items=[
                    CheckItem(
                        item_index=1,
                        item_text="placeholder",
                        result="YES",
                        rationale="placeholder",
                        basis_refs=["state.json"],
                    )
                ],
            ),
        )
    )

    assert result["reason_code"] == "STATE_ARTIFACT_INVALID"
    assert json.loads((task_root / "state.json").read_text(encoding="utf-8")) == original_payload
    assert not (task_root / "state.json.v1.bak").exists()


def test_docs_only_runtime_cli_dispatches(monkeypatch, capsys, tmp_path: Path) -> None:
    task_root = tmp_path / "cli-task"
    payload = {
        "task_root": str(task_root),
        "event": "start",
        "workflow_kind": "docs_only",
        "workflow_kind_resolved": True,
        "user_request": "문서 변경",
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-docs-only-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["reason_code"] is None
    assert captured["docs_state"] == "discussion"
    assert (task_root / "state.json").exists()
