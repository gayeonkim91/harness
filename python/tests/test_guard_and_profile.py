from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.core.guard_executor import GuardInput, run_guard
from harness.shared.core.repo_profile_loader import RepoProfileLoadError, load_repo_profile
from harness.shared.contracts.state import CurrentPhase, HarnessCounters, HarnessState, SessionState, WorkflowMode


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_profile(workspace_root: Path, body: str) -> Path:
    profile_path = workspace_root / "contracts/repo_profile.md"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(body, encoding="utf-8")
    return profile_path


def _minimal_profile_yaml(adoption_kind: str, doc_rule_yaml: str) -> str:
    return f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
provenance_refs: []
project_context:
  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - {adoption_kind}
  initialization_requirements:
    {adoption_kind}:
      doc_rules:
{doc_rule_yaml}
guided_classifications: {{}}
known_issue_selector_mapping: []
checkpoint_supplements: {{}}
```
"""


def _minimal_profile_without_project_context() -> str:
    return """# Test Profile

```yaml
profile_id: test
profile_version: 1
provenance_refs: []
guided_classifications: {}
known_issue_selector_mapping: []
checkpoint_supplements: {}
```
"""


def test_repo_profile_loads_initialization_requirements() -> None:
    profile = load_repo_profile(REPO_ROOT / "contracts/repo_profile.md", workspace_root=REPO_ROOT)

    assert profile.profile_version == 8
    assert profile.project_context is not None
    assert profile.verification_toolchain is not None
    assert profile.verification_toolchain.configured is True
    assert profile.verification_toolchain.build_tool == "python"
    assert profile.verification_toolchain.required_gates[0].command == "pytest python/tests"
    assert profile.project_context.adoption_kind_resolution_order == ["explicit initialization input"]
    legacy_large_rules = profile.project_context.initialization_requirements["legacy-large"]
    assert [rule.doc_path for rule in legacy_large_rules] == [
        "templates/project/architecture.md",
        "templates/project/code-structure.md",
        "templates/project/known-issue.md",
    ]
    assert legacy_large_rules[-1].min_level_two_sections == 3
    assert profile.verification_gate_templates["greenfield"].required_gates[0].name == (
        "Task-specific smoke or regression gate"
    )
    assert profile.verification_gate_templates["legacy-large"].required_gates[0].command == (
        "<repo-defined regression command>"
    )


def test_repo_profile_rejects_configured_toolchain_without_build_tool(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: ""
  required_gates:
    - name: Tests
      command: ./mvnw test
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="build_tool"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_configured_toolchain_with_null_build_tool(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: null
  required_gates:
    - name: Tests
      command: ./mvnw test
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="build_tool"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_configured_toolchain_with_null_working_directory(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: maven
  working_directory: null
  required_gates:
    - name: Tests
      command: ./mvnw test
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="working_directory"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_configured_toolchain_without_required_gates(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: maven
  required_gates: []
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="required gate"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize("field_name", ["name", "command", "working_directory", "success_criteria", "evidence"])
def test_repo_profile_rejects_configured_toolchain_with_empty_required_gate_field(
    tmp_path: Path,
    field_name: str,
) -> None:
    gate = {
        "name": "Tests",
        "command": "./mvnw test",
        "working_directory": ".",
        "success_criteria": "exits 0",
        "evidence": "surefire report",
    }
    gate[field_name] = '""'
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: maven
  required_gates:
    - name: {gate["name"]}
      command: {gate["command"]}
      working_directory: {gate["working_directory"]}
      success_criteria: {gate["success_criteria"]}
      evidence: {gate["evidence"]}
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=field_name):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_configured_toolchain_with_null_required_gate_field(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: maven
  required_gates:
    - name: Tests
      command: null
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="command"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_null_verification_toolchain(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain: null
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="must be a mapping"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_null_project_context(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
project_context: null
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="project_context must be a mapping"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_rejects_toolchain_missing_configured(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  build_tool: maven
  required_gates:
    - name: Tests
      command: ./mvnw test
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="verification_toolchain.configured"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize(
    "field_name",
    ["guided_classifications", "checkpoint_supplements", "verification_gate_templates"],
)
def test_repo_profile_rejects_null_optional_mapping_field(tmp_path: Path, field_name: str) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
{field_name}: null
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=field_name):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize("entry_value", ["[]", "null"])
def test_repo_profile_rejects_non_mapping_verification_gate_template_entry(
    tmp_path: Path,
    entry_value: str,
) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_gate_templates:
  legacy-medium: {entry_value}
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="verification gate template must be a mapping"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize("field_name", ["provenance_refs", "known_issue_selector_mapping"])
def test_repo_profile_rejects_null_optional_list_field(tmp_path: Path, field_name: str) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
{field_name}: null
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=field_name):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize(
    ("profile_yaml", "match"),
    [
        (
            """profile_id: 123
profile_version: 1
""",
            "profile_id",
        ),
        (
            """profile_id: test
profile_version: "1"
""",
            "profile_version",
        ),
        (
            """profile_id: test
profile_version: 1
provenance_refs:
  - 123
""",
            "provenance_refs",
        ),
    ],
)
def test_repo_profile_rejects_lenient_top_level_coercion(
    tmp_path: Path,
    profile_yaml: str,
    match: str,
) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
{profile_yaml}```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=match):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize(
    ("field_yaml", "match"),
    [
        (
            """  adoption_kind_source:
    kind: null
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - greenfield
  initialization_requirements:
    greenfield:
      doc_rules: []
""",
            "adoption_kind_source.kind",
        ),
        (
            """  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - 123
  adoption_kind_allowed:
    - greenfield
  initialization_requirements:
    greenfield:
      doc_rules: []
""",
            "resolution_order",
        ),
        (
            """  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - 123
  initialization_requirements:
    greenfield:
      doc_rules: []
""",
            "adoption_kind_allowed",
        ),
        (
            """  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - greenfield
  initialization_requirements:
    greenfield:
      doc_rules:
        - doc_path: templates/project/known-issue.md
          min_level_two_sections: "3"
""",
            "min_level_two_sections",
        ),
    ],
)
def test_repo_profile_rejects_lenient_project_context_coercion(
    tmp_path: Path,
    field_yaml: str,
    match: str,
) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
project_context:
{field_yaml}```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=match):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize(
    ("entry_yaml", "match"),
    [
        (
            """read_target_kind: 123
doc_path: templates/project/known-issue.md
selector_type: header_path
section_selector: 문서 정본과 실제 구조 불일치
why: direct symptom check
""",
            "read_target_kind",
        ),
        (
            """read_target_kind: unknown_target
doc_path: templates/project/known-issue.md
selector_type: header_path
section_selector: 문서 정본과 실제 구조 불일치
why: direct symptom check
""",
            "read_target_kind",
        ),
        (
            """read_target_kind: doc_section
doc_path: templates/project/known-issue.md
selector_type: 123
section_selector: 문서 정본과 실제 구조 불일치
why: direct symptom check
""",
            "selector_type",
        ),
        (
            """read_target_kind: doc_section
doc_path: templates/project/known-issue.md
selector_type: unknown_selector
section_selector: 문서 정본과 실제 구조 불일치
why: direct symptom check
""",
            "selector_type",
        ),
        (
            """read_target_kind: doc_section
doc_path: templates/project/known-issue.md
selector_type: header_path
section_selector: null
why: direct symptom check
""",
            "section_selector",
        ),
        (
            """read_target_kind: doc_section
doc_path: templates/project/known-issue.md
selector_type: header_set
section_selector:
  - 문서 정본과 실제 구조 불일치
  - 123
why: direct symptom check
""",
            "section_selector",
        ),
    ],
)
def test_repo_profile_rejects_invalid_typed_read_entry_fields(
    tmp_path: Path,
    entry_yaml: str,
    match: str,
) -> None:
    entry_lines = entry_yaml.splitlines()
    indented_entry = "\n".join(
        [f"  - {entry_lines[0]}"]
        + [f"    {line}" if line else "" for line in entry_lines[1:]]
    )
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
known_issue_selector_mapping:
{indented_entry}
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=match):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_repo_profile_ignores_unconfigured_toolchain_stub_gates(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: false
  build_tool: maven
  test_tool: surefire
  working_directory: service
  required_gates:
    - name: null
      command: null
      working_directory: null
      success_criteria: null
      evidence: null
  notes:
    - ignored stub note
```
""",
    )

    profile = load_repo_profile(profile_path, workspace_root=tmp_path)

    assert profile.verification_toolchain is not None
    assert profile.verification_toolchain.configured is False
    assert profile.verification_toolchain.build_tool == ""
    assert profile.verification_toolchain.test_tool is None
    assert profile.verification_toolchain.working_directory == "."
    assert profile.verification_toolchain.required_gates == []
    assert profile.verification_toolchain.notes == []


def test_repo_profile_rejects_quoted_toolchain_configured_false(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path,
        """# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: "false"
  build_tool: maven
  required_gates: []
```
""",
    )

    with pytest.raises(RepoProfileLoadError, match="boolean"):
        load_repo_profile(profile_path, workspace_root=tmp_path)


@pytest.mark.parametrize(
    ("extra_yaml", "match"),
    [
        (
            """  conditional_gates:
    - condition: null
      gate: run API scenario check
""",
            "condition",
        ),
        (
            """  conditional_gates:
    - condition: public API changed
      gate: null
""",
            "gate",
        ),
        (
            """  manual_checks:
    - check: null
      evidence: reviewed endpoint scenario notes
""",
            "check",
        ),
        (
            """  manual_checks:
    - check: compare Spring endpoint behavior
      evidence: null
""",
            "evidence",
        ),
    ],
)
def test_repo_profile_rejects_configured_toolchain_with_invalid_conditional_or_manual_field(
    tmp_path: Path,
    extra_yaml: str,
    match: str,
) -> None:
    profile_path = _write_profile(
        tmp_path,
        f"""# Test Profile

```yaml
profile_id: test
profile_version: 1
verification_toolchain:
  configured: true
  build_tool: maven
  required_gates:
    - name: Tests
      command: ./mvnw test
      working_directory: .
      success_criteria: exits 0
      evidence: surefire report
{extra_yaml}```
""",
    )

    with pytest.raises(RepoProfileLoadError, match=match):
        load_repo_profile(profile_path, workspace_root=tmp_path)


def test_guard_blocks_partial_task_initialization(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# partial\n", encoding="utf-8")

    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path,
            context={
                "user_request": "부분 초기화 검사",
                "workflow_mode": "generic",
                "workflow_mode_resolved": True,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_TASK_INIT_PARTIAL"


def test_guard_blocks_generic_mode_when_workspace_profile_exists(tmp_path: Path) -> None:
    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path,
            context={
                "user_request": "generic 우회 검사",
                "workflow_mode": "generic",
                "workflow_mode_resolved": True,
                "workflow_kind": "runbook",
                "workflow_kind_resolved": True,
                "workspace_root": REPO_ROOT,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_WORKFLOW_MODE_CONFLICT"


def test_start_guard_resolves_profile_from_nested_workspace_path(tmp_path: Path) -> None:
    _write_profile(tmp_path, _minimal_profile_without_project_context())
    nested_root = tmp_path / "tasks/current"
    nested_root.mkdir(parents=True)

    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path / "task",
            context={
                "user_request": "nested profile 검사",
                "workflow_mode": "generic",
                "workflow_mode_resolved": True,
                "workflow_kind": "runbook",
                "workflow_kind_resolved": True,
                "workspace_root": nested_root,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_WORKFLOW_MODE_CONFLICT"


def test_guard_blocks_unresolved_workflow_mode_direct_call(tmp_path: Path) -> None:
    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path,
            context={
                "user_request": "mode unresolved",
                "workflow_mode": "generic",
                "workflow_mode_resolved": False,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_WORKFLOW_MODE_UNRESOLVED"


def test_guard_blocks_non_runbook_start(tmp_path: Path) -> None:
    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path,
            context={
                "user_request": "문서만 정리",
                "workflow_mode": "generic",
                "workflow_mode_resolved": True,
                "workflow_kind": "docs_only",
                "workflow_kind_resolved": True,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_NOT_RUNBOOK"


def test_guard_blocks_unresolved_workflow_kind_direct_call(tmp_path: Path) -> None:
    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path,
            context={
                "user_request": "kind unresolved",
                "workflow_mode": "generic",
                "workflow_mode_resolved": True,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_NOT_RUNBOOK"


def test_guard_blocks_missing_required_initialization_doc(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        _minimal_profile_yaml(
            "legacy-small",
            """        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
""",
        ),
    )

    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path / "task",
            context={
                "user_request": "문서 없음",
                "workflow_mode": "guided",
                "workflow_mode_resolved": True,
                "workflow_kind": "runbook",
                "workflow_kind_resolved": True,
                "repo_profile_ref": "contracts/repo_profile.md",
                "adoption_kind": "legacy-small",
                "workspace_root": tmp_path,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_INIT_REQUIRED_DOCS_MISSING"


def test_guard_blocks_required_initialization_header_missing(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        _minimal_profile_yaml(
            "legacy-small",
            """        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
""",
        ),
    )
    template_dir = tmp_path / "templates/project"
    template_dir.mkdir(parents=True)
    (template_dir / "architecture.md").write_text("## 다른 헤더\n", encoding="utf-8")

    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path / "task",
            context={
                "user_request": "헤더 없음",
                "workflow_mode": "guided",
                "workflow_mode_resolved": True,
                "workflow_kind": "runbook",
                "workflow_kind_resolved": True,
                "repo_profile_ref": "contracts/repo_profile.md",
                "adoption_kind": "legacy-small",
                "workspace_root": tmp_path,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_INIT_REQUIRED_DOCS_MISSING"


def test_guard_blocks_min_level_two_sections_missing(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        _minimal_profile_yaml(
            "legacy-large",
            """        - doc_path: templates/project/known-issue.md
          required_sections:
            - 문서 정본과 실제 구조 불일치
          min_level_two_sections: 3
          ignored_level_two_sections:
            - 최소 작성 기준
            - 작성 메모
""",
        ),
    )
    template_dir = tmp_path / "templates/project"
    template_dir.mkdir(parents=True)
    (template_dir / "known-issue.md").write_text(
        "## 최소 작성 기준\n\n## 문서 정본과 실제 구조 불일치\n\n## 작성 메모\n",
        encoding="utf-8",
    )

    decision = run_guard(
        GuardInput(
            action="wf-start",
            task_root=tmp_path / "task",
            context={
                "user_request": "known issue 부족",
                "workflow_mode": "guided",
                "workflow_mode_resolved": True,
                "workflow_kind": "runbook",
                "workflow_kind_resolved": True,
                "repo_profile_ref": "contracts/repo_profile.md",
                "adoption_kind": "legacy-large",
                "workspace_root": tmp_path,
            },
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "START_INIT_REQUIRED_DOCS_MISSING"


def _checkpoint_state(phase: CurrentPhase, current_step_ref: str | None = None) -> HarnessState:
    return HarnessState(
        schema_version=1,
        session_state=SessionState.IN_PROGRESS,
        workflow_mode=WorkflowMode.GENERIC,
        current_phase=phase,
        repo_profile_ref=None,
        workspace_baseline_ref=None,
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
    )


def test_checkpoint_guard_blocks_missing_plan(tmp_path: Path) -> None:
    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=_checkpoint_state(CurrentPhase.PLAN),
            context={"phase": "plan"},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "PLAN_ARTIFACT_MISSING"


def test_checkpoint_guard_blocks_current_step_ref_missing(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=_checkpoint_state(CurrentPhase.IMPLEMENTATION),
            context={"phase": "implementation"},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "CHECKPOINT_CURRENT_STEP_REF_MISSING"


def test_checkpoint_guard_allows_inline_go_marker_without_current_step_ref(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text(
        "# Plan\n\n## Steps\n\n- [ ] Implement one. (go)\n",
        encoding="utf-8",
    )

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=_checkpoint_state(CurrentPhase.IMPLEMENTATION),
            context={"phase": "implementation"},
        )
    )

    assert decision.allow is True


def test_checkpoint_guard_blocks_invalid_inline_marker_even_with_current_step_ref(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text(
        "# Plan\n\n## Steps\n\n- [ ] Implement one. (go)\n- [ ] Implement two. (go)\n",
        encoding="utf-8",
    )

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=_checkpoint_state(CurrentPhase.IMPLEMENTATION, current_step_ref="step:1"),
            context={"phase": "implementation"},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "CHECKPOINT_CURRENT_STEP_REF_MISSING"


def test_checkpoint_guard_allows_plan_phase_with_plan_artifact(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=_checkpoint_state(CurrentPhase.PLAN),
            context={"phase": "plan"},
        )
    )

    assert decision.allow is True


def test_verify_guard_blocks_missing_baseline(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.VERIFICATION)
    state.latest_checkpoint_ref = "logs/checkpoints/checkpoint.json"

    decision = run_guard(GuardInput(action="wf-verify", task_root=tmp_path, state=state))

    assert decision.allow is False
    assert decision.reason_code == "VERIFY_WORKSPACE_BASELINE_MISSING"


def test_verify_guard_allows_valid_state(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.VERIFICATION)
    state.workspace_baseline_ref = "logs/workspace-baseline.json"
    state.latest_checkpoint_ref = "logs/checkpoints/checkpoint.json"

    decision = run_guard(GuardInput(action="wf-verify", task_root=tmp_path, state=state))

    assert decision.allow is True


def test_review_guard_blocks_missing_verification_ref(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.REVIEW)
    state.workspace_baseline_ref = "logs/workspace-baseline.json"

    decision = run_guard(GuardInput(action="wf-review", task_root=tmp_path, state=state))

    assert decision.allow is False
    assert decision.reason_code == "REVIEW_VERIFICATION_REF_MISSING"


def test_review_guard_allows_valid_state(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.REVIEW)
    state.workspace_baseline_ref = "logs/workspace-baseline.json"
    state.latest_verification_ref = "logs/verification/verification.json"

    decision = run_guard(GuardInput(action="wf-review", task_root=tmp_path, state=state))

    assert decision.allow is True


def test_checkpoint_guard_resolves_guided_profile_from_nested_workspace_path(tmp_path: Path) -> None:
    _write_profile(tmp_path, _minimal_profile_without_project_context())
    (tmp_path / "phases").mkdir(parents=True)
    task_root = tmp_path / "tasks/current"
    task_root.mkdir(parents=True)
    (task_root / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.PLAN)
    state.workflow_mode = WorkflowMode.GUIDED
    state.repo_profile_ref = "contracts/repo_profile.md"

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=task_root,
            state=state,
            context={"phase": "plan", "workspace_root": task_root},
        )
    )

    assert decision.allow is True
    assert decision.repo_profile is not None


def test_checkpoint_guard_blocks_guided_missing_repo_profile_ref(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.PLAN)
    state.workflow_mode = WorkflowMode.GUIDED

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=state,
            context={"phase": "plan", "workspace_root": tmp_path},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "CHECKPOINT_REPO_PROFILE_UNAVAILABLE"


def test_checkpoint_guard_blocks_guided_missing_repo_profile_file(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.PLAN)
    state.workflow_mode = WorkflowMode.GUIDED
    state.repo_profile_ref = "contracts/missing_profile.md"

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=state,
            context={"phase": "plan", "workspace_root": tmp_path},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "CHECKPOINT_REPO_PROFILE_UNAVAILABLE"


def test_checkpoint_guard_blocks_guided_invalid_repo_profile_payload(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        """# Broken Profile

```yaml
profile_id: broken
```
""",
    )
    (tmp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
    state = _checkpoint_state(CurrentPhase.PLAN)
    state.workflow_mode = WorkflowMode.GUIDED
    state.repo_profile_ref = "contracts/repo_profile.md"

    decision = run_guard(
        GuardInput(
            action="wf-checkpoint",
            task_root=tmp_path,
            state=state,
            context={"phase": "plan", "workspace_root": tmp_path},
        )
    )

    assert decision.allow is False
    assert decision.reason_code == "CHECKPOINT_REPO_PROFILE_UNAVAILABLE"


def test_repo_profile_rejects_adoption_key_mismatch(tmp_path: Path) -> None:
    profile_path = tmp_path / "broken-profile.md"
    profile_path.write_text(
        """# Broken Profile

```yaml
profile_id: broken
profile_version: 1
provenance_refs: []
project_context:
  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - greenfield
    - legacy-small
  initialization_requirements:
    greenfield:
      doc_rules:
        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
guided_classifications: {}
known_issue_selector_mapping: []
checkpoint_supplements: {}
```
""",
        encoding="utf-8",
    )

    with pytest.raises(RepoProfileLoadError):
        load_repo_profile(profile_path, workspace_root=tmp_path)
