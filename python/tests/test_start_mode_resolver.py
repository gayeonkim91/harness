from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

from harness.runtime_cli import main
from harness.shared.core.repo_profile_loader import load_repo_profile
from harness.shared.core.start_mode_resolver import StartModeResolverInput, resolve_start_mode
from harness.shared.contracts.state import WorkflowMode
from harness.shared.contracts.workflow import WorkflowKind
from harness.shared.runtime import start_runtime as start_runtime_module
from harness.shared.runtime.start_runtime import StartRuntimeInput, execute_start_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_start_mode_uses_workspace_convention() -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
        )
    )

    assert result.workflow_mode == WorkflowMode.GUIDED
    assert result.repo_profile_ref == "contracts/repo_profile.md"
    assert result.adoption_kind == "legacy-medium"
    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_mode_resolved is True
    assert result.resolution_source == "workspace_convention"


def test_resolve_start_mode_falls_back_to_generic_without_profile(tmp_path: Path) -> None:
    result = resolve_start_mode(StartModeResolverInput(workspace_root=tmp_path, adoption_kind="legacy-large"))

    assert result.workflow_mode == WorkflowMode.GENERIC
    assert result.repo_profile_ref is None
    assert result.adoption_kind is None
    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_mode_resolved is True
    assert result.resolution_source == "no_active_profile"


def test_resolve_start_mode_keeps_explicit_profile_for_guard_validation(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            explicit_repo_profile_ref="contracts/missing_profile.md",
            adoption_kind="legacy-medium",
        )
    )

    assert result.workflow_mode == WorkflowMode.GUIDED
    assert result.repo_profile_ref == "contracts/missing_profile.md"
    assert result.workflow_mode_resolved is True


def test_resolve_start_mode_uses_workflow_kind_hint() -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    assert result.workflow_kind == WorkflowKind.RUNBOOK
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "workflow_kind_hint"


def test_resolve_start_mode_uses_docs_path_clue_without_hint(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            request_path_refs=["docs/decision-record.md", "README.md"],
        )
    )

    assert result.workflow_kind == WorkflowKind.DOCS_ONLY
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "path_docs_clue"


def test_resolve_start_mode_treats_txt_path_as_docs_without_hint(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            request_path_refs=["notes.txt"],
        )
    )

    assert result.workflow_kind == WorkflowKind.DOCS_ONLY
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "path_docs_clue"


def test_resolve_start_mode_treats_docs_directory_as_docs_before_code_dir_name(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            request_path_refs=["docs/python/guide.md", "python/docs/foo.md"],
        )
    )

    assert result.workflow_kind == WorkflowKind.DOCS_ONLY
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "path_docs_clue"


def test_resolve_start_mode_rejects_docs_hint_with_code_path_clue(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="docs_only",
            request_path_refs=["python/src/example.py"],
        )
    )

    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_kind_source == "workflow_kind_hint_path_conflict"


def test_resolve_start_mode_rejects_runbook_hint_with_docs_only_path_clue(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="runbook",
            request_path_refs=["README.md", "docs/guide.md"],
        )
    )

    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_kind_source == "workflow_kind_hint_path_conflict"


def test_resolve_start_mode_marks_mixed_code_docs_paths_unknown_without_hint(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            request_path_refs=["src/service.py", "docs/guide.md"],
        )
    )

    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_kind_source == "path_mixed_clue"


def test_resolve_start_mode_allows_runbook_hint_with_mixed_code_docs_paths(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="runbook",
            request_path_refs=["src/service.py", "docs/guide.md"],
        )
    )

    assert result.workflow_kind == WorkflowKind.RUNBOOK
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "workflow_kind_hint"


def test_resolve_start_mode_allows_runbook_hint_with_single_mixed_path(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="runbook",
            request_path_refs=["docs/scripts/setup.py"],
        )
    )

    assert result.workflow_kind == WorkflowKind.RUNBOOK
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "workflow_kind_hint"


def test_resolve_start_mode_uses_discussion_hint_without_path_refs(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="discussion_only",
        )
    )

    assert result.workflow_kind == WorkflowKind.DISCUSSION_ONLY
    assert result.workflow_kind_resolved is True
    assert result.workflow_kind_source == "workflow_kind_hint"


def test_resolve_start_mode_keeps_explicit_unknown_hint_unresolved(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="unknown",
            request_path_refs=["src/service.py"],
        )
    )

    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_kind_source == "workflow_kind_hint_unknown_explicit"


def test_resolve_start_mode_reports_invalid_workflow_kind_hint(tmp_path: Path) -> None:
    result = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=tmp_path,
            workflow_kind_hint="not-a-kind",
            request_path_refs=["src/service.py"],
        )
    )

    assert result.workflow_kind == WorkflowKind.UNKNOWN
    assert result.workflow_kind_resolved is False
    assert result.workflow_kind_source == "workflow_kind_hint_invalid"


def test_start_runtime_accepts_resolver_payload(tmp_path: Path) -> None:
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="resolver-to-runtime",
            task_classification="simple_local",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="resolver 연결",
            workspace_root=REPO_ROOT,
            **resolved.to_start_runtime_payload(),
        )
    )

    assert result["reason_code"] is None
    assert result["repo_profile_ref"] == "contracts/repo_profile.md"


def test_start_runtime_rejects_unknown_guided_classification(tmp_path: Path) -> None:
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="unknown-classification",
            task_classification="unknown",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="분류 검증",
            workspace_root=REPO_ROOT,
            **resolved.to_start_runtime_payload(),
        )
    )

    assert result["reason_code"] == "START_CLASSIFICATION_INVALID"


def test_start_runtime_rejects_profile_read_set_mismatch(tmp_path: Path) -> None:
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="read-set-mismatch",
            task_classification="entry_common_flow",
            initial_phase="plan",
            minimum_read_set=[
                {
                    "read_target_kind": "doc_section",
                    "doc_path": "unknown.md",
                    "selector_type": "header_path",
                    "section_selector": "unknown",
                    "why": "not in profile",
                }
            ],
            phase_doc_ref="phases/plan.md",
            user_request="read set 검증",
            workspace_root=REPO_ROOT,
            **resolved.to_start_runtime_payload(),
        )
    )

    assert result["reason_code"] == "START_MINIMUM_READ_SET_INVALID"


def test_start_runtime_accepts_reordered_profile_read_set_subset(tmp_path: Path) -> None:
    profile = load_repo_profile(REPO_ROOT / "contracts/repo_profile.md", workspace_root=REPO_ROOT)
    classification = profile.guided_classifications["entry_common_flow"]
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="read-set-subset",
            task_classification="entry_common_flow",
            initial_phase="plan",
            minimum_read_set=list(reversed(classification.minimum_read_set_default[:1])),
            phase_doc_ref="phases/plan.md",
            user_request="read set subset 검증",
            workspace_root=REPO_ROOT,
            **resolved.to_start_runtime_payload(),
        )
    )

    assert result["reason_code"] is None


def test_start_runtime_reuses_guard_loaded_profile(monkeypatch, tmp_path: Path) -> None:
    def fail_runtime_profile_load(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("runtime should reuse the profile loaded by guard")

    monkeypatch.setattr(start_runtime_module, "load_repo_profile", fail_runtime_profile_load)
    resolved = resolve_start_mode(
        StartModeResolverInput(
            workspace_root=REPO_ROOT,
            adoption_kind="legacy-medium",
            workflow_kind_hint="runbook",
        )
    )

    result = execute_start_runtime(
        StartRuntimeInput(
            task_root=tmp_path,
            task_name="profile-handoff",
            task_classification="simple_local",
            initial_phase="plan",
            minimum_read_set=[],
            phase_doc_ref="phases/plan.md",
            user_request="profile handoff 검증",
            workspace_root=REPO_ROOT,
            **resolved.to_start_runtime_payload(),
        )
    )

    assert result["reason_code"] is None


def test_runtime_cli_exposes_start_mode_resolver(monkeypatch, capsys) -> None:
    payload = {"workspace_root": str(REPO_ROOT), "adoption_kind": "legacy-small", "workflow_kind_hint": "runbook"}
    monkeypatch.setattr(sys, "argv", ["harness-runtime", "wf-start-mode-resolver"])
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    exit_code = main()
    captured = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["workflow_mode"] == "guided"
    assert captured["repo_profile_ref"] == "contracts/repo_profile.md"
    assert captured["adoption_kind"] == "legacy-small"
    assert captured["workflow_kind"] == "runbook"
    assert captured["workflow_kind_resolved"] is True
    assert captured["workflow_mode_resolved"] is True
