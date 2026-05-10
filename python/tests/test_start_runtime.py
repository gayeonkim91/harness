from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

from harness.runtime_cli import main
from harness.shared.artifacts.plan_artifact import read_plan_current_state, scaffold_plan
from harness.shared.artifacts.state_artifact import read_state
from harness.shared.runtime.start_runtime import StartRuntimeInput, execute_start_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_scaffold_plan_omits_current_state_section(tmp_path: Path) -> None:
    plan_path = scaffold_plan(tmp_path, "plan-smoke")

    content = plan_path.read_text(encoding="utf-8")
    assert "## Current State" not in content
    assert "## References" in content
    assert "## Contract Notes" in content


def test_execute_start_runtime_blocks_reinitialization(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()
    first = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="start-smoke",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="첫 시작",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )
    second = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="start-smoke",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="다시 시작",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert first["reason_code"] is None
    assert second["reason_code"] == "START_TASK_ALREADY_INITIALIZED"
    assert second["created_artifacts"] == []
    state = read_state(task_root / "state.json")
    current = read_plan_current_state(task_root / "plan.md")
    assert state.workspace_baseline_ref == "logs/workspace-baseline.json"
    assert not Path(state.workspace_baseline_ref).is_absolute()
    assert (task_root / state.workspace_baseline_ref).exists()
    assert current is not None
    assert current.session_state == state.session_state
    assert current.current_phase == state.current_phase
    assert current.workspace_baseline_ref == "logs/workspace-baseline.json"


def test_execute_start_runtime_initializes_generic_verification_contract(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="verification-contract",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="검증 계약 생성",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    plan = (task_root / "plan.md").read_text(encoding="utf-8")
    assert result["reason_code"] is None
    assert "- Gate Policy:" in plan
    assert "initialized_by: wf-start" in plan
    assert "adoption_kind: unknown" in plan
    assert "task_classification: generic" in plan
    assert "gate_source: generic fallback" in plan
    assert "Task-appropriate verification gate" in plan
    assert "<define before verification>" in plan


def test_execute_start_runtime_blocks_non_runbook_without_artifacts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="docs-only",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="docs_only",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="README 문서만 정리",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not (task_root / "plan.md").exists()
    assert not (task_root / "steps.md").exists()
    assert not (task_root / "state.json").exists()
    assert not (task_root / "logs").exists()


def test_execute_start_runtime_blocks_missing_workflow_kind_without_artifacts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="missing-kind",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="분류 누락",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_blocks_discussion_only_without_artifacts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="discussion-only",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="discussion_only",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="방향만 논의",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_blocks_explicit_unknown_kind_without_artifacts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="unknown-kind",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="unknown",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="애매한 요청",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_blocks_docs_path_clue_without_kind_hint(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="docs-path",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="README 문서만 정리",
            request_path_refs=["README.md"],
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_blocks_runbook_hint_with_docs_only_paths(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="docs-path-conflict",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="runbook",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="README 문서만 정리",
            request_path_refs=["docs/python/guide.md"],
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_allows_runbook_hint_with_mixed_code_docs_paths(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="mixed-runbook",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="runbook",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="코드 변경 후 문서 갱신",
            request_path_refs=["src/service.py", "docs/guide.md"],
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] is None
    assert (task_root / "plan.md").exists()
    assert (task_root / "steps.md").exists()
    assert (task_root / "state.json").exists()
    assert (task_root / "logs").exists()


def test_execute_start_runtime_blocks_runbook_hint_with_txt_doc_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="txt-doc",
            workflow_mode="generic",
            repo_profile_ref=None,
            workflow_kind="runbook",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="notes.txt만 정리",
            request_path_refs=["notes.txt"],
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_NOT_RUNBOOK"
    assert result["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_uses_guided_adoption_verification_template(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    profile_path = workspace_root / "contracts" / "repo_profile.md"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        """# Test Profile

```yaml
profile_id: test-profile
profile_version: 1
project_context:
  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - greenfield
  initialization_requirements:
    greenfield:
      doc_rules: []
guided_classifications:
  simple_local:
    token: simple_local
    default_initial_phase_hint: plan
    minimum_read_set_default: []
    minimum_read_set_extensions: []
known_issue_selector_mapping: []
checkpoint_supplements: {}
verification_gate_templates:
  greenfield:
    required_gates:
      - name: Profile smoke gate
        command: ./scripts/smoke-check
        working_directory: .
        success_criteria: smoke exits 0
        evidence: smoke output summary
    conditional_gates:
      - condition: public API changed
        gate: run API scenario check
    manual_checks:
      - check: inspect generated entry point
        evidence: note reviewed files
```
""",
        encoding="utf-8",
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="guided-verification-contract",
            workflow_mode="generic",
            repo_profile_ref=None,
            explicit_repo_profile_ref="contracts/repo_profile.md",
            task_classification="simple_local",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="guided 검증 계약 생성",
            adoption_kind="greenfield",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    plan = (task_root / "plan.md").read_text(encoding="utf-8")
    assert result["reason_code"] is None
    assert "adoption_kind: greenfield" in plan
    assert "task_classification: simple_local" in plan
    assert "gate_source: repo_profile.verification_gate_templates" in plan
    assert "name: Profile smoke gate" in plan
    assert "command: ./scripts/smoke-check" in plan
    assert "condition: public API changed" in plan
    assert "check: inspect generated entry point" in plan


def test_runtime_cli_rejects_invalid_minimum_read_set(monkeypatch, capsys, tmp_path: Path) -> None:
    payload = {
        "task_root": str(tmp_path / "cli-invalid"),
        "task_name": "cli-invalid",
        "workflow_mode": "generic",
        "repo_profile_ref": None,
        "task_classification": "generic",
        "initial_phase": "plan",
        "minimum_read_set": [
            {
                "read_target_kind": "not-a-kind",
                "doc_path": "templates/project/architecture.md",
                "selector_type": "header_set",
                "section_selector": ["시스템 개요"],
                "why": "invalid enum smoke",
            }
        ],
        "phase_doc_ref": "phases/plan.md",
        "user_request": "입력 검증",
        "workspace_root": str(REPO_ROOT),
        "workflow_mode_resolved": True,
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-start-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["reason_code"] == "START_INPUT_CONTRACT_INVALID"
    assert captured["created_artifacts"] == []


def test_runtime_cli_blocks_missing_workflow_kind(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "cli-missing-kind"
    workspace_root.mkdir()
    payload = {
        "task_root": str(task_root),
        "task_name": "cli-missing-kind",
        "workflow_mode": "generic",
        "repo_profile_ref": None,
        "task_classification": "generic",
        "initial_phase": "plan",
        "minimum_read_set": [],
        "phase_doc_ref": "phases/plan.md",
        "user_request": "분류 누락",
        "workspace_root": str(workspace_root),
        "workflow_mode_resolved": True,
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-start-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["reason_code"] == "START_NOT_RUNBOOK"
    assert captured["created_artifacts"] == []
    assert not task_root.exists()


def test_runtime_cli_blocks_invalid_workflow_kind_as_not_runbook(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "cli-invalid-kind"
    workspace_root.mkdir()
    payload = {
        "task_root": str(task_root),
        "task_name": "cli-invalid-kind",
        "workflow_mode": "generic",
        "repo_profile_ref": None,
        "workflow_kind": "not-a-kind",
        "task_classification": "generic",
        "initial_phase": "plan",
        "minimum_read_set": [],
        "phase_doc_ref": "phases/plan.md",
        "user_request": "분류 오류",
        "workspace_root": str(workspace_root),
        "workflow_mode_resolved": True,
    }
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-start-runtime"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["reason_code"] == "START_NOT_RUNBOOK"
    assert captured["created_artifacts"] == []
    assert not task_root.exists()


def test_execute_start_runtime_re_resolves_caller_generic_in_profile_workspace(tmp_path: Path) -> None:
    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="mode-conflict",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="mode 검사",
            workflow_kind="runbook",
            workspace_root=REPO_ROOT,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_PROJECT_CONTEXT_UNRESOLVED"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_blocks_missing_user_request(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path / "task",
            task_name="missing-request",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_REQUEST_MISSING"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_requires_workspace_root(tmp_path: Path) -> None:
    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path / "task",
            task_name="missing-workspace-root",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="workspace_root 없음",
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_WORKSPACE_ROOT_MISSING"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_blocks_unavailable_explicit_profile(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path / "task",
            task_name="missing-profile",
            workflow_mode="generic",
            repo_profile_ref=None,
            explicit_repo_profile_ref="contracts/missing_profile.md",
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="profile 없음",
            adoption_kind="legacy-medium",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_REPO_PROFILE_UNAVAILABLE"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_blocks_invalid_initial_phase(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path / "task",
            task_name="invalid-phase",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="implementation",
            minimum_read_set=[],
            phase_doc_ref="phases/implementation.md",
            user_request="잘못된 phase",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_INITIAL_PHASE_INVALID"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_blocks_unwritable_task_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("file\n", encoding="utf-8")

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=parent_file / "task",
            task_name="unwritable",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="쓰기 실패",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    assert result["reason_code"] == "START_TASK_ROOT_UNWRITABLE"
    assert result["created_artifacts"] == []


def test_execute_start_runtime_writes_canonical_initial_state(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    task_root = tmp_path / "task"
    workspace_root.mkdir()

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=task_root,
            task_name="state-snapshot",
            workflow_mode="generic",
            repo_profile_ref=None,
            task_classification="generic",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="state 확인",
            workflow_kind="runbook",
            workspace_root=workspace_root,
            workflow_mode_resolved=True,
        )
    )

    state = json.loads((task_root / "state.json").read_text(encoding="utf-8"))
    assert result["reason_code"] is None
    assert state["schema_version"] == 2
    assert state["session_state"] == "in_progress"
    assert state["workflow_mode"] == "generic"
    assert state["current_phase"] == "plan"
    assert state["repo_profile_ref"] is None
    assert state["workspace_baseline_ref"] == "logs/workspace-baseline.json"
    assert (task_root / state["workspace_baseline_ref"]).exists()
    assert state["current_step_ref"] is None
    assert state["latest_checkpoint_ref"] is None
    assert state["latest_verification_ref"] is None
    assert state["latest_review_ref"] is None
    assert state["pending_approval_for"] is None
    assert state["review_outcome"] is None
    assert state["closure_authorized"] is False
    assert state["counters"] == {"rework_count": 0, "rewrite_count": 0, "rollback_count": 0}
    assert state["blocked_transition"] is None
    assert state["blocked_reason_ref"] is None
    assert state["stop_condition_ref"] is None
    assert state["last_updated"].endswith(" KST")
    assert state["approvals_granted"] == []
    assert state["adapter_meta"] == {}
