# Harness Repo Profile Schema

## 목적과 범위

이 문서는 하네스가 특정 프로젝트에 도입될 때 guided workflow가 사용할 concrete repo onboarding profile instance를 정의한다.
이 profile은 대상 프로젝트의 `templates/project/architecture.md`, `templates/project/code-structure.md`, `templates/project/known-issue.md`를 읽기 위한 schema instance다.

이 문서는 shared core contract가 아니라 repo-specific profile schema instance다.
즉 `/wf-start`의 output shape, state/scaffold/write 책임은 [shared_implementation.md](contracts/shared_implementation.md)를 따르고, 이 문서는 shared core가 소비할 repo-specific structured data surface를 고정한다.

범위:
- 도입 유형 입력 surface
- 도입 유형별 guided classification inventory
- classification별 `minimum_read_set_default` / `minimum_read_set_extensions`
- repo 최초 세팅 시 선택한 build/test/static/format-check toolchain
- 도입 유형별 초기 verification gate template
- direct symptom 기반 `known_issue_selector_mapping`
- repo-specific implementation exit doc-sync supplement

비범위:
- `/wf-start`의 shared output/state/scaffold contract
- `/wf-checkpoint`, `/wf-next`, `/wf-apply` 등의 공용 의미
- Claude/Codex adapter wiring

## Consumption Contract

shared core는 이 문서를 free-form 설명문이 아니라, 단일 top-level schema object를 가진 profile instance로 소비한다.

top-level fields:
- `profile_id`
- `profile_version`
- `provenance_refs` (optional, default `[]`)
- `project_context` (optional for generic profiles)
- `guided_classifications` (optional, default `{}`)
- `verification_toolchain` (optional but recommended; default unset)
- `verification_gate_templates` (optional, default `{}`)
- `known_issue_selector_mapping` (optional, default `[]`)
- `checkpoint_supplements` (optional, default `{}`)
- Optional mapping/list fields may be omitted to use their defaults, but explicit YAML `null` is invalid and must fail profile load as `RepoProfileLoadError`.

identity contract:
- `repo_profile_ref`는 task state에 pin되는 external locator/path다
- `profile_id`는 loaded profile instance 내부의 stable semantic identity다
- shared core는 `repo_profile_ref`로 profile artifact를 찾고, 그 안의 `profile_id`, `profile_version`을 읽는다
- canonical task state는 locator인 `repo_profile_ref`를 pin하고, loaded profile instance는 그 locator가 가리키는 semantic payload를 제공한다

typed read-entry contract:
- `minimum_read_set_default[*]`, `minimum_read_set_extensions[*]`, `known_issue_selector_mapping[*]`, `checkpoint_supplements[*].reads[*]`는 모두 최소 `doc_path`, `section_selector`, `why`를 가진다
- schema-driven consumption에서는 위 최소 field 외에 `read_target_kind`, `selector_type`를 함께 가진다
- `doc_path`, `why`, `read_target_kind`, `selector_type`는 non-empty string이어야 한다
- `section_selector`는 non-empty string 또는 non-empty string list여야 한다. YAML `null`, 숫자, list 내부 non-string 값은 허용하지 않는다
- `read_target_kind` 허용 값:
  - `doc_section`
  - `artifact_view`
  - `state_field`
  - `derived_input`
- `selector_type` 허용 값:
  - `header_path`
  - `header_set`
  - `wildcard`
  - `field_name`
  - `virtual`

project context contract:
- `project_context`는 guided mode initialization에서 먼저 판정할 도입 유형의 resolution contract와 required-doc rule surface다
- 최소 required field:
  - `adoption_kind_source`
  - `adoption_kind_allowed`
  - `initialization_requirements`
- resolved input `adoption_kind` 허용 값:
  - `greenfield`
  - `legacy-small`
  - `legacy-medium`
  - `legacy-large`
- shared core는 이 contract를 통해 guided mode의 initialization precondition과 `/wf-start` guard를 해석할 수 있어야 한다
- `adoption_kind`는 profile에 pin된 stored field가 아니다. workspace initialization input이 먼저 resolve하고, shared core는 그 resolved value가 `adoption_kind_allowed` 안에 있는지 확인한다
- 현재 구현은 `adoption_kind_source.resolution_order` 중 `explicit initialization input`만 지원한다. `workspace-local config`, `repo-local profile metadata`는 reserved 확장 surface다
- `initialization_requirements`는 도입 유형별 required template path와 required section rule의 canonical source다. `templates/project/*` 템플릿 문서는 이 기준을 설명하는 문서지만, guard의 source of truth는 profile instance다

verification gate template contract:
- `verification_toolchain`은 repo 최초 세팅 시 선택한 build/test/static/format-check 도구와 required gate의 canonical source다
- `verification_toolchain.configured=true`이면 `/wf-start`는 `verification_gate_templates[adoption_kind]`보다 toolchain required gates를 우선해 `plan.md`의 `Verification` 초기 계약을 만든다
- `verification_toolchain` section이 present하면 `verification_toolchain.configured`는 필수이며 YAML boolean `true | false`여야 한다. quoted string `"true"` / `"false"`는 허용하지 않는다
- `verification_toolchain.configured=true`이면 `build_tool`은 non-empty string, `required_gates`는 1개 이상이어야 하고, 각 required gate의 `name`, `command`, `working_directory`, `success_criteria`, `evidence`도 non-empty string이어야 한다. `working_directory`는 생략하면 `.`로 처리되지만, key가 있으면 non-empty string이어야 한다. YAML `null`이나 non-string 값은 허용하지 않는다. 이 조건을 만족하지 않으면 profile load가 실패한다
- `verification_toolchain.conditional_gates[*].condition`, `verification_toolchain.conditional_gates[*].gate`, `verification_toolchain.manual_checks[*].check`, `verification_toolchain.manual_checks[*].evidence`도 present하면 non-empty string이어야 한다
- `verification_toolchain.configured=false`이면 toolchain 전체를 비활성 stub으로 보며 build/test/gate/check/notes 내용을 검증하거나 사용하지 않는다
- `verification_toolchain.configured=false`이거나 section이 없으면 기존 `verification_gate_templates[adoption_kind]` 또는 shared fallback placeholder를 사용한다
- `verification_toolchain.build_tool`은 repo가 실제 사용하는 build/test driver를 적는다. 예: `gradle`, `maven`, `python`, `pnpm`, `custom`
- `verification_toolchain.required_gates[*]`는 task별 최소 gate 후보이며, 특정 작업에서 과하거나 부족하면 plan/checkpoint/apply flow로 task-local `Verification` 계약을 수정한다
- `verification_gate_templates`는 `/wf-start`가 최초 1회 `plan.md`의 `Verification` 계약을 초기화할 때 사용하는 도입 유형별 template이다
- key는 `project_context.adoption_kind_allowed`의 token과 일치해야 한다
- shared harness는 이 template을 실행하지 않는다. `/wf-start`는 task-local verification contract scaffold만 만들고, 실제 실행은 `/wf-verify`가 최신 `plan.md` 계약을 기준으로 수행한다
- 각 required gate는 최소 `name`, `command`, `working_directory`, `success_criteria`, `evidence`를 가진다
- 각 conditional gate와 manual check field도 YAML `null`이나 non-string 값을 허용하지 않는다
- command를 아직 repo 차원에서 확정할 수 없으면 `<define before verification>` 같은 명시적 placeholder를 남긴다
- shared profile은 특정 언어, 빌드 도구, 테스트 프레임워크 명령을 기본값으로 고정하지 않는다

profile version migration:
- `profile_version: 8`은 repo-level `verification_toolchain`을 도입하고, configured toolchain을 adoption template보다 우선한다
- v7 profile이 `verification_toolchain: {}` 또는 `configured` 누락 형태를 쓰고 있었다면 v8에서는 `configured: false`를 명시하거나, `configured: true`와 완전한 toolchain 값을 함께 제공해야 한다
- v8 loader는 `verification_toolchain.configured`, required gate fields, conditional gate fields, manual check fields의 YAML `null` 또는 non-string 값을 profile load failure로 처리한다

## Profile Instance

```yaml
profile_id: workspace-default
profile_version: 8
provenance_refs:
  - contracts/repo_profile.md
project_context:
  adoption_kind_source:
    kind: explicit_initialization_input
    resolution_order:
      - explicit initialization input
  adoption_kind_allowed:
    - greenfield
    - legacy-small
    - legacy-medium
    - legacy-large
  initialization_requirements:
    greenfield:
      doc_rules:
        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
            - 전체 구조와 책임
            - 데이터 흐름
        - doc_path: templates/project/code-structure.md
          required_sections:
            - 1. 시작점
            - 3. 공통 처리 플로우
    legacy-small:
      doc_rules:
        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
            - 전체 구조와 책임
    legacy-medium:
      doc_rules:
        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
            - 전체 구조와 책임
            - 데이터 흐름
            - 외부 의존성
        - doc_path: templates/project/code-structure.md
          required_sections:
            - 1. 시작점
            - 2. 주요 진입 경로
            - 3. 공통 처리 플로우
    legacy-large:
      doc_rules:
        - doc_path: templates/project/architecture.md
          required_sections:
            - 시스템 개요
            - 디렉터리 구조
            - 전체 구조와 책임
            - 데이터 흐름
            - 외부 의존성
            - 주요 분기 / 예외 경로
        - doc_path: templates/project/code-structure.md
          required_sections:
            - 1. 시작점
            - 2. 주요 진입 경로
            - 3. 공통 처리 플로우
            - 4. 외부 연동 경로
            - 5. Known Issue 경로
        - doc_path: templates/project/known-issue.md
          required_sections:
            - 문서 정본과 실제 구조 불일치
          min_level_two_sections: 3
          ignored_level_two_sections:
            - 최소 작성 기준
            - 작성 메모
verification_toolchain:
  configured: true
  build_tool: python
  test_tool: pytest
  working_directory: .
  required_gates:
    - name: Python test suite
      command: pytest python/tests
      working_directory: .
      success_criteria: pytest exits 0
      evidence: pytest summary
  conditional_gates:
    - condition: packaging or import surface changes
      gate: run an import/package smoke check for the touched surface
  manual_checks:
    - check: confirm changed workflow docs match runtime behavior
      evidence: reviewed contracts/shared_implementation.md and relevant skill docs
  notes:
    - Java/Spring repos should replace this toolchain during onboarding with their actual build tool, such as gradle, maven, or a custom script.
guided_classifications:
  simple_local:
    token: simple_local
    meaning:
      - 특정 파일, 클래스, 메서드로 이미 좁혀진 작업
      - 상위 구조, 공통 처리 순서, 외부 연동 경계, known issue selector를 바꾸지 않음
    default_initial_phase_hint: plan
    minimum_read_set_default: []
    minimum_read_set_extensions: []
  entry_common_flow:
    token: entry_common_flow
    meaning:
      - 시작점, dispatcher/router/factory, 공통 처리 순서, 핵심 분기 변경
    default_initial_phase_hint: plan
    minimum_read_set_default:
      - read_target_kind: doc_section
        doc_path: templates/project/architecture.md
        selector_type: header_set
        section_selector:
          - 시스템 개요
          - 전체 구조와 책임
          - 데이터 흐름
        why: 시작점과 공통 처리의 상위 책임 경계를 먼저 닫기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/code-structure.md
        selector_type: header_set
        section_selector:
          - 1. 시작점
          - 2. 주요 진입 경로
          - 3. 공통 처리 플로우
        why: 실제 읽기 순서와 공통 처리 순서를 코드 기준으로 따라가기 위해
    minimum_read_set_extensions: []
  integration_persistence:
    token: integration_persistence
    meaning:
      - 외부 API, 메시지 큐, DB, 캐시, 파일 I/O, 후속 처리/저장 경계 변경
    default_initial_phase_hint: plan
    minimum_read_set_default:
      - read_target_kind: doc_section
        doc_path: templates/project/architecture.md
        selector_type: header_set
        section_selector:
          - 데이터 흐름
          - 외부 의존성
          - 주요 분기 / 예외 경로
        why: 외부 연동과 저장 경계가 end-to-end 흐름에 어떻게 연결되는지 먼저 닫기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/code-structure.md
        selector_type: header_set
        section_selector:
          - 3. 공통 처리 플로우
          - 4. 외부 연동 경로
        why: 공통 처리 이후 외부 경계로 나가는 위치를 실제 코드 기준으로 따라가기 위해
    minimum_read_set_extensions: []
  guided_input_templates:
    token: guided_input_templates
    meaning:
      - architecture, code-structure, known-issue, repo profile, selector, 최소 읽기 집합 변경
    default_initial_phase_hint: pre-planning
    minimum_read_set_default:
      - read_target_kind: doc_section
        doc_path: templates/project/architecture.md
        selector_type: header_set
        section_selector:
          - 최소 작성 기준
          - 작성 메모
        why: architecture 문서의 최소 계약과 selector 안정성을 먼저 확인하기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/code-structure.md
        selector_type: header_set
        section_selector:
          - 최소 작성 기준
          - 6. 주요 경로별 읽기 순서
          - 작성 메모
        why: code-structure의 최소 계약과 read map 연결 규칙을 먼저 확인하기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/known-issue.md
        selector_type: wildcard
        section_selector: "*"
        why: selector 대상 섹션과 symptom shape를 함께 확인하기 위해
    minimum_read_set_extensions: []
  uncertain_or_multi:
    token: uncertain_or_multi
    meaning:
      - 하나로 고르기 어렵거나 둘 이상 도메인에 동시에 걸치는 작업
    default_initial_phase_hint: pre-planning
    minimum_read_set_default:
      - read_target_kind: doc_section
        doc_path: templates/project/architecture.md
        selector_type: header_set
        section_selector:
          - 전체 구조와 책임
          - 데이터 흐름
        why: 복합 작업에서 먼저 상위 책임 경계와 end-to-end 흐름을 닫기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/code-structure.md
        selector_type: header_path
        section_selector: 3. 공통 처리 플로우
        why: 세부 분류 전에 공통 실행축을 먼저 확보하기 위해
    minimum_read_set_extensions: []
known_issue_selector_mapping:
  - match_hint: stale_docs_symptom
    read_target_kind: doc_section
    doc_path: templates/project/known-issue.md
    selector_type: header_path
    section_selector: 문서 정본과 실제 구조 불일치
    why: 구조 문서와 실제 구조가 엇갈린다는 직접 증상이 있으면 먼저 확인하기 위해
checkpoint_supplements:
  implementation_exit_doc_sync:
    supplement_id: implementation_exit_doc_sync
    applies_to_phase: implementation
    activation_predicate:
      workflow_mode: guided
      base_candidate_in:
        - GO
        - GO_WITH_NOTE
      terminal_implementation_exit_only: true
    reads:
      - read_target_kind: doc_section
        doc_path: templates/project/architecture.md
        selector_type: wildcard
        section_selector: "*"
        why: 책임 경계와 상위 구조 문서가 stale한지 확인하기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/code-structure.md
        selector_type: wildcard
        section_selector: "*"
        why: 읽기 순서와 진입 경로 문서가 stale한지 확인하기 위해
      - read_target_kind: doc_section
        doc_path: templates/project/known-issue.md
        selector_type: wildcard
        section_selector: "*"
        why: known issue selector와 증상 문서가 stale한지 확인하기 위해
      - read_target_kind: artifact_view
        doc_path: steps.md
        selector_type: virtual
        section_selector: canonical-parse
        why: 현재 step 완료 후 pending execution step이 남는지 판단하기 위해
      - read_target_kind: state_field
        doc_path: state.json
        selector_type: field_name
        section_selector: workspace_baseline_ref
        why: task-scoped diff의 canonical baseline을 얻기 위해
      - read_target_kind: derived_input
        doc_path: task-scoped-diff
        selector_type: virtual
        section_selector: current
        why: 현재 변경이 구조 문서 update 대상인지 판단하기 위해
      - read_target_kind: doc_section
        doc_path: plan.md
        selector_type: header_set
        section_selector:
          - References
          - Scope
          - Constraints
        why: task contract와 실제 변경 범위를 대조하기 위해
    override_contract:
      judgement_code: REWORK
      primary_cause_code:
        required: repo-doc-sync-required
        unresolved: repo-doc-sync-status-unresolved
      reason_fingerprint:
        required: checkpoint:implementation|REWORK|task|repo-doc-sync-required
        unresolved: checkpoint:implementation|REWORK|task|repo-doc-sync-status-unresolved
      summary_rule: verification 진입 전 구조 문서 sync 필요 여부가 직접 드러나야 한다
      basis_refs_rule: 구조 문서 ref와 현재 task-scoped diff/code ref를 함께 포함해야 한다
    doc_update_policy:
      architecture_required_when:
        - 컴포넌트 책임 경계가 바뀜
        - 상위 데이터 흐름이 바뀜
        - 외부 의존성 경계가 바뀜
      code_structure_required_when:
        - 주요 entrypoint, 공통 처리 순서, 읽기 순서가 바뀜
        - 구조 문서에서 안내하는 실제 읽기 경로가 stale해짐
      known_issue_required_when:
        - 반복 증상과 selector 대상 섹션이 바뀜
        - 기존 symptom 분류로는 빠른 대조가 불가능해짐
      usually_not_required_when:
        - 같은 책임 경계 안의 내부 구현 변경
        - 동작 의미를 바꾸지 않는 local refactor
        - 테스트만의 변경
        - naming/comment/format 정리
    policy_notes:
      - 구조 문서 sync가 필요 없으면 base candidate를 유지한다
      - 구조 문서 sync가 필요하지만 아직 반영되지 않았으면 REWORK로 override한다
      - sync 필요 여부를 자신 있게 판단할 수 없으면 안전하게 REWORK로 본다
verification_gate_templates:
  greenfield:
    required_gates:
      - name: Task-specific smoke or regression gate
        command: <define before verification>
        working_directory: <repo root or task-defined workdir>
        success_criteria: Command exits 0 or documented manual check passes.
        evidence: Command summary, report path, or manual check notes in verification.md.
    conditional_gates:
      - condition: Public behavior, API, or integration boundary is introduced.
        gate: Add an integration or scenario check before /wf-verify.
    manual_checks:
      - check: Confirm the new scaffold or behavior matches the intended task contract.
        evidence: Reviewed file list, entry points, and representative scenario notes.
  legacy-small:
    required_gates:
      - name: Existing regression gate for touched area
        command: <repo-defined regression command>
        working_directory: <repo-defined workdir>
        success_criteria: No new failures relative to the task baseline.
        evidence: Command summary, structured report, or failure analysis in verification.md.
    conditional_gates:
      - condition: Shared module, persistence, external integration, or entry flow changes.
        gate: Run the narrowest available downstream or integration check for that boundary.
    manual_checks:
      - check: Compare changed behavior with existing documented behavior and known issues.
        evidence: References to relevant project docs, diff summary, and unresolved risk notes.
  legacy-medium:
    required_gates:
      - name: Existing regression gate for touched area
        command: <repo-defined regression command>
        working_directory: <repo-defined workdir>
        success_criteria: No new failures relative to the task baseline.
        evidence: Command summary, structured report, or failure analysis in verification.md.
    conditional_gates:
      - condition: Shared module, persistence, external integration, or entry flow changes.
        gate: Run the narrowest available downstream or integration check for that boundary.
    manual_checks:
      - check: Compare changed behavior with existing documented behavior and known issues.
        evidence: References to relevant project docs, diff summary, and unresolved risk notes.
  legacy-large:
    required_gates:
      - name: Existing regression gate for touched area
        command: <repo-defined regression command>
        working_directory: <repo-defined workdir>
        success_criteria: No new failures relative to the task baseline.
        evidence: Command summary, structured report, or failure analysis in verification.md.
    conditional_gates:
      - condition: Shared module, persistence, external integration, or entry flow changes.
        gate: Run the narrowest available downstream or integration check for that boundary.
    manual_checks:
      - check: Compare changed behavior with existing documented behavior and known issues.
        evidence: References to relevant project docs, diff summary, and unresolved risk notes.
```

운영 메모:
- verification/review는 구조 문서가 stale한 상태로 들어가지 않는 것을 기본 원칙으로 한다
- 코드 구조, 책임 경계, 진입점, 읽기 순서, known issue 분류가 바뀌면 이 profile schema instance도 함께 갱신해야 한다
