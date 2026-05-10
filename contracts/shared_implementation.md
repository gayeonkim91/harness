# Harness Shared Implementation

## 목적과 범위

이 문서는 Claude/Codex adapter가 공통으로 따르는 shared implementation contract다.
tool-specific 차이를 제외한 `/wf-*` semantic contract, artifact ownership, state transition, guard/failure 처리의 정본이다.

현재 이 문서에서 확정된 shared contract:
- artifact 읽기/쓰기 ownership
- `/wf-start`
- `/wf-checkpoint`
- `/wf-verify`
- `/wf-review`
- `/wf-next`
- `/wf-apply`
- failure/block/resume의 공용 처리 원칙

범위:
- 최종적으로 `/wf-*` 공용 skill semantic contract
- artifact(`plan.md`, legacy `steps.md`, `state.json`, `logs/`)의 공용 읽기/쓰기 contract
- shared failure/block/resume 처리
- shared review/guard executor boundary

비범위:
- Claude native hook wiring
- Codex preflight wiring
- tool-specific metadata / entry wiring
- adapter-specific reviewer execution 방식

## 공용 설계 참조와 구현 경계

- 공용 skill 이름, artifact 역할, state 공통 스키마 baseline, artifact 수정 기준의 정본은 이 문서와 `workflow` runtime이다
- 하위 문서의 예시/표현이 이 문서와 충돌하면 이 문서를 정본으로 본다
- `/wf-*` skill 본체는 single-source shared skill set으로 유지한다
- `state.json`, `logs/` 쓰기는 shared writer가 담당한다
- `plan.md`는 semantic markdown artifact이므로 각 skill이 직접 수정한다
- `steps.md`는 PR7 이후 신규 task에서 만들지 않는다. 기존 task의 legacy step source로만 읽기 호환한다
- review packet은 shared packet builder가 조립한다
- review log 기록과 `latest_review_ref` 갱신은 shared review sink가 담당한다
- reviewer execution만 adapter 책임이다
- guardrail 정본은 shared behavioral spec + shared guard executor다
- adapter의 hook / preflight는 guardrail 정본이 아니라 연결 계층이다
- hard enforcement는 `/wf-*` 공식 skill surface를 통해 진입할 때를 기준으로 보장한다

## Artifact 구현 계약

### plan.md

- `plan.md`는 작업 계약, 범위, 완료 조건, 검증 계획, 계약 수준의 risk/pending/note를 담는 semantic artifact다
- `plan.md`의 `Current State` section은 PR5(`PlanCurrentState` parser/writer 도입)부터 workflow 위치와 latest result pointer의 canonical source다
- `state.json`과 `plan.md`의 Current State가 충돌하면 `plan.md`를 우선한다. shared state reader는 in-memory reconcile만 수행하고, mirror 파일 갱신은 명시 `reconcile_state_from_plan` helper가 담당한다
- shared runtime은 `plan.md`의 parse 규칙이나 markdown render shape가 shared 구현에 필요한 경우에만 이 문서의 contract를 적용한다
- `Current State` section parse/render contract:
  - parse target은 top-level section title이 `Current State` 또는 `현재 상태 (Current State)`인 section이다
  - section이 없으면 pre-PR5 task로 보고 `state.json`만 읽는다
  - section이 있으면 아래 machine-readable bullet key를 사용한다
  - 기존/수동 template처럼 일부 key만 있으면 존재하는 key만 `plan.md` 우선으로 병합하고, 없는 key는 `state.json` mirror 값을 유지한다
  - keys: `schema_version`, `session_state`, `workflow_mode`, `current_phase`, `repo_profile_ref`, `workspace_baseline_ref`, `current_step_ref`, `latest_checkpoint_ref`, `latest_verification_ref`, `latest_review_ref`, `pending_approval_for`, `review_outcome`, `closure_authorized`, `counters.rework_count`, `counters.rewrite_count`, `counters.rollback_count`, `blocked_transition`, `blocked_reason_ref`, `stop_condition_ref`, `approvals_granted`, `last_updated`
  - empty value / `null` / `none` / `n/a` / `해당 없음`은 null로 해석한다
  - display keys `current_step`과 `latest_checkpoint`는 사람이 읽는 요약 전용이며 machine state로 승격하지 않는다. writer는 machine key인 `current_step_ref`와 `latest_checkpoint_ref`를 쓴다
- `Risks / Pending` section parse/render contract:
  - parse target은 top-level section title이 `Risks / Pending`이거나 `리스크 / 보류 사항 (Risks / Pending)`인 section이다
  - canonical entry shape:
    - risk entry: `- [risk] <risk_text> [basis_refs=<ref1>, <ref2>, ...]`
    - pending entry: `- [pending] <pending_text> [basis_refs=<ref1>, <ref2>, ...]`
  - legacy plain bullet은 read-only compatibility를 위해 허용하고, packet builder는 이를 opaque unresolved item으로 읽을 수 있다
  - 이 section은 contract-level unresolved risk / pending만 담는다
  - active working risk / pending의 canonical 위치는 `plan.md`의 `Working Notes` 또는 `logs/`이며, contract-level `Risks / Pending` section이 이를 대체하지 않는다
  - section이 없으면 packet builder는 empty로 간주할 수 있다
- `Contract Notes` section render shape:
  - section aliases: `Contract Notes`, `계약 메모 (Contract Notes)`
  - note entry: `- [contract-note] <note_text> [basis_refs=<ref1>, <ref2>, ...]`
  - rewrite-required entry: `- [rewrite-required] <rewrite_reason_code> [basis_ref=<ref>]`
  - section이 없으면 `/wf-apply`가 생성할 수 있다
  - `Contract Notes`는 checklist parse 대상이 아니다

### inline Steps in plan.md

- PR7 이후 신규 runbook task의 실행 가능한 step 목록과 working note는 `plan.md` 안의 top-level `Steps` / `Working Notes` section에 둔다
- 한국어 template의 `진행 단계 (Steps)`는 `Steps` section alias로 파싱한다
- 신규 task는 `steps.md`를 만들지 않는다
- 기존 `steps.md` task는 `plan.md`에 inline `Steps` section이 없거나 inline section이 성공적으로 parse됐지만 비어 있거나 template placeholder sentinel(`<!-- harness:steps-placeholder -->`)만 담고 있을 때 legacy step source로 읽을 수 있다
- `plan.md` inline `Steps` section parse가 실패하면 legacy `steps.md`로 fallback하지 않고 해당 inline plan을 canonical 오류로 차단한다
- `Steps` section parse contract:
  - execution step은 `Steps` section 안 top-level checklist item만 포함한다
  - HTML comment block은 execution step으로 파싱하지 않는다
  - `pending`은 unchecked(`- [ ]`) step이다
  - `done`은 checked(`- [x]`) step이다
  - `(go)`는 current step marker이며 `pending | done` 판정 기준과 분리된다
  - step 본문 중간의 literal `(go)` 문자열은 marker로 보지 않는다
  - marker는 no-`step_ref` inline step에서는 line 끝의 ` (go)`, legacy `[step_ref=...]` step에서는 `[step_ref=...]` 바로 앞의 ` (go)` sentinel만 의미한다
  - canonical execution step 기준 `(go)` marker는 최종적으로 `0개 또는 1개`만 허용한다. `step` / `implementation` checkpoint 진입 시에는 정확히 1개가 필요하다
  - `[step_ref=...]`는 legacy read-only compatibility field다. 신규 step writer는 `step_ref`를 발급하거나 재발급하지 않는다
  - no-`step_ref` inline step의 `current_step_ref_snapshot.step_ref`는 Python helper가 base document order에서 만든 ephemeral locator이며, persistent identity로 취급하지 않는다
- `Working Notes` section render shape:
  - section aliases: `Working Notes`, `작업 노트 (Working Notes)`
  - note entry: `- [step] <step_text>: <note_text> [basis_refs=<ref1>, <ref2>, ...]`
  - rewrite-required entry: `- [step] <step_text>: rewrite-required:<rewrite_reason_code> [basis_ref=<ref>]`
  - legacy `steps.md` fallback task에서는 기존 entry shape `- [step_ref=<id>] ...`를 유지해 중복 note를 만들지 않는다
  - `Working Notes` section이 없으면 `/wf-apply`가 생성할 수 있다

### state.json

원칙:
- `state.json`은 workflow 위치, latest result pointer, approval/block 상태, counters를 담는 machine-readable mirror다
- PR5(`PlanCurrentState` parser/writer 도입) 이후 initialized task에서 canonical state는 `plan.md`의 `Current State` section이며, `state.json`은 helper/runtime을 위한 derived mirror다
- pre-PR5 task처럼 `plan.md`에 `Current State` section이 없으면 shared reader는 기존 `state.json`만 사용한다
- `state.json`과 `plan.md` Current State가 충돌하면 shared reader는 `plan.md` 값을 우선해 in-memory state를 반환한다. `state.json` mirror 파일 갱신은 명시 reconcile helper가 수행한다
- 운영 중 mirror drift를 발견하면 `reconcile_state_from_plan` helper를 한 번 실행해 `plan.md` Current State에서 `state.json` mirror를 재생성한다
- PR5 task에서 `plan.md` Current State write가 성공하고 `state.json` mirror write만 실패한 경우는 canonical update 성공으로 취급한다. pre-PR5 task처럼 `plan.md`가 없으면 `state.json` write 실패가 canonical update 실패다
- `schema_version`은 required top-level integer field이며 현재 값은 `2`이다
- `workflow_mode`의 허용 값은 `guided | generic`이다
- `current_phase`의 허용 값은 `pre-planning | plan | step | implementation | verification | review`다
- `repo_profile_ref`는 task-level로 pin된 repo onboarding profile ref다
- `workflow_mode=guided`이면 `repo_profile_ref`는 non-null이어야 하고, `generic`이면 `null`이어야 한다
- `workspace_baseline_ref`는 `/wf-start`가 캡처한 task-local workspace baseline artifact ref다
- `workspace_baseline_ref`는 task lifetime 동안 바뀌지 않으며, task-scoped diff/fingerprint 계산의 canonical base다
- 현재 최소 구현에서 이 ref는 `logs/workspace-baseline.json` 경로를 가리킨다
- `workspace_baseline_ref`, `latest_checkpoint_ref`, `latest_verification_ref`, `latest_review_ref` 같은 task-local artifact ref는 task root 기준 상대 경로로 저장한다
- baseline artifact는 최소 `captured_at`, `workspace_root`, VCS 종류, `head_commit` 가능 여부, `git status --porcelain=v1` 결과를 담아야 한다
- baseline capture helper는 explicit `workspace_root`를 요구하며, 누락 시 current working directory로 fallback하지 않는다
- PR7 이후 current step의 canonical source는 `plan.md` inline `Steps` section의 단일 `(go)` marker다
- `current_step_ref`는 legacy mirror/read-compat field다. 신규 no-`step_ref` task에서는 Python helper가 marker의 document-order 위치에서 ephemeral locator를 쓸 수 있지만, 사람이나 skill은 이를 stable step identity로 취급하지 않는다
- `current_phase=step | implementation`이면 `current_step_ref`를 사용할 수 있지만 없어도 단일 `(go)` marker가 있으면 checkpoint guard를 통과할 수 있다
- `current_phase=pre-planning | plan | verification | review`이면 `current_step_ref=null`이어야 한다
- `pending_approval_for`의 공식 값은 `pre_plan_to_plan | plan_to_implementation | closure`이다
- `approvals_granted`는 승인점 통과 이력을 담는 정수 배열이며 `1=pre_plan_to_plan`, `2=plan_to_implementation`, `3=closure`를 의미한다
- cut-over 이전 in-flight task는 이전 승인 이력이 비어 있을 수 있으므로, 뒤 승인점을 기록할 때 누락된 앞 번호를 함께 채워 cumulative prefix를 유지한다
- `counters`는 remediation/rollback routing 진입 횟수를 기록하는 control-plane field다
- `rework_count`는 `REWORK` 경로 진입 횟수다
- `rework_count`는 execution rework와 repo-policy supplement가 낸 non-terminal `REWORK`를 함께 세는 aggregate counter다
- `rewrite_count`는 rewrite-class 경로(`REWRITE_STEP`, `REWRITE_PLAN`, 이후 추가될 `REWRITE_*`) 진입 횟수다
- `rollback_count`는 `ROLLBACK` 경로 진입 횟수다
- risk 자체는 저장하지 않고 blocker/hold 관련 제어 포인터만 허용한다
- 모든 필드는 항상 존재하고, 값이 없으면 `null`을 사용한다
- `counters` 하위 필드는 항상 정수이며 초기값은 `0`이다
- top-level 필드는 공통 스키마로 고정하고, tool-specific 확장은 `adapter_meta` 아래로만 둔다
- 기본 읽기 우선순위는 `state first -> plan -> logs on demand`
- `state.json` 쓰기는 shared state writer가 담당한다

### logs/

- `logs/`는 checkpoint, verification, review, baseline, recovery artifact를 남기는 audit trail이다
- logs 쓰기는 shared log writer가 담당한다
- log writer는 task-local ref를 task root 기준 상대 경로로 반환한다
- `APPLY_COMMIT_PARTIAL`이 발생하면 shared apply sink가 partial recovery record를 `logs/`에 남긴다
- partial recovery record는 최소 `reason_code`, `updated_artifacts`, attempted `required_artifact_actions`, `routing_basis_ref`, 발생 시각을 포함한다
- 현재 최소 구현에서 partial recovery record는 `logs/apply-recovery/*.json`에 기록하며 `record_type=apply_partial_recovery`, `status=unresolved`를 포함한다

### active repo onboarding profile

- active repo onboarding profile의 discovery/selection은 shared skill 내부 휴리스틱이 아니라 workspace configuration contract다
- active repo onboarding profile은 free-form prose가 아니라 stable field를 가진 schema instance로 취급한다
- shared core가 직접 의존하는 최소 field surface는 `profile_id`, `profile_version`, `guided_classifications`, `known_issue_selector_mapping`, `checkpoint_supplements`다
- `repo_profile_ref`는 task state에 pin되는 profile artifact locator/path이고, `profile_id`는 그 artifact 안의 stable semantic identity다
- shared core는 `repo_profile_ref`로 profile instance를 찾고, loaded payload에서 `profile_id`, `profile_version`을 읽는다
- new task에서 guided mode는 explicit config 또는 fixed workspace convention으로 단일 active `repo_profile_ref`를 resolve할 수 있을 때만 성립한다
- 현재 workspace의 기본 convention은 `contracts/repo_profile.md`를 active profile로 resolve하는 것이다
- new task에서 active profile을 resolve하지 못하면 generic mode로 간주한다
- new task `/wf-start`에서 guard/runtime에 전달되는 `workflow_mode`는 caller 임의 문자열이 아니라 shared `start.mode_resolver`가 이미 resolve한 값이어야 한다
- `/wf-start` runtime은 caller의 `workflow_mode`, `repo_profile_ref`, `adoption_kind`를 최종 신뢰하지 않고 `start.mode_resolver`를 재실행해 canonical input으로 덮어쓴다
- `explicit_repo_profile_ref`는 caller가 명시적으로 지정한 resolver input이고, `repo_profile_ref`는 resolver가 산출해 task state에 pin할 locator다
- runtime compatibility를 위해 `repo_profile_ref`가 들어오면 explicit resolver input처럼 다룰 수 있지만, 새 adapter는 `explicit_repo_profile_ref`를 사용해야 한다
- 따라서 generic fallback은 "caller가 generic이라고 주장했기 때문"이 아니라, resolver가 guided precondition을 만족하는 active profile을 찾지 못했을 때만 허용된다
- configured profile ref가 있는데 읽을 수 없으면 해당 skill은 자신의 guard reason으로 차단한다
- `/wf-start`는 resolved mode/profile을 `state.json.workflow_mode`, `state.json.repo_profile_ref`에 pin한다
- initialized task에서는 `state.json.workflow_mode`, `state.json.repo_profile_ref`가 canonical source of truth다
- downstream skill은 caller가 넘긴 string을 신뢰하지 않고, 기존 task면 먼저 state를 읽고 pinned mode/profile을 따라야 한다
- `state.json.workflow_mode=guided`인데 `state.json.repo_profile_ref`를 읽을 수 없으면 해당 skill은 자신의 guard reason으로 차단한다
- `/wf-start` 진입 전 workflow kind는 `runbook | docs_only | discussion_only | unknown` 중 하나로 resolve한다
- `runbook`은 기존 plan/steps/state/logs artifact를 생성하는 실행 workflow다
- `docs_only`, `discussion_only`, `unknown`은 `/wf-start`의 runbook artifact scaffold 대상이 아니다
- `docs_only` task의 상태 전이는 PR6 `docs_only_runtime`이 별도 `workflow_kind=docs_only` state model로 담당한다
- shared `start.mode_resolver`는 LLM이 넘긴 `workflow_kind_hint`를 primary input으로 쓰고, `request_path_refs`의 코드/문서 path 단서로 보조 검증한다
- `workflow_kind_hint`가 없고 path 단서도 없으면 `workflow_kind=unknown`, `workflow_kind_resolved=false`로 반환해 artifact 생성을 막는다
- 문서 확장자(`.md`, `.mdx`, `.rst`, `.adoc`, `.txt`)나 `docs/` 계열 경로는 `python`, `src`, `tests` 같은 코드 디렉토리명보다 우선해서 문서 단서로 본다
- 코드 단서와 문서 단서가 섞이면 path-only 판정은 `workflow_kind=unknown`으로 낮춘다
- 코드 단서와 문서 단서가 섞였더라도 `workflow_kind_hint=runbook`이면 코드 변경과 문서 갱신을 함께 하는 정상 runbook으로 허용한다
- 단일 path가 문서 단서와 코드 단서를 동시에 가지는 경우(예: `docs/scripts/setup.py`)도 mixed path로 본다
- `workflow_kind_hint=runbook`인데 path 단서가 순수 문서-only를 가리키거나, `workflow_kind_hint=docs_only | discussion_only`인데 path 단서가 코드 실행 workflow를 가리키면 `workflow_kind=unknown`으로 낮춰 artifact 생성을 막는다
- runbook `state.json`에서 `workflow_kind`는 pre-start routing input으로만 쓰며 저장하지 않는다
- docs-only `state.json`은 runbook `HarnessState`와 별개 shape로 `workflow_kind=docs_only`를 top-level에 저장한다

### task-scoped diff baseline

- `workspace_baseline_ref`는 `/wf-start` 시점의 repo 상태를 task-local로 고정한 baseline artifact ref다
- 이 baseline은 repository HEAD만이 아니라 task 시작 시점의 pre-existing dirty workspace까지 포함할 수 있는 abstract snapshot으로 취급한다
- 현재 최소 구현은 `logs/workspace-baseline.json`에 baseline metadata를 기록한다
- git repository에 `HEAD`가 아직 없으면 `head_commit=null`, `head_available=false`를 허용한다
- baseline artifact는 task 시작 시점의 `git status --porcelain=v1`, working tree diff, staged diff를 함께 기록해 pre-existing dirty workspace를 task diff에서 제외할 수 있어야 한다
- baseline artifact의 `vcs.working_tree_diff`는 raw `git diff --binary` string이다
- baseline artifact의 `vcs.staged_diff`는 raw `git diff --binary --cached` string이다
- baseline artifact는 plaintext log이므로 secret-bearing dirty diff를 남길 수 있다. 운영 환경에서는 `/wf-start` 전에 secret-bearing local changes를 정리하거나 별도 secret scan / size cap 정책을 adapter 계층에서 적용해야 한다
- task-scoped diff는 "현재 workspace"와 `workspace_baseline_ref` 사이의 factual diff다
- task-scoped diff는 repo 전체의 현재 dirty diff와 동일하다고 가정하지 않는다
- shared diff helper는 task-scoped diff에서 stable `task_diff_fingerprint`를 계산할 수 있어야 한다
- 현재 최소 구현은 git baseline artifact를 읽고, `HEAD`가 있으면 baseline HEAD와 현재 HEAD 차이, baseline 대비 바뀐 working tree/staged diff, status delta를 사용한다
- git diff 명령 일부가 실패하면 helper는 해당 실패를 `## diff-error: <kind>` 블록으로 raw diff와 fingerprint material에 포함해야 한다
- baseline에 `HEAD`가 없으면 baseline `git status --porcelain=v1`와 현재 status의 delta만으로 raw diff와 fingerprint material을 만든다
- working tree / staged diff raw output은 `## working-tree-diff` 또는 `## staged-diff` 아래에 `### baseline`, `### current` subsection으로 표현할 수 있다
- repo-profile supplement와 review packet builder는 raw workspace diff가 아니라 task-scoped diff를 사용한다

## Shared Cross-Skill Contracts

### initialization precondition

- 새 프로젝트에 하네스를 처음 도입할 때 initialization의 첫 단계는 도입 유형 판정이다.
- 도입 유형은 최소 `greenfield | legacy-small | legacy-medium | legacy-large`로 구분한다.
- 도입 유형 판정 결과는 active repo onboarding profile이나 workspace initialization metadata가 제공하는 입력으로 취급한다.
- guided mode는 도입 유형을 판정할 수 있을 때만 쓸 수 있다. 도입 유형을 판정할 수 없으면 generic mode fallback 또는 guard block 대상이다.
- guided mode를 쓰려면 도입 유형에 따라 필요한 문서 세트가 먼저 준비돼 있어야 한다.
  - `greenfield`
    - 필수: `templates/project/architecture.md`, `templates/project/code-structure.md`
  - `legacy-small`
    - 필수: `templates/project/architecture.md`
  - `legacy-medium`
    - 필수: `templates/project/architecture.md`, `templates/project/code-structure.md`
  - `legacy-large`
    - 필수: `templates/project/architecture.md`, `templates/project/code-structure.md`, `templates/project/known-issue.md`
- 이 문서들은 `/wf-start`와 repo onboarding profile이 가리키는 대상 프로젝트 문서다.
- guided minimum read set은 이 문서 세트를 읽는 계약 위에서만 성립한다.
- 따라서 initialization 단계에서 먼저 도입 유형과 필수 문서 세트를 확정하고, 그 다음 repo profile을 맞춘다.

도입 유형별 initialization completion 기준:

- `greenfield`
  - `templates/project/architecture.md`는 최소 `시스템 개요`, `전체 구조와 책임`, `데이터 흐름`을 가져야 한다
  - `templates/project/code-structure.md`는 최소 `1. 시작점`, `3. 공통 처리 플로우`를 가져야 한다
- `legacy-small`
  - `templates/project/architecture.md`는 최소 `시스템 개요`, `전체 구조와 책임`을 가져야 한다
- `legacy-medium`
  - `templates/project/architecture.md`는 최소 `시스템 개요`, `전체 구조와 책임`, `데이터 흐름`, `외부 의존성`을 가져야 한다
  - `templates/project/code-structure.md`는 최소 `1. 시작점`, `2. 주요 진입 경로`, `3. 공통 처리 플로우`를 가져야 한다
- `legacy-large`
  - `templates/project/architecture.md`는 최소 `시스템 개요`, `디렉터리 구조`, `전체 구조와 책임`, `데이터 흐름`, `외부 의존성`, `주요 분기 / 예외 경로`를 가져야 한다
  - `templates/project/code-structure.md`는 최소 `1. 시작점`, `2. 주요 진입 경로`, `3. 공통 처리 플로우`, `4. 외부 연동 경로`, `5. Known Issue 경로`를 가져야 한다
  - `templates/project/known-issue.md`는 `문서 정본과 실제 구조 불일치`를 포함해 최소 3개의 level-two known issue 섹션을 가져야 한다
  - 즉 stable entry 1개와 concrete issue 섹션 최소 2개가 필요하다

### /wf-start

**목적**
- `/wf-start`는 사용자-facing workflow entry skill이다
- shared core는 `/wf-start`의 output shape, scaffold/write 책임, initial phase contract를 고정한다
- repo-specific 작업 분류값과 최소 읽기 section map은 active repo onboarding profile schema instance가 제공한다
- `/wf-start`는 active repo onboarding profile(있으면)을 사용해 작업을 분류하고, workflow artifact scaffold를 만들고, 첫 진입 phase를 canonical state에 기록한 뒤, agent가 바로 읽어야 할 최소 문서/섹션 집합을 반환한다

**입력**
- `task_root`
- `user_request`
- `task_name_hint` (optional)
- `workflow_mode_resolved` (shared `start.mode_resolver`가 mode를 확정했는지 나타내는 boolean)
- `workflow_kind` (`runbook | docs_only | discussion_only | unknown`)
- `workflow_kind_resolved` (shared `start.mode_resolver`가 kind를 확정했는지 나타내는 boolean)

입력 원칙:
- `user_request`는 task classification과 initial phase 판정의 primary input이다
- `workflow_mode_resolved=true`여야 `/wf-start`가 mode 입력을 신뢰할 수 있다
- `workflow_kind=runbook`일 때만 `/wf-start`가 task artifact scaffold를 만든다
- `workflow_kind=docs_only | discussion_only | unknown`이면 `reason_code=START_NOT_RUNBOOK`으로 차단하고 artifact를 만들지 않는다
- `workflow_kind_resolved=false`이면 `workflow_kind=runbook` 값이 있더라도 unresolved로 보고 `reason_code=START_NOT_RUNBOOK`으로 차단한다
- `/wf-start`는 broad codebase exploration 없이, active repo onboarding profile과 사용자 요청만으로 최초 분류와 최소 읽기 목록을 결정하는 것을 기본값으로 한다
- `task_name_hint`는 directory/file naming 보조일 뿐 classification source of truth가 아니다
- active repo onboarding profile이 configured 상태인데 읽을 수 없으면 `reason_code=START_REPO_PROFILE_UNAVAILABLE`로 차단한다
- guided mode에서는 도입 유형 판정 결과와 도입 유형별 필수 문서 세트 검증 결과를 함께 가져야 한다
- guided mode에서 도입 유형을 판정할 수 없으면 `reason_code=START_PROJECT_CONTEXT_UNRESOLVED` 또는 generic mode fallback 대상으로 본다
- guided mode에서 도입 유형별 필수 문서 세트가 아직 준비되지 않았다면, 이는 initialization 미완료 상태로 취급해야 한다

**Precondition / Guard**
- runtime entry는 명시적인 `workspace_root`를 요구한다. `workspace_root`가 없으면 `reason_code=START_WORKSPACE_ROOT_MISSING`으로 차단한다
- `workspace_root`가 task 하위 경로처럼 nested path이면 shared workspace root resolver가 repo/profile/template marker까지 상위 탐색해 canonical workspace root로 정규화한다
- `user_request`가 비어 있으면 `reason_code=START_REQUEST_MISSING`으로 차단한다
- `workflow_mode_resolved != true`면 `reason_code=START_WORKFLOW_MODE_UNRESOLVED`로 차단한다
- runtime entry에서는 `start.mode_resolver`를 재실행하므로 이 reason은 주로 shared guard direct-call / adapter preflight용 defense-in-depth다
- `workflow_kind != runbook`이거나 `workflow_kind_resolved=false`이면 `reason_code=START_NOT_RUNBOOK`으로 차단한다
- active repo profile이 있는 workspace에서 resolved `workflow_mode=generic`이 들어오면 `reason_code=START_WORKFLOW_MODE_CONFLICT`로 차단한다
- `task_root`가 없으면 `/wf-start`가 생성할 수 있어야 한다
- target `task_root`에 canonical workflow artifact(`plan.md`, `state.json`, `logs/`)가 모두 있으면 `reason_code=START_TASK_ALREADY_INITIALIZED`로 차단한다. legacy `steps.md` 존재 여부는 already-initialized 판단에 필요하지 않다
- target `task_root`에 canonical workflow artifact의 strict subset만 있으면 `reason_code=START_TASK_INIT_PARTIAL`로 차단한다
- init guard에서 `logs/`는 directory 존재 여부만 본다. 빈 디렉토리도 "존재"로 간주하며, `plan.md`, `state.json`은 있는데 `logs/`만 없으면 partial initialization이다. `steps.md`만 있어도 legacy partial initialization으로 본다
- `task_root`를 만들 수 없거나 scaffold artifact를 쓸 수 없으면 `reason_code=START_TASK_ROOT_UNWRITABLE`로 차단한다
- `initial_phase`가 `pre-planning | plan`이 아니면 `reason_code=START_INITIAL_PHASE_INVALID`로 차단한다
- guided mode인데 도입 유형을 판정할 수 없으면 `reason_code=START_PROJECT_CONTEXT_UNRESOLVED`로 차단할 수 있다
- guided mode인데 도입 유형별 필수 문서 세트가 없거나 최소 작성 기준을 만족하지 않으면 `reason_code=START_INIT_REQUIRED_DOCS_MISSING`으로 차단한다
- guided mode인데 `task_classification`이 active profile에 없으면 `reason_code=START_CLASSIFICATION_INVALID`로 차단한다
- guided mode인데 `minimum_read_set`에 active profile classification이 허용하지 않은 read entry가 있으면 `reason_code=START_MINIMUM_READ_SET_INVALID`로 차단한다
- guard에 차단되면 `/wf-start`는 어떤 artifact도 생성하지 않는다
- `/wf-start`의 pre-initialization guard block은 general blocked-state write 예외다. 이 경우 `state.json`이 없을 수 있으므로 blocked 정보는 skill output으로만 반환한다

`/wf-start` reason code inventory:
- `START_WORKSPACE_ROOT_MISSING`
- `START_REQUEST_MISSING`
- `START_WORKFLOW_MODE_UNRESOLVED`
- `START_NOT_RUNBOOK`
- `START_WORKFLOW_MODE_CONFLICT`
- `START_TASK_ALREADY_INITIALIZED`
- `START_TASK_INIT_PARTIAL`
- `START_TASK_ROOT_UNWRITABLE`
- `START_INITIAL_PHASE_INVALID`
- `START_PROJECT_CONTEXT_UNRESOLVED`
- `START_INIT_REQUIRED_DOCS_MISSING`
- `START_REPO_PROFILE_UNAVAILABLE`
- `START_CLASSIFICATION_INVALID`
- `START_MINIMUM_READ_SET_INVALID`
- `START_INPUT_CONTRACT_INVALID`
- `START_GUARD_BLOCKED`

guard 해석 원칙:

- `START_PROJECT_CONTEXT_UNRESOLVED`
  - 도입 유형을 판단할 입력이 없어서 guided profile을 안전하게 적용할 수 없는 상태다
- `START_INIT_REQUIRED_DOCS_MISSING`
  - 도입 유형은 판정됐지만, 그 도입 유형에 필요한 구조 문서 세트가 없거나 최소 작성 기준을 만족하지 않는 상태다
- 이 둘은 모두 initialization 미완료 계열 block이며, `/wf-start`가 task artifact를 생성하기 전에 해결해야 한다
- `START_WORKFLOW_MODE_UNRESOLVED`
  - shared mode resolver가 실행됐다는 신뢰 표식 없이 guard가 직접 호출된 상태다
- `START_WORKFLOW_MODE_CONFLICT`
  - active profile이 있는 workspace에서 generic mode로 guard를 직접 통과하려는 상태다. runtime entry에서는 resolver 재실행으로 보통 도달하지 않는 guard-only safeguard다
- `START_NOT_RUNBOOK`
  - workflow kind가 `runbook`이 아니어서 현재 `/wf-start`가 plan/steps/state/logs scaffold를 만들 수 없는 상태다
  - document-only 본체가 있더라도 `/wf-start`는 runbook artifact만 담당하므로 이 reason은 정상 차단 결과다. docs-only task는 `/wf-docs-only`로 시작한다
- `START_INITIAL_PHASE_INVALID`
  - `/wf-start`가 직접 시작할 수 없는 phase(`step | implementation | verification | review`)가 입력된 상태다
- `START_CLASSIFICATION_INVALID`
  - guided mode에서 `task_classification`이 active repo profile의 classification inventory에 없는 상태다
- `START_MINIMUM_READ_SET_INVALID`
  - guided mode에서 `minimum_read_set`에 active repo profile의 해당 classification이 허용하지 않은 read entry가 포함된 상태다

**task classification 규칙**
- semantic baseline은 `/wf-start` 역할과 active repo onboarding profile을 따른다
- shared core는 repo-specific classification inventory를 직접 정의하지 않는다
- `task_classification`은 active repo onboarding profile schema가 정의하는 stable token이다
- repo onboarding profile이 있는 guided mode에서는 profile이 classification inventory, class별 read map, known-issue selector mapping을 제공한다
- repo onboarding profile이 없는 generic mode에서는 `task_classification=generic`을 허용한다
- guided mode의 repo-specific class 의미는 shared core가 아니라 profile 문서가 정본이다
- guided mode에서 classification은 도입 유형과 사용자 요청을 함께 고려해 해석할 수 있어야 한다

**초기 phase 결정**
- repo onboarding profile은 classification별 `default_initial_phase_hint`를 제공할 수 있다
- `/wf-start`는 profile hint가 있더라도, 사용자 요청만으로 범위/접근/요구사항이 충분히 고정되지 않았으면 `current_phase=pre-planning`으로 시작할 수 있다
- profile hint가 없으면 기본은 `request ambiguous -> pre-planning`, 아니면 `plan`이다
- `/wf-start`는 `step | implementation | verification | review`로 직접 시작하지 않는다

**최소 읽기 목록 결정**
- `/wf-start`는 `minimum_read_set`을 구조화된 section ref 목록으로 반환한다
- 각 항목은 최소 `doc_path`, `section_selector`, `why`를 가진다
- guided profile schema가 제공하는 read entry는 typed selector contract를 함께 가진다
- typed selector contract의 최소 추가 field는 `read_target_kind`, `selector_type`다
- shared core는 cross-repo minimum surface로 `doc_path`, `section_selector`, `why`를 보장하고, guided profile이 제공한 `read_target_kind`, `selector_type`를 손실 없이 전달해야 한다
- `section_selector`는 `selector_type`과 함께 해석한다
- guided mode에서는 active repo onboarding profile이 도입 유형과 `task_classification`, 사용자 요청의 직접 단서를 바탕으로 `minimum_read_set`을 결정한다
- shared runtime은 guided `minimum_read_set`을 exact-match로 강제하지 않고, active profile classification이 허용한 read entry의 subset인지 확인한다
- generic mode에서는 `minimum_read_set=[]`를 허용한다
- repo onboarding profile은 domain-specific read set의 합집합 대신 initial triage용 최소 공통 set을 반환하도록 정의할 수 있다
- `/wf-start`는 이 목록에 phase 문서를 중복 포함하지 않는다. main workflow/orchestrator는 반환된 `minimum_read_set`에 더해 initial phase 문서를 따로 읽는다
- 현재 workspace repo의 guided profile schema instance는 [repo_profile.md](contracts/repo_profile.md)에 정의한다

**출력**
최소:
- `task_classification`
- `initial_phase`
- `minimum_read_set`
- `repo_profile_ref`
- `phase_doc_ref`
- `created_artifacts`
- `reason_code`

출력 원칙:
- `repo_profile_ref`는 guided mode면 active profile ref, generic mode면 `null`이다
- `repo_profile_ref`는 `/wf-start`가 state에 pin한 profile ref를 echo한 값이다
- `phase_doc_ref`는 `phases/pre-planning.md | phases/plan.md` 중 하나다
- `created_artifacts`는 실제로 생성/보장된 artifact path 목록을 담는다
- `reason_code`는 성공 시 `null`이다
- guard block이면 output shape는 유지하되 `task_classification=null`, `initial_phase=null`, `minimum_read_set=[]`, `repo_profile_ref=null`, `phase_doc_ref=null`, `created_artifacts=[]`, `reason_code=<non-null>`로 반환한다
- main workflow/orchestrator는 `minimum_read_set`, `repo_profile_ref`, `phase_doc_ref`를 plan의 `References` seed로 사용할 수 있다

**생성/보장 대상**
- `plan.md` scaffold
- `state.json`
- `logs/` 디렉토리

**초기 verification gate 계약**
- `/wf-start`는 최초 initialization 1회에 한해 `plan.md`의 `Verification` section에 task-local verification gate contract를 scaffold한다
- 이후 `/wf-start` 재실행은 guard가 차단하므로 기존 verification gate contract를 덮어쓰지 않는다
- guided mode에서는 resolved `adoption_kind`와 `task_classification`을 기록하고, active repo profile의 `verification_gate_templates[adoption_kind]`가 있으면 이를 초기값으로 사용한다
- profile template이 없거나 generic mode이면 shared fallback template을 사용하되, 특정 테스트/린트/빌드 명령을 고정하지 않고 `<define before verification>` placeholder를 남긴다
- 초기 contract는 baseline일 뿐이며, 작업 중 새 위험이나 범위 변경이 발견되면 plan/checkpoint/apply flow를 통해 검증 게이트를 추가하거나 수정할 수 있다
- `/wf-verify`는 항상 최신 `plan.md`의 `Verification` contract를 canonical input으로 사용한다

**state.json 초기값**
- `/wf-start`는 같은 값을 `plan.md`의 `Current State` section에도 기록한다
- `/wf-start`는 `plan.md` scaffold 생성 후 initial state writer를 호출해야 한다. 이 순서가 깨지면 initial `Current State` mirror가 생성되지 않는다
- `schema_version=2`
- `session_state=in_progress`
- `workflow_mode=<guided | generic>`
- `current_phase=<initial phase>`
- `repo_profile_ref=<resolved profile ref | null>`
- `workspace_baseline_ref=<captured baseline ref>`
- `current_step_ref=null`
- `latest_checkpoint_ref=null`
- `latest_verification_ref=null`
- `latest_review_ref=null`
- `pending_approval_for=null`
- `approvals_granted=[]`
- `review_outcome=null`
- `closure_authorized=false`
- `counters.rework_count=0`
- `counters.rewrite_count=0`
- `counters.rollback_count=0`
- `blocked_transition=null`
- `blocked_reason_ref=null`
- `stop_condition_ref=null`
- `last_updated=<creation timestamp>`
- `adapter_meta={}`

**artifact scaffold 원칙**
- `plan.md`는 contract section scaffold만 만든다. `/wf-start`가 plan 본문 의미를 채우지 않는다
- `plan.md` scaffold는 downstream reader가 기대하는 top-level section(`Goal`, `Scope`, `DoD`, `Constraints`, `Risks / Pending`, `Contract Notes`, `Steps`, `Working Notes`)을 포함할 수 있다
- `/wf-start`는 `steps.md`를 만들지 않는다
- `/wf-start`는 첫 `(go)` step이나 `current_step_ref`를 만들지 않는다

**쓰기 책임**
- `task_root` 디렉토리가 없으면 `/wf-start`가 생성한다
- `plan.md` scaffold 생성은 `/wf-start`가 담당한다
- task-local workspace baseline capture는 `/wf-start`가 요청하고 shared snapshot/state writer가 `logs/workspace-baseline.json` ref를 `workspace_baseline_ref`에 기록한다
- baseline capture는 `/wf-start`에서 정규화된 explicit `workspace_root`를 사용하며, helper 내부에서 `cwd`를 추론하지 않는다
- 초기 `state.json` 기록은 shared state writer가 담당한다
- `logs/` 디렉토리 생성은 `/wf-start`가 담당한다
- `/wf-start`는 checkpoint/verification/review log artifact를 만들지 않는다

**후속 handoff**
- main workflow/orchestrator는 `/wf-start` 결과의 `minimum_read_set`, `repo_profile_ref`, `phase_doc_ref`만 읽고 initial phase로 진입한다
- `/wf-start`가 반환한 section ref는 이후 plan의 `References` section에 기록할 seed input으로 사용한다
- initial phase가 `pre-planning`이면 agent는 먼저 범위/접근/요구사항을 닫고, `plan`이면 곧바로 stable contract plan 작성으로 들어간다

**하지 않는 것**
- semantic plan 작성
- step 분해
- approval 상태 생성
- verification/review result 생성
- broad codebase exploration 수행

### /wf-docs-only

**목적**
- `/wf-docs-only`는 문서-only 요청을 runbook plan/steps/checkpoint 흐름과 분리해 추적하는 deterministic helper surface다
- `/wf-start`는 여전히 `workflow_kind=docs_only` 요청에 대해 `START_NOT_RUNBOOK`을 반환하고 runbook artifact를 만들지 않는다
- docs-only task가 필요하면 caller는 `wf-docs-only-runtime`을 직접 호출해 docs-only state를 만들고 전이시킨다

**상태 모델**
- state file: task root의 `state.json`
- runbook `HarnessState`와 shape가 다르며, runbook runtime은 이 state를 읽지 않는다
- fields:
  - `schema_version=1`
  - `workflow_kind=docs_only`
  - `docs_state=discussion | proposal_visualized | proposal_accepted | diff_presented | applied`
  - `user_request`
  - `target_doc_refs`
  - `proposal_ref`
  - `diff_ref`
  - `applied_ref`
  - `last_event_ref`
  - `event_history_refs`
  - `last_updated`
  - `adapter_meta`
- docs-only state는 `session_state`, `current_phase`, `pending_approval_for`, `approvals_granted`를 사용하지 않는다

**전이**
- `start`: no state -> `discussion`
- `present_proposal`: `discussion` -> `proposal_visualized`
- `accept_proposal`: `proposal_visualized` -> `proposal_accepted`
- `present_diff`: `proposal_accepted` -> `diff_presented`
- `apply`: `diff_presented` -> `applied`
- 각 event는 `logs/docs-only/*.json`에 event log를 남기고 `last_event_ref` / `event_history_refs`를 갱신한다
- `present_proposal`, `present_diff`, `apply`는 caller가 넘긴 `artifact_ref`를 각각 `proposal_ref`, `diff_ref`, `applied_ref`로 저장한다. 없으면 해당 event log ref를 저장한다
- `accept_proposal`의 `artifact_ref`는 state pointer로 승격하지 않고 event log 근거로만 남긴다
- start 이후 event의 `adapter_meta`는 기존 state의 `adapter_meta`에 merge하며, 같은 key는 최신 event input이 우선한다

**분리 가드**
- docs-only runtime은 `plan.md` 또는 `steps.md`가 이미 있는 task root에서 start하지 않는다
- docs-only runtime은 runbook 승인 event(`GO`, `GO_WITH_NOTE`, `DONE`, `DONE_WITH_NOTE`)를 받으면 차단한다
- docs-only state payload에 `session_state=awaiting_approval` 또는 runbook `pending_approval_for` token이 섞이면 차단한다
- docs-only flow에는 `awaiting_approval` 상태가 없다. proposal acceptance는 `accept_proposal` event로만 기록한다
- docs-only state는 docs-only runtime만 읽는다. runbook state reader는 `workflow_kind=docs_only` state를 runbook v1으로 마이그레이션하거나 재작성하지 않고 `STATE_ARTIFACT_INVALID` 계열 차단으로 처리한다

`/wf-docs-only` reason code inventory:
- `DOCS_ONLY_KIND_UNRESOLVED`
- `DOCS_ONLY_KIND_INVALID`
- `DOCS_ONLY_REQUEST_MISSING`
- `DOCS_ONLY_ALREADY_INITIALIZED`
- `DOCS_ONLY_RUNBOOK_ARTIFACT_PRESENT`
- `DOCS_ONLY_TASK_ROOT_UNWRITABLE`
- `DOCS_ONLY_STATE_MISSING`
- `DOCS_ONLY_SUMMARY_MISSING`
- `DOCS_ONLY_STATE_INVALID`
- `DOCS_ONLY_EVENT_INVALID`
- `DOCS_ONLY_TRANSITION_INVALID`
- `DOCS_ONLY_STATE_UPDATE_FAILED`
- `DOCS_ONLY_RUNBOOK_APPROVAL_BLOCKED`

**Python helper boundary**
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-docs-only-runtime`
- Python은 event/state validation, state write, event log write만 담당한다
- LLM은 문서 proposal과 diff 설명을 사용자에게 보여주고, 해당 단계가 완료됐음을 구조화된 event로 helper에 넘기는 책임만 가진다

### stop-condition evidence model

- stop-condition hard enforcement의 source of truth는 `state.json` 단독이 아니라 `state.json + relevant result logs`다
- `state.json.counters`는 fast-path summary cache이며, 원인/step 동일성까지 단독으로 증명하지 않는다
- 후퇴/차단 계열 result artifact는 `primary_cause_code`와 `reason_fingerprint`를 함께 가져야 한다
- `primary_cause_code`는 result producer가 관리하는 stable kebab-case token이다
- `primary_cause_code`는 human summary를 그대로 쓰지 않는다
- `reason_fingerprint` 형식은 `<producer_scope>|<judgement_code>|<location_key>|<primary_cause_code>`다
- `producer_scope`는 `checkpoint:<phase> | verify | review` 중 하나다
- `location_key`는 step-bound judgement면 `step:<step_ref>`, 아니면 `task`다
- summary 문구, line number, timestamp, 실행 횟수 같은 변동값은 `reason_fingerprint`에 넣지 않는다
- 복수 원인이 있더라도 stop-condition 비교용 `primary_cause_code`는 1개만 고른다
- 같은 원인 비교가 필요한 조건은 result artifact의 `reason_fingerprint`를 canonical key로 사용한다
- 같은 `(go)` step 비교가 필요한 조건은 result artifact의 `current_step_ref_snapshot.step_ref`를 canonical key로 사용한다
- `/wf-checkpoint`, `/wf-verify`, `/wf-review` 중 후퇴/차단 계열 판정을 낼 수 있는 result artifact는 모두 `reason_fingerprint` 필드를 가져야 한다
- `reason_fingerprint`는 caller hint가 아니라 result-producing skill이 정규화해 만든다
- `REWORK`, `REWRITE_*`, `ROLLBACK`, `HOLD` 판정에서 `reason_fingerprint`는 필수다
- shared guard executor는 stop-condition 평가 시 기본적으로 `state -> latest relevant result -> historical logs on demand` 순서로 읽는다
- 구현 편의상 `counters`만으로 바로 판정 가능한 조건은 fast-path로 처리할 수 있지만, fast-path 결과가 historical evidence와 충돌하면 logs 기준을 우선한다
- repo-policy supplement는 verification 진입 차단용 non-execution `REWORK`를 낼 수 있다
- 이런 `REWORK`도 aggregate audit 목적의 `rework_count`에는 포함되지만, "implementation에서 같은 `(go)` step REWORK 2회" 같은 자동 중지 조건은 `current_step_ref_snapshot`와 `reason_fingerprint`를 함께 보며 `repo-doc-sync-*` 원인만으로 충족된 것으로 간주하지 않는다

## 각 skill 구현 명세

### /wf-verify result contract

- semantic role은 verification phase 문서와 `/wf-next(source=verify)` routing contract를 따른다
- shared 구현이 `/wf-next`와 합의해야 하는 최소 result shape만 고정한다
- 최소 필드:
  - `verification_ref`
  - `judgement_code`
  - `summary`
  - `verification_items`
  - `basis_refs`
  - `note_signals`
  - `verified_task_diff_fingerprint`
  - `stop_condition_code`
  - `primary_cause_code`
  - `reason_fingerprint`
- `judgement_code`의 허용 집합은 verification phase 문서의 허용 판정 집합을 따른다
- `note_signals` shape은 `/wf-checkpoint`와 같지만 `note_target_hint=plan`만 허용한다
- `judgement_code != GO_WITH_NOTE`이면 `note_signals=[]`다
- `judgement_code = GO_WITH_NOTE`이면 `note_signals`는 1개 이상이어야 한다
- `judgement_code`가 `REWORK | REWRITE_STEP | REWRITE_PLAN | ROLLBACK | HOLD`면 `primary_cause_code`는 필수다
- `judgement_code`가 `REWORK | REWRITE_STEP | REWRITE_PLAN | ROLLBACK | HOLD`면 `reason_fingerprint`는 필수다
- `reason_fingerprint`는 위 `stop-condition evidence model`의 canonical format을 따른다
- `judgement_code`가 `GO | GO_WITH_NOTE`면 `primary_cause_code=null`이어도 된다
- `judgement_code`가 `GO | GO_WITH_NOTE`면 `reason_fingerprint=null`이어도 된다
- `verified_task_diff_fingerprint`는 verification 종료 시점의 task-scoped diff fingerprint다
- `verified_task_diff_fingerprint`는 항상 필드로 존재하며 non-null이어야 한다
- `current_step_ref_snapshot`은 `/wf-verify` result contract에 포함하지 않는다
- `/wf-next`는 `/wf-verify` result에서 최소 `judgement_code`, `note_signals`, `stop_condition_code`, `reason_fingerprint`, `basis_refs`를 소비할 수 있어야 한다

### /wf-review result contract

- semantic role은 review phase 문서와 `/wf-next(source=review)` routing contract를 따른다
- shared 구현이 `/wf-next`와 합의해야 하는 최소 result shape만 고정한다
- 최소 필드:
  - `review_ref`
  - `judgement_code`
  - `summary`
  - `out_of_scope_change`
  - `key_issues`
  - `verification_blind_spots`
  - `carry_forward_notes`
  - `basis_refs`
  - `verified_task_diff_fingerprint`
  - `primary_cause_code`
  - `reason_fingerprint`
- `judgement_code`의 허용 집합은 `DONE | DONE_WITH_NOTE | REWORK | REWRITE_PLAN | HOLD`다
- `out_of_scope_change=yes`면 `judgement_code=DONE | DONE_WITH_NOTE`를 사용할 수 없다
- `judgement_code=DONE_WITH_NOTE`면 `carry_forward_notes`는 1개 이상이어야 한다
- `judgement_code`가 `REWORK | REWRITE_PLAN | HOLD`면 `primary_cause_code`는 필수다
- `judgement_code`가 `REWORK | REWRITE_PLAN | HOLD`면 `reason_fingerprint`는 필수다
- `reason_fingerprint`는 위 `stop-condition evidence model`의 canonical format을 따른다
- `judgement_code`가 `DONE | DONE_WITH_NOTE`면 `primary_cause_code=null`이어도 된다
- `judgement_code`가 `DONE | DONE_WITH_NOTE`면 `reason_fingerprint=null`이어도 된다
- `carry_forward_notes`는 항상 필드로 존재하며, 없으면 빈 배열이다
- `verified_task_diff_fingerprint`는 review packet과 latest verification freshness check에 사용한 task-scoped diff fingerprint다
- `DONE_WITH_NOTE`의 note 내용은 review log와 closure summary에 남기며, `/wf-next`가 별도 `plan`/`steps` artifact action으로 변환하지 않는다
- reviewer는 `REWRITE_STEP`을 직접 출력하지 않는다
- shared routing default는 `review / REWORK -> step`이다. reviewer가 execution history를 직접 보지 않더라도, 메인 workflow는 종료 불가인 실행 remediation을 step phase 재개로 정규화한다
- `review / REWORK -> step` 경로에서는 `/wf-next`가 `current_step_ref_snapshot`을 합성하지 않는다. step 재구성은 step phase에서 메인 에이전트가 수행한다

### /wf-checkpoint

**목적**
- `/wf-checkpoint`는 `pre-planning | plan | step | implementation` phase의 checkpoint self-check를 수행하고, 구조화된 checkpoint result artifact를 남긴다
- `verification`, `review`는 각각 `/wf-verify`, `/wf-review`의 전용 result artifact를 사용하므로 `/wf-checkpoint` 범위에서 제외한다
- 따라서 `/wf-checkpoint`의 `judgement_code`는 대상 phase 문서가 허용한 판정만 가질 수 있으며, `DONE`, `DONE_WITH_NOTE`는 여기서 나오지 않는다

**입력**
- `task_root`
- `phase`
- `caller_summary_hint` (optional)
- `candidate_basis_refs` (optional)

입력 원칙:
- `caller_summary_hint`, `candidate_basis_refs`는 모두 caller가 주는 optional, non-authoritative hint다
- `/wf-checkpoint`는 이를 탐색 보조로만 사용할 수 있다
- 최종 판정은 phase 문서, artifact, workspace evidence를 다시 읽어 내려야 하며, caller hint를 source of truth로 쓰면 안 된다

**Precondition / Guard**
- runtime entry는 명시적인 `workspace_root`를 요구한다. `workspace_root`가 없으면 `reason_code=CHECKPOINT_WORKSPACE_ROOT_MISSING`으로 차단한다
- `workspace_root`가 task 하위 경로처럼 nested path이면 shared workspace root resolver가 repo/profile/template marker까지 상위 탐색해 canonical workspace root로 정규화한다
- `state.json`이 없으면 `reason_code=STATE_ARTIFACT_MISSING`으로 차단한다
- `state.json`이 runbook state가 아니거나 읽을 수 없는 shape이면 `reason_code=STATE_ARTIFACT_INVALID`로 차단하며, 파일을 마이그레이션하거나 재작성하지 않는다
- `state.json.current_phase`가 canonical이다
- 입력 `phase`는 checkpoint 템플릿 선택과 호출 의도 확인용이다
- `phase != state.json.current_phase`이면 override가 아니라 invalid context다
- 이 경우 shared guard executor가 `CHECKPOINT_PHASE_MISMATCH`로 차단한다
- `state.json.workflow_mode=guided`인데 `state.json.repo_profile_ref`를 읽을 수 없으면 guard가 `CHECKPOINT_REPO_PROFILE_UNAVAILABLE`로 차단한다
- `/wf-start`는 어떤 phase checkpoint보다 먼저 `task_root/plan.md` scaffold를 생성해야 한다
- 따라서 `/wf-checkpoint`는 모든 대상 phase에서 `plan.md` 존재를 전제로 한다
- pre-planning의 `plan.md`는 완성본이 아니라 scaffold/draft 상태일 수 있다
- `plan.md`가 없으면 guard가 `PLAN_ARTIFACT_MISSING`으로 차단한다
- `step`, `implementation`에서는 `plan.md` inline `Steps` 또는 legacy `steps.md`에 정확히 1개의 `(go)` marker가 있어야 한다. `current_step_ref`가 있어도 marker 검증을 대체할 수 없다. marker가 없거나 2개 이상이거나 Steps section이 invalid이면 `CHECKPOINT_CURRENT_STEP_REF_MISSING`으로 차단한다
- `state.json.current_phase`가 `/wf-checkpoint` 대상이 아니면 `reason_code=CHECKPOINT_PHASE_UNSUPPORTED`로 차단한다
- phase 문서의 checkpoint spec을 읽을 수 없으면 `reason_code=CHECKPOINT_PHASE_SPEC_UNAVAILABLE`로 차단한다
- guard에 차단되면 `/wf-checkpoint`는 checkpoint result artifact를 만들지 않는다
- checkpoint blocked output은 `reason_code`와 함께 operator-facing `message_summary`를 포함한다

**읽는 artifact / 참조**
항상:
- `state.json`
- 해당 phase 문서의 `Checkpoint` 섹션
- judgement rules
- stop-conditions
- `plan.md`

조건부:
- `step`, `implementation`이면 `plan.md` inline `Steps`의 단일 `(go)` step 주변 문맥. `plan.md`에 inline `Steps` section이 없는 legacy task에서는 `steps.md`를 read-only compatibility source로 읽을 수 있다
- guided mode에서 active repo onboarding profile
- active repo onboarding profile이 phase-specific checkpoint supplement를 정의하면 그 supplement가 요구하는 추가 repo artifact/doc
- caller가 넘긴 `candidate_basis_refs`
- 필요한 workspace evidence

읽기 원칙:
- 기본 우선순위는 `state -> phase checkpoint spec -> plan inline steps -> legacy steps.md -> evidence`다
- phase별 허용 판정 집합의 canonical source는 각 phase 문서의 `Checkpoint > 판정` 섹션이다
- phase 문서가 fenced YAML `phase_spec` block을 제공하면 shared loader는 그 block의 `checkpoint_items`, `allowed_judgements`를 우선 canonical source로 사용한다. fenced spec block이 없을 때만 markdown `Checkpoint` section을 fallback parser로 읽는다
- phase spec block은 fence info가 `yaml phase-spec`이어야 하며, top-level `phase_spec:` mapping을 가져야 한다
- `phase_spec.phase`는 문서 phase와 같아야 한다
- `phase_spec.checkpoint_items`는 non-empty string list이며 list order가 canonical `check_items[*].item_index` 순서다
- `phase_spec.allowed_judgements`는 non-empty judgement token list이며, shared judgement token 집합(`GO`, `GO_WITH_NOTE`, `HOLD`, `REWORK`, `REWRITE_STEP`, `REWRITE_PLAN`, `ROLLBACK`, `DONE`, `DONE_WITH_NOTE`)의 부분집합이어야 한다
- phase spec YAML은 harness-owned subset만 지원한다: mapping, list, scalar string/int/bool/null, quoted string, `#` comment. anchors, aliases, multiline scalar, flow collection, custom tag는 지원하지 않는다
- `phase_spec`이 아닌 YAML fence는 loader가 무시한다
- judgement rules는 허용 판정 집합 정의가 아니라, 판정 이후의 transition semantics를 정의한다
- `/wf-checkpoint`는 최종 `judgement_code`가 해당 phase 문서의 허용 집합 안에 있는지 검증해야 한다
- repo profile supplement의 `reads[*]`는 profile schema의 typed read-entry contract에 따라 해석한다

**평가 규칙**
- phase 문서의 checkpoint 항목을 순서대로 평가한다
- active repo onboarding profile이 있으면, base checkpoint candidate를 만든 뒤 phase-specific checkpoint supplement를 추가 적용할 수 있다
- `base checkpoint candidate`는 내부 평가 상태이며 별도 출력 필드로 노출하지 않는다
- 각 항목은 최소 `item_index`, `item_text`, `result`, `rationale`, `basis_refs`를 가진다
- `rationale`은 모든 항목에서 필수다
- 근거 없는 `YES`는 허용하지 않는다
- `YES`인 항목은 `basis_refs`가 반드시 1개 이상 있어야 한다
- 근거를 확보하지 못하면 `YES`가 아니라 `NO` 또는 `N/A`로 처리한다
- `N/A`도 왜 해당 없음인지 근거를 남긴다
- 전체 항목 결과와 phase별 허용 판정 집합을 바탕으로 가장 작은 적절한 판정을 선택한다
- repo profile supplement는 base candidate를 유지하거나, 해당 phase 문서의 허용 판정 집합 안에서만 override할 수 있다
- repo profile supplement가 candidate를 override하면 override 근거를 `summary`, `basis_refs`, 필요 시 `primary_cause_code`, `reason_fingerprint`에 반영한다
- checkpoint output의 `judgement_code`, `summary`, `basis_refs`, `primary_cause_code`, `reason_fingerprint`는 항상 supplement 적용 후의 최종 candidate를 나타낸다
- supplement override는 synthetic checkpoint item을 추가로 만들지 않는다. `check_items`는 phase 문서의 base evaluation만 반영하고, 최종 판정 변경 근거는 top-level `summary`, `basis_refs`, `primary_cause_code`, `reason_fingerprint`에서 확인한다
- guided mode에서 guard가 repo profile을 성공적으로 load한 경우 checkpoint log는 `repo_profile_context` metadata를 남길 수 있다. 최소 field는 `profile_id`, `profile_version`, `applicable_checkpoint_supplements`이며, runtime은 `GuardDecision.repo_profile`을 single-invocation handoff로 사용해 profile을 다시 load하지 않는다
- `applicable_checkpoint_supplements`는 phase-targeting metadata이며, supplement activation predicate 평가 결과나 실제 적용 완료 목록이 아니다
- 후퇴 계열 잠정 판정이면 stop condition도 함께 평가한다
- stop condition이 걸려도 `judgement_code`를 의미적으로 덮어쓰지 않고, `stop_condition_code`를 별도 기록한다
- semantic routing은 `/wf-checkpoint` 책임이 아니다
- 현재 workspace repo의 repo-specific supplement는 [repo_profile.md](contracts/repo_profile.md)의 `checkpoint_supplements.implementation_exit_doc_sync`를 따른다

**GO_WITH_NOTE 처리**
- `GO_WITH_NOTE`의 NOTE는 log-only가 아니다
- `GO_WITH_NOTE`는 진행 가능하지만 note가 있는 판정이다. review outcome의 `DONE_WITH_NOTE`와 의미 구조는 같지만, review 이후에는 다음 phase가 없으므로 `DONE` prefix를 사용한다
- `GO_WITH_NOTE`이면 반드시 구조화된 `note_signals`를 출력한다
- `note_signals`는 1개 이상의 note object를 담는 배열이다
- 각 note object는 최소 `note_text`, `note_basis_refs`, `note_target_hint`를 가진다
- 각 `note_target_hint`는 `plan | steps` 중 하나다
- phase별 target 제약:
  - `pre-planning`, `plan`에서는 `note_target_hint=plan`만 허용한다
  - `step`, `implementation`에서는 `note_target_hint=plan | steps`를 모두 허용한다
- `plan`은 contract-level risk, constraint, approval-relevant caveat일 때 사용한다
- `steps`는 working risk, pending, execution-level follow-up일 때 사용한다
- `pre-planning`, `plan`에서 보이는 execution-level caution도 future `steps` note로 미루지 않고 `plan` note로 승격한다
- `note_target_hint=steps`는 `current_step_ref_snapshot != null`인 checkpoint output에서만 허용한다
- note의 의미 분류는 `/wf-checkpoint`가 담당한다
- artifact action 생성은 `/wf-next`가 담당한다
- 실제 `plan.md` 반영은 `/wf-apply`가 담당한다. legacy `steps.md`는 plan inline section이 없는 기존 task의 compatibility source다

**출력**
- `checkpoint_ref`
- `phase`
- `judgement_code`
- `summary`
- `check_items`
- `basis_refs`
- `note_signals`
- `stop_condition_code`
- `primary_cause_code`
- `reason_fingerprint`
- `current_step_ref_snapshot`

출력 필드 의미:
- `summary`는 checkpoint 판정 근거에 대응하는 1-2문장 요약이다
- `check_items[*].item_index`는 해당 phase checkpoint 항목의 평가 순서를 나타낸다
- `check_items`는 phase spec의 checkpoint 항목 개수와 순서를 모두 반영해야 하며, `item_index`는 `1..N` 순서여야 한다
- `check_items[*].item_text`는 평가한 checkpoint 항목을 사람이 읽을 수 있게 설명하는 non-empty text다. runtime은 phase spec 원문과의 글자 단위 일치를 요구하지 않는다
- `check_items[*].result`는 `YES | NO | N/A` 중 하나다
- `check_items[*].basis_refs`는 각 checkpoint 항목의 개별 판정 근거 ref다
- top-level `basis_refs`는 최종 `judgement_code`와 `summary`를 지지하는 근거 ref 집합이다
- 즉 `check_items[*].basis_refs`는 항목별 상세 근거이고, top-level `basis_refs`는 최종 판정 요약 근거다
- `current_step_ref_snapshot`은 최소 `step_ref`, `step_text`, `go_marker_present`를 가진다
- `step_ref`는 legacy `[step_ref=...]`가 있으면 그 값을 담고, no-ref inline step이면 Python helper가 marker의 document-order 위치에서 만든 ephemeral locator를 담는다. 이 값은 persistent identity가 아니다. checkpoint persistence는 no-ref inline step의 prompt-supplied `step_ref`를 canonical marker snapshot으로 normalize할 수 있지만, legacy stable `step_ref`는 marker snapshot과 일치해야 한다
- `step_text`는 snapshot 시점의 execution step text이며 `(go)` marker sentinel은 포함하지 않는다
- `go_marker_present`는 snapshot 시점에 해당 step에 `(go)` marker가 있었는지를 나타낸다
- `primary_cause_code`는 remediation/hold 판단의 primary cause를 나타내는 stable token이다
- `reason_fingerprint`는 stop-condition에서 "같은 원인" 판정을 할 때 쓰는 normalized key다
- `judgement_code`가 `REWORK | REWRITE_* | ROLLBACK | HOLD`면 `primary_cause_code`는 필수다
- `judgement_code`가 `REWORK | REWRITE_* | ROLLBACK | HOLD`면 `reason_fingerprint`는 필수다
- `reason_fingerprint`는 위 `stop-condition evidence model`의 canonical format을 따른다
- `judgement_code`가 `GO | GO_WITH_NOTE`면 `primary_cause_code=null`이어도 된다
- `judgement_code`가 `GO | GO_WITH_NOTE`면 `reason_fingerprint=null`이어도 된다

null 규칙:
- `note_signals`는 항상 필드로 존재한다
- `judgement_code != GO_WITH_NOTE`이면 `note_signals = []`다
- `judgement_code = GO_WITH_NOTE`이면 `note_signals`는 1개 이상의 note object를 가져야 한다
- `stop_condition_code`는 항상 필드로 존재한다
- 매칭된 stop condition이 없으면 `stop_condition_code = null`이다
- `primary_cause_code`는 항상 필드로 존재한다
- `reason_fingerprint`는 항상 필드로 존재한다
- `current_step_ref_snapshot`은 항상 필드로 존재한다
- `pre-planning`, `plan`에서는 `current_step_ref_snapshot = null`이다
- `step`, `implementation`에서는 현재 step 문맥 snapshot이다
- `step`, `implementation`인데 snapshot을 만들 수 없으면 output에서 `null`로 흘리지 않고 guard 단계에서 차단한다

`/wf-checkpoint` reason code inventory:
- `CHECKPOINT_WORKSPACE_ROOT_MISSING`
- `STATE_ARTIFACT_MISSING`
- `STATE_ARTIFACT_INVALID`
- `CHECKPOINT_PHASE_MISMATCH`
- `CHECKPOINT_PHASE_UNSUPPORTED`
- `CHECKPOINT_REPO_PROFILE_UNAVAILABLE`
- `PLAN_ARTIFACT_MISSING`
- `CHECKPOINT_CURRENT_STEP_REF_MISSING`
- `CHECKPOINT_PHASE_SPEC_UNAVAILABLE`
- `CHECKPOINT_RESULT_CONTRACT_INVALID`
- `CHECKPOINT_JUDGEMENT_INVALID`
- `CHECKPOINT_NOTE_SIGNALS_INVALID`
- `CHECKPOINT_REASON_REQUIRED`
- `CHECKPOINT_CURRENT_STEP_SNAPSHOT_INVALID`
- `CHECKPOINT_NOTE_TARGET_INVALID`
- `CHECKPOINT_CHECK_ITEMS_INCOMPLETE`
- `CHECKPOINT_CHECK_ITEM_INVALID`
- `CHECKPOINT_GUARD_BLOCKED`

**쓰기 책임**
- checkpoint result/log 생성은 shared writer가 담당한다
- checkpoint result writer는 `checkpoint_ref`가 포함된 최종 payload를 1-pass write로 남겨야 하며, placeholder result를 먼저 쓰고 같은 파일을 재작성하지 않는다
- `state.json.latest_checkpoint_ref` 갱신은 shared writer가 담당한다
- `/wf-checkpoint`는 `session_state`, `current_phase`, `pending_approval_for`, `review_outcome`, `closure_authorized`를 직접 수정하지 않는다
- `/wf-checkpoint`는 `plan.md` 또는 legacy `steps.md`를 직접 수정하지 않는다

**후속 handoff**
- `/wf-next`는 `latest_checkpoint_ref`가 가리키는 checkpoint result를 읽는다
- `/wf-next`는 `judgement_code`, `stop_condition_code`, `note_signals`, `reason_fingerprint`를 해석해 `required_artifact_actions`와 state transition을 만든다
- `/wf-apply`는 그 structured action을 적용해 `plan.md` inline step sections를 수정한다

**하지 않는 것**
- next phase 결정
- next session state 결정
- approval 처리
- 다음 `(go)` step 선정
- `required_artifact_actions` 직접 생성
- `plan.md` 또는 legacy `steps.md` 직접 수정
- `verification`/`review` result 생성

### /wf-verify

**목적**
- `/wf-verify`는 verification phase의 실행 책임을 가진 internal skill이다
- repo profile과 plan의 `Verification` section이 요구하는 자동 정리 단계와 필수 검증 게이트를 실행하고, 작업별 추가 verification을 수행한 뒤 structured verification result artifact를 남긴다
- 이 result artifact는 `/wf-next(source=verify)`와 review packet builder의 canonical input이다

**입력**
- `task_root`
- `caller_summary_hint` (optional)
- `candidate_basis_refs` (optional)

입력 원칙:
- optional hint는 탐색 보조일 뿐 source of truth가 아니다
- 최종 판정과 verification summary는 실제 실행 결과, phase 문서, repo profile, plan의 `Verification` section을 다시 읽어 내려야 한다

**Precondition / Guard**
- `state.json.current_phase=verification`이어야 한다
- `state.json.session_state=in_progress`이어야 한다
- `state.json.pending_approval_for=null`이어야 한다
- `state.json.current_step_ref=null`이어야 한다
- `state.json.workspace_baseline_ref`가 있어야 한다
  - 없으면 `reason_code=VERIFY_WORKSPACE_BASELINE_MISSING`으로 차단한다
- `plan.md`가 있어야 한다
- verification phase 첫 진입이든 재수행이든, verification basis를 설명할 최신 result ref가 최소 하나는 있어야 한다
  - 없으면 `reason_code=VERIFY_BASIS_REF_MISSING`으로 차단한다
  - 첫 진입에서는 보통 `latest_checkpoint_ref`
  - 재수행에서는 `latest_verification_ref` 또는 `latest_checkpoint_ref`
- guard에 차단되면 `/wf-verify`는 verification result artifact를 만들지 않는다

**읽는 artifact / 참조**
항상:
- `state.json`
- verification phase 문서
- repo profile의 자동 정리 단계 / 검증 게이트
- `plan.md`의 `Verification` section

조건부:
- `latest_checkpoint_ref`
- `latest_verification_ref`
- caller가 넘긴 `candidate_basis_refs`
- verification 실행 중 생성된 command output / test report / diff ref

실행 환경 원칙:
- shared harness는 테스트, 린트, 빌드, 정적 분석 명령을 고정하지 않는다
- 각 verification command/check는 repo profile 또는 plan이 지정한 working directory와 환경 전제를 따른다
- verification은 repo profile의 자동 정리 단계 후, 필수 검증 게이트를 정의된 순서대로 실행한다
- plan의 `Verification` section에 있는 추가 검증은 필수 게이트 뒤에 실행한다

**verification item 실행 규칙**
- `/wf-verify`는 가능한 한 독립적인 verification item을 끝까지 시도해 근거를 최대한 수집한다
- 다만 선행 실패 때문에 의미 있는 실행이 불가능한 item은 생략하지 않고 `NOT_RUN`으로 기록한다
- 모든 verification item은 최소 다음 필드를 가진다:
  - `item_key`
  - `item_type` (`cleanup | gate | extra`)
  - `label`
  - `method`
  - `result` (`PASS | FAIL | NOT_RUN`)
  - `summary`
  - `basis_refs`
- repo profile의 자동 정리 단계가 workspace를 변경하면, `/wf-verify`는 그 변경을 허용한다
- 이 변경은 `plan.md`/legacy `steps.md`/`state.json` artifact write가 아니라 verification execution의 일부로 본다
- 이후 gate와 review는 cleanup 적용 후의 workspace 상태를 기준으로 판단한다

**평가 규칙**
- verification phase 문서의 `Checkpoint > 확인 항목`, `Checkpoint > 판정`, `판정 기준 메모`를 기준으로 판정을 고른다
- 허용 판정 집합 밖의 `judgement_code`는 선택할 수 없다
- `GO_WITH_NOTE`는 verification을 통과하되 계약상 남겨야 할 caution이 있을 때만 사용한다
- verification의 `note_signals`는 `note_target_hint=plan`만 허용한다
- `REWORK`는 verification만 다시 수행하면 해결되는 경우에만 사용한다
- `REWRITE_STEP`, `REWRITE_PLAN`, `ROLLBACK`, `HOLD`는 verification 결과가 가리키는 remediation 범위에 따라 선택한다
- 후퇴/차단 계열 판정이면 `primary_cause_code`, `reason_fingerprint`를 반드시 채운다
- stop condition은 별도로 평가하며 `judgement_code`를 덮어쓰지 않고 `stop_condition_code`에 기록한다

**출력 / 쓰기 책임**
- verification result shape의 정본은 위 `### /wf-verify result contract`를 따른다
- verification result/log 생성은 shared writer가 담당한다
- shared writer는 verification 종료 시점의 task-scoped diff fingerprint를 계산해 `verified_task_diff_fingerprint`에 기록한다
- `state.json.latest_verification_ref` 갱신은 shared writer가 담당한다
- verification result log가 기록된 뒤 `state.json.latest_verification_ref` 갱신에 실패하면 `reason_code=VERIFY_STATE_UPDATE_FAILED`로 차단한다
- 이 경우 verification log는 persisted 상태이며, `latest_verification_ref`는 갱신되지 않은 상태로 남는다
- shared writer는 `logs/verify-recovery/*.json`에 `record_type=verify_state_update_recovery`, `status=unresolved`, `orphan_result_ref`, `attempted_pointer_field=latest_verification_ref`를 포함한 recovery record를 남긴다
- recovery record write까지 실패하면 runtime은 예외로 종료하지 않고 `recovery_record_persisted=false`, `recovery_ref=null`을 포함한 structured blocked output을 반환한다
- 이후 blocked state mutation으로 `session_state=paused`, `current_phase=verification`, `current_step_ref=null`, `pending_approval_for=null`, `blocked_transition=verify_state_update`, `blocked_reason_ref=<orphan verification ref>`를 반영한다
- blocked state mutation까지 실패하면 runtime은 예외로 종료하지 않고 `blocked_state_persisted=false`를 포함한 structured blocked output을 반환한다. 이때 recovery record와 orphan result log는 persisted 상태일 수 있지만 `state.json` blocked fields는 갱신되지 않았을 수 있다
- 이후 성공적인 `/wf-verify` 재실행은 이전 `blocked_transition=verify_state_update`, `blocked_reason_ref`를 clear한다
- 재개 시 메인 workflow/orchestrator는 unresolved verify recovery record와 orphan verification log를 사용자에게 노출하고, 일반 `/wf-next(source=verify)`로 진행하지 않는다. 수습은 orphan log를 폐기하고 `/wf-verify`를 재실행하거나, 운영자가 orphan ref를 state pointer로 채택한 뒤 recovery record를 resolved 처리하는 방식 중 하나로 명시적으로 수행한다
- `/wf-verify`는 `session_state`, `current_phase`, `pending_approval_for`, `review_outcome`, `closure_authorized`를 직접 수정하지 않는다
- `/wf-verify`는 `plan.md`, legacy `steps.md`, `state.json`, `logs/`를 직접 수정하지 않는다
  - 단, repo profile 자동 정리 단계의 workspace 변경은 verification execution으로 허용된다
- verify blocked output은 `reason_code`와 함께 operator-facing `message_summary`를 포함한다

현재 `/wf-verify` reason code inventory:
- `VERIFY_WORKSPACE_ROOT_MISSING`
- `STATE_ARTIFACT_MISSING`
- `STATE_ARTIFACT_INVALID`
- `VERIFY_GUARD_BLOCKED`
- `VERIFY_PHASE_MISMATCH`
- `VERIFY_SESSION_STATE_INVALID`
- `VERIFY_PENDING_APPROVAL_INVALID`
- `VERIFY_CURRENT_STEP_REF_INVALID`
- `VERIFY_WORKSPACE_BASELINE_MISSING`
- `PLAN_ARTIFACT_MISSING`
- `VERIFY_BASIS_REF_MISSING`
- `VERIFY_PHASE_SPEC_UNAVAILABLE`
- `VERIFY_RESULT_CONTRACT_INVALID`
- `VERIFY_JUDGEMENT_INVALID`
- `VERIFY_NOTE_SIGNALS_INVALID`
- `VERIFY_NOTE_TARGET_INVALID_FOR_PHASE`
- `VERIFY_REASON_REQUIRED`
- `VERIFY_ITEM_INVALID`
- `VERIFY_DIFF_UNAVAILABLE`
- `VERIFY_STATE_UPDATE_FAILED`

**후속 handoff**
- `/wf-next(source=verify)`는 `latest_verification_ref`가 가리키는 verification result를 읽는다
- `/wf-next(source=verify)`가 `next_phase=review`, `next_session_state=in_progress`로 라우팅하면 main workflow/orchestrator가 internal `/wf-review`를 이어서 실행할 수 있다
- `/wf-next(source=verify)`가 `REWORK | REWRITE_* | ROLLBACK | HOLD` 경로로 라우팅하면 메인 workflow가 해당 remediation phase를 수행한다

**하지 않는 것**
- user approval 처리
- next phase / next session state 결정
- review input packet 조립
- review execution
- `required_artifact_actions` 생성
- `plan.md` 또는 legacy `steps.md` 직접 수정

### /wf-review

**목적**
- `/wf-review`는 review phase의 실행 책임을 가진 internal skill이다
- shared packet builder가 factual review input packet을 조립하고, adapter가 독립 reviewer를 실행한 뒤, shared review sink가 structured review result/log를 남긴다
- 이 result artifact는 `/wf-next(source=review)`와 사용자 노출용 review 보고의 canonical input이다

**입력**
- `task_root`
- `caller_summary_hint` (optional)
- `candidate_basis_refs` (optional)

입력 원칙:
- optional hint는 탐색 보조일 뿐 source of truth가 아니다
- `/wf-review`는 메인 workflow의 변호성 설명이나 implementation reasoning을 정본 입력으로 받지 않는다
- 초기 shared contract는 단일 `final-review` profile만 가정하며, profile 선택 입력은 두지 않는다

**Precondition / Guard**
- `state.json.current_phase=review`이어야 한다
- `state.json.session_state=in_progress`이어야 한다
- `state.json.pending_approval_for=null`이어야 한다
- `state.json.current_step_ref=null`이어야 한다
- `state.json.workspace_baseline_ref`가 있어야 한다
  - 없으면 `reason_code=REVIEW_WORKSPACE_BASELINE_MISSING`으로 차단한다
- `plan.md`가 있어야 한다
- review basis를 설명할 `latest_verification_ref`가 있어야 한다
  - 없으면 `reason_code=REVIEW_VERIFICATION_REF_MISSING`으로 차단한다
- current task-scoped diff fingerprint가 `latest_verification_ref.verified_task_diff_fingerprint`와 같아야 한다
  - 다르면 `reason_code=REVIEW_VERIFICATION_STALE`로 차단한다
- guard에 차단되면 `/wf-review`는 review result artifact를 만들지 않는다

**읽는 artifact / 참조**
항상:
- `state.json`
- review phase 문서
- `plan.md`의 `Goal`, `Scope`, `DoD`, `Constraints`, `Risks / Pending`
- `latest_verification_ref`
- 현재 task-scoped raw diff

조건부:
- `latest_checkpoint_ref`
- caller가 넘긴 `candidate_basis_refs`
- `plan.md` inline `Working Notes` section 또는 legacy `steps.md`의 `Working Notes` section
- `latest_verification_ref`가 가리키는 verification item의 `basis_refs`
- review packet builder가 diff 설명에 필요하다고 판단한 changed file excerpt

기본 제외:
- step source 전체
- `state.json` 전체 dump
- 이전 review result 전문
- 메인 workflow의 self-check 상세나 변호성 설명

**review input packet 조립 규칙**
- 입력 packet의 semantic baseline은 review phase 문서와 shared review result contract를 따른다
- shared packet builder는 최소 다음 블록을 조립한다:
  - `contract_summary`: `plan.md`의 `Goal`, `Scope`, `DoD`, `Constraints`
  - `raw_diff`: `workspace_baseline_ref` 기준의 현재 task-scoped factual diff
  - `verification_summary`: `latest_verification_ref`의 판정, 핵심 item 결과, stop condition, note/issue 요약
  - `unresolved_risks_summary`: `plan.md`의 contract-level `Risks / Pending`, inline `Working Notes`에서 아직 carry-forward가 필요한 unresolved item, verification 결과에서 남겨야 할 risk/note를 합성한 요약
- packet builder는 자유 서술형 변호나 “왜 이렇게 구현했는가” 설명을 추가하지 않는다
- file excerpt나 basis ref를 포함하더라도 factual snippet만 허용한다
- 별도 packet snapshot file은 만들지 않는다
- shared review sink가 review log 안에 `Input Packet` section을 만들고 해당 ref를 review log header에 남긴다

**실행 규칙**
- reviewer execution의 semantic contract는 위 `### /wf-review result contract`를 따른다
- reviewer는 read-only 판정 주체이며, review execution은 workspace/artifact 수정 단계로 취급하지 않는다
- rerun review가 필요하면 이전 review result를 재사용하지 않고, 현재 task-scoped diff와 최신 verification 결과로 packet을 다시 조립한다
- adapter가 반환한 reviewer output이 result contract validation에 실패하면 shared review sink는 review result artifact를 기록하지 않는다
- reviewer output validation 실패는 `logs/review-failures/*.json` failure record를 남기고, `state.json.session_state=paused`, `state.json.current_phase=review`, `state.json.current_step_ref=null`, `state.json.pending_approval_for=null`, `state.json.blocked_transition=review_execution`, `state.json.blocked_reason_ref=<failure record ref>`를 반영한다
- review failure record는 최소 `record_type=review_failure`, `status=blocked`, `occurred_at`, `reason_code`, `review_output`을 가진다
- guard, verification freshness, diff 생성 실패는 review result/failure record와 state mutation 없이 blocked output만 반환한다
- 이 blocked path에서는 `latest_review_ref`를 갱신하지 않는다

**평가 규칙**
- review phase 문서의 `Checkpoint > 확인 항목`, `Checkpoint > 판정`, `판정 기준 메모`를 기준으로 판정을 고른다
- 허용 판정 집합 밖의 `judgement_code`는 선택할 수 없다
- `DONE_WITH_NOTE`는 종료 가능하지만 사용자에게 남겨야 할 note/risk가 있을 때만 사용한다
- `DONE_WITH_NOTE`면 `carry_forward_notes`는 비어 있을 수 없다
- `REWORK`, `REWRITE_PLAN`, `HOLD`면 `key_issues`, `primary_cause_code`, `reason_fingerprint`를 채워야 한다
- `out_of_scope_change=yes`면 `DONE`, `DONE_WITH_NOTE`로 닫을 수 없다
- review 결과가 가리키는 remediation 범위가 execution 보완이면 `REWORK`, contract/plan 재정렬이면 `REWRITE_PLAN`, 안전한 판정이 어려우면 `HOLD`를 사용한다

**출력 / 쓰기 책임**
- review result shape의 정본은 위 `### /wf-review result contract`를 따른다
- review result/log 생성은 shared review sink가 담당한다
- shared review sink는 review log의 `Input Packet` section과 review result section을 함께 기록한다
- `state.json.latest_review_ref` 갱신은 shared review sink가 담당한다
- review result log가 기록된 뒤 `state.json.latest_review_ref` 갱신에 실패하면 `reason_code=REVIEW_STATE_UPDATE_FAILED`로 차단한다
- 이 경우 review log는 persisted 상태이며, `latest_review_ref`는 갱신되지 않은 상태로 남는다
- shared review sink는 `logs/review-recovery/*.json`에 `record_type=review_state_update_recovery`, `status=unresolved`, `orphan_result_ref`, `attempted_pointer_field=latest_review_ref`를 포함한 recovery record를 남긴다
- recovery record write까지 실패하면 runtime은 예외로 종료하지 않고 `recovery_record_persisted=false`, `recovery_ref=null`을 포함한 structured blocked output을 반환한다
- 이후 blocked state mutation으로 `session_state=paused`, `current_phase=review`, `current_step_ref=null`, `pending_approval_for=null`, `blocked_transition=review_state_update`, `blocked_reason_ref=<orphan review ref>`를 반영한다
- blocked state mutation까지 실패하면 runtime은 예외로 종료하지 않고 `blocked_state_persisted=false`를 포함한 structured blocked output을 반환한다. 이때 recovery record와 orphan result log는 persisted 상태일 수 있지만 `state.json` blocked fields는 갱신되지 않았을 수 있다
- 이후 성공적인 `/wf-review` 재실행은 이전 `blocked_transition=review_state_update`, `blocked_reason_ref`를 clear한다
- 재개 시 메인 workflow/orchestrator는 unresolved review recovery record와 orphan review log를 사용자에게 노출하고, 일반 `/wf-next(source=review)`로 진행하지 않는다. 수습은 orphan log를 폐기하고 `/wf-review`를 재실행하거나, 운영자가 orphan ref를 state pointer로 채택한 뒤 recovery record를 resolved 처리하는 방식 중 하나로 명시적으로 수행한다
- `/wf-review`는 `session_state`, `current_phase`, `pending_approval_for`, `review_outcome`, `closure_authorized`를 직접 수정하지 않는다
- `/wf-review`는 `plan.md`, legacy `steps.md`, `state.json`, `logs/`를 직접 수정하지 않는다
- reviewer output validation 실패 시 shared state writer는 blocked state mutation을 반영한다
- review blocked output은 `reason_code`와 함께 operator-facing `message_summary`를 포함한다

**후속 handoff**
- `/wf-next(source=review)`는 `latest_review_ref`가 가리키는 review result를 읽는다
- main workflow/orchestrator는 review 결과를 사용자에게 반드시 노출한 뒤 closure approval 여부를 진행한다
- `/wf-next(source=review)`가 `DONE | DONE_WITH_NOTE`를 closure gate로 라우팅하면, 이후 승인 이벤트는 `/wf-next(source=approval)`로 다시 전달된다
- `/wf-next(source=review)`가 `REWORK | REWRITE_PLAN | HOLD`로 라우팅하면 메인 workflow가 해당 remediation phase를 이어서 수행한다
- reviewer output validation 실패로 blocked된 경로에서는 메인 workflow가 `/wf-next(source=review)`를 호출하지 않고 blocked output을 사용자에게 노출한다

현재 `/wf-review` reason code inventory:
- `REVIEW_WORKSPACE_ROOT_MISSING`
- `STATE_ARTIFACT_MISSING`
- `STATE_ARTIFACT_INVALID`
- `REVIEW_GUARD_BLOCKED`
- `REVIEW_PHASE_MISMATCH`
- `REVIEW_SESSION_STATE_INVALID`
- `REVIEW_PENDING_APPROVAL_INVALID`
- `REVIEW_CURRENT_STEP_REF_INVALID`
- `REVIEW_WORKSPACE_BASELINE_MISSING`
- `PLAN_ARTIFACT_MISSING`
- `REVIEW_VERIFICATION_REF_MISSING`
- `REVIEW_VERIFICATION_REF_UNREADABLE`
- `REVIEW_VERIFICATION_STALE`
- `REVIEW_DIFF_UNAVAILABLE`
- `REVIEW_PHASE_SPEC_UNAVAILABLE`
- `REVIEW_RESULT_CONTRACT_INVALID`
- `REVIEW_JUDGEMENT_INVALID`
- `REVIEW_OUT_OF_SCOPE_INVALID`
- `REVIEW_CARRY_FORWARD_NOTES_INVALID`
- `REVIEW_KEY_ISSUES_REQUIRED`
- `REVIEW_REASON_REQUIRED`
- `REVIEW_STATE_UPDATE_FAILED`

**하지 않는 것**
- user approval 처리
- next phase / next session state 결정
- semantic routing 재판단
- verification 재실행
- `required_artifact_actions` 생성
- `plan.md` 또는 legacy `steps.md` 직접 수정

### /wf-next

현재 최소 구현 범위:
- `source=checkpoint`, `source=verify`, `source=review`, `source=approval`을 실행 경로로 지원한다

**호출 시점**
- `/wf-checkpoint`, `/wf-verify`, `/wf-review` 결과 직후
- 필요 시 사용자 승인 이벤트로 state 전이가 발생할 때
- 사용자 승인 이벤트는 main workflow/orchestrator가 수신해 `/wf-next(source=approval)` 호출로 전달한다

**입력**
- `source` (`checkpoint | verify | review | approval`)
- `task_root`
- `latest_result_ref`
  - `checkpoint | verify | review`에서는 필수
  - `approval`에서는 optional
- `judgement_code` (optional, hint only)

판정 코드는 직접 넘길 수 있지만, `/wf-next`는 항상 내부적으로 `resolved_result_ref`를 계산한 뒤 그 artifact를 source of truth로 다시 읽는 것을 기본으로 한다.
`resolved_result_ref` 계산 규칙:
- `source=checkpoint | verify | review`이면 `latest_result_ref`를 그대로 사용한다
- `source=approval`일 때 승인은 새 result artifact를 만들지 않는다. 이 경우 `state.json`의 `pending_approval_for`와 기존 최신 ref를 기준으로 `resolved_result_ref`를 계산한다
- 즉 approval event를 받은 main workflow/orchestrator가 `/wf-next(source=approval)`를 호출하면, `/wf-next`가 승인 후 phase 전이와 후속 internal skill 실행 여부를 라우팅한다
- `pending_approval_for=pre_plan_to_plan | plan_to_implementation`이면 기존 `latest_checkpoint_ref`를 기준으로 한다
- `pending_approval_for=closure`이면 기존 `latest_review_ref`를 기준으로 한다
- approval event는 `state.json.session_state=awaiting_approval` 상태에서만 유효하다
- `pending_approval_for=pre_plan_to_plan`이면 `current_phase=pre-planning`이어야 한다
- `pending_approval_for=plan_to_implementation`이면 `current_phase=step`이어야 한다
- `pending_approval_for=closure`이면 `current_phase=review`이고 `review_outcome=DONE | DONE_WITH_NOTE`이어야 한다
- `/wf-next(source=approval, pending_approval_for=closure)`은 `state.review_outcome`을 canonical closure signal로 사용하며 review artifact의 `judgement_code`를 다시 읽지 않는다
- `source=approval`인데 `pending_approval_for`가 `null`이거나 허용되지 않은 값이면 invalid approval context로 간주한다
- PR1-era `verification_entry`는 공식 approval token이 아니며 state migration에서 제거한다. 제거 직후 stale approval event가 들어오고 state가 이미 `current_phase=verification`, `session_state=in_progress`, `pending_approval_for=null`이면 idempotent하게 verification 상태를 반환할 수 있다
- invalid approval context에서는 `resolved_result_ref = null`로 간주하고, 정상 라우팅을 진행하지 않는다
- 이 경우 `next_phase=current_phase`, `next_session_state=paused`, `pending_approval_for=null`, `required_artifact_actions=[]`, `reason_code=NEXT_APPROVAL_CONTEXT_INVALID`, `routing_basis_ref=state.json`으로 처리한다
- `source=approval`에서 `latest_result_ref`가 전달되면, 계산된 `resolved_result_ref`와 일치해야 한다
- `source=approval`에서 전달된 `latest_result_ref`가 계산된 `resolved_result_ref`와 불일치하면 approval result ref mismatch로 간주한다
- mismatch에서는 정상 라우팅을 진행하지 않고 `next_phase=current_phase`, `next_session_state=paused`, `pending_approval_for`는 기존 값을 유지, `required_artifact_actions=[]`, `reason_code=NEXT_APPROVAL_RESULT_REF_MISMATCH`, `routing_basis_ref=state.json`으로 처리한다
- `judgement_code`는 optimization/hint 용도로만 쓰며, result artifact와 불일치하면 artifact 쪽을 우선한다

정의:
- `resolved_result_ref`는 `/wf-next` 내부에서 읽을 result artifact를 가리키는 작업값이다
- `routing_basis_ref`는 최종 라우팅 판단의 근거가 된 ref를 외부에 노출하는 출력값이다
- `resolved_current_step_ref_snapshot`은 `/wf-next`가 steps-targeted action 생성에 사용할 현재 step 문맥 snapshot 작업값이다
- 정상 경로에서는 `routing_basis_ref = resolved_result_ref`를 기본으로 한다
- 예외 경로에서는 `resolved_result_ref`가 없거나 사용되지 않을 수 있으며, 이 경우 `routing_basis_ref`는 실제 판단 근거(예: `state.json`)를 가리킨다

**읽는 artifact / 참조**
항상:
- `state.json`

`state.json`이 runbook state가 아니거나 읽을 수 없는 shape이면 `/wf-next`는 정상 라우팅을 진행하지 않고 `next_phase=<input current_phase>`, `next_session_state=paused`, `required_artifact_actions=[]`, `reason_code=STATE_ARTIFACT_INVALID`, `routing_basis_ref=state.json`으로 처리한다. 이 경로는 docs-only `state.json`을 runbook v1으로 마이그레이션하거나 재작성하지 않는다.

조건부:
- `resolved_result_ref != null`이면 해당 최신 결과 artifact
- invalid approval context에서는 결과 artifact를 읽지 않고 `state.json`만 기준으로 판단한다
- steps-targeted action 생성이나 current step snapshot 복원이 필요하면 `plan.md` inline `Steps` 또는 legacy `steps.md`

필요 시:
- judgement rules
- stop-conditions
- 현재 phase 완료 기준 문서
- step source의 현재 `(go)` 주변 문맥

**current step snapshot 복원 규칙**
- `/wf-next`는 steps-targeted action을 생성할 때마다 `params.current_step_ref_snapshot`을 채워야 한다
- `source=checkpoint`이고 checkpoint result에 non-null `current_step_ref_snapshot`이 있으면 그것을 그대로 사용한다
- 그 외 source(`verify | review | approval`)이거나 checkpoint result에 usable snapshot이 없으면 `/wf-next`는 `state.json.current_step_ref`와 step source의 canonical parse 결과로 `resolved_current_step_ref_snapshot`을 재구성한다
- 재구성은 `state.json.current_step_ref`가 가리키는 execution step을 step source에서 정확히 1개 resolve하는 방식이어야 한다
- 재구성된 snapshot shape은 checkpoint output의 `current_step_ref_snapshot`과 동일한 contract를 따른다
- 재구성된 snapshot은 최소 `step_ref`, `step_text`, `go_marker_present`를 채워야 한다
- `go_marker_present`는 `/wf-next`가 읽은 base-state step source에서 해당 step의 `(go)` marker 존재 여부와 일치해야 한다
- steps-targeted action이 필요하지 않은 경로에서는 snapshot 복원을 수행하지 않아도 된다
- steps-targeted action이 필요한데 current step snapshot을 step source에서 resolve할 수 없으면 invalid routing context로 간주한다
- 이 경우 정상 라우팅을 진행하지 않고 `next_phase=current_phase`, `next_session_state=paused`, `pending_approval_for`는 기존 값을 유지, `required_artifact_actions=[]`, `reason_code=NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE`, `routing_basis_ref=state.json`으로 처리한다

**라우팅 로직**
최신 결과의 의미를 해석해 다음 항목을 결정한다:
- `next_phase`
- `next_session_state`
- `pending_approval_for`
- `review_outcome` 반영 여부
- `closure_authorized` 초기화/유지 여부
- `required_artifact_actions`
- `routing_basis_ref`

원칙:
- `semantic routing`은 `/wf-next` 책임이다
- 같은 판정 코드라도 `source`에 따라 다르게 해석할 수 있다
- 애매한 경우 `reason_code=HOLD`, `next_session_state=paused`로 해석한다
- `HOLD`는 session state 값이 아니라 routing/review 판단 코드다
- `INVALID_*`, `*_MISMATCH`, `*_UNRESOLVABLE` 계열 `reason_code`는 routing block class로 본다
- routing block class에서는 `next_phase=current_phase`, `next_session_state=paused`, `required_artifact_actions=[]`, `blocked_transition=<attempted transition>`, `blocked_reason_ref=routing_basis_ref`를 함께 남긴다
- `source=checkpoint`인데 `note_target_hint=steps`와 `current_step_ref_snapshot=null` 조합이 나오면 invalid checkpoint output으로 간주한다
- 이 경우 정상 라우팅을 진행하지 않고 `next_phase=current_phase`, `next_session_state=paused`, `pending_approval_for=null`, `required_artifact_actions=[]`, `reason_code=CHECKPOINT_NOTE_TARGET_INVALID_FOR_PHASE`, `routing_basis_ref=resolved_result_ref`로 처리한다
- `source=checkpoint`이고 checkpoint result의 `note_signals`가 비어 있지 않으면 `/wf-next`는 각 note마다 note-targeted action 하나씩을 `required_artifact_actions`에 추가한다
- note-targeted action은 phase routing 때문에 생기는 다른 action과 공존할 수 있다
- 각 note-targeted action의 `basis_ref`는 `resolved_result_ref`를 사용하고, 세부 note 근거는 `params.note_basis_refs`에 담는다
- 각 note의 `note_target_hint=plan`이면 `target=plan`, `action=plan.record_contract_note`를 사용한다
- 각 note의 `note_target_hint=steps`이면 `target=steps`, `action=steps.record_working_note`를 사용한다
- current step 완료가 확정된 경로에서는 `/wf-next`는 `steps.mark_current_step_done -> steps.clear_current_step -> steps.select_next_go_step` 순서의 explicit action sequence를 생성한다
- `/wf-next`는 `/wf-apply`가 기존 `(go)` marker를 implicit하게 제거한다고 가정하지 않는다
- 다음 `(go)` step이 없는 terminal clear path에서는 `/wf-next`가 `steps.select_next_go_step`를 만들지 않고 `steps.mark_current_step_done -> steps.clear_current_step`만 생성한다
- `REWORK`, `REWRITE_*`, `HOLD` 같은 미완료 경로에서는 `steps.mark_current_step_done`를 생성하지 않는다

**정규 라우팅 매트릭스**

- `source=checkpoint`
  - `phase=pre-planning`
    - `GO | GO_WITH_NOTE` -> `next_phase=pre-planning`, `next_session_state=awaiting_approval`, `pending_approval_for=pre_plan_to_plan`
    - `REWRITE_PLAN` -> `next_phase=pre-planning`, `next_session_state=in_progress`, `required_artifact_actions += plan.rewrite_required`
    - `HOLD` -> `next_phase=pre-planning`, `next_session_state=paused`
  - `phase=plan`
    - `GO | GO_WITH_NOTE` -> `next_phase=step`, `next_session_state=in_progress`, `pending_approval_for=null`
    - `REWRITE_PLAN` -> `next_phase=plan`, `next_session_state=in_progress`, `required_artifact_actions += plan.rewrite_required`
    - `HOLD` -> `next_phase=plan`, `next_session_state=paused`
  - `phase=step`
    - `GO | GO_WITH_NOTE` -> `next_phase=step`, `next_session_state=awaiting_approval`, `pending_approval_for=plan_to_implementation`
    - `REWRITE_STEP` -> `next_phase=step`, `next_session_state=in_progress`, `required_artifact_actions += steps.rewrite_required`
    - `REWRITE_PLAN` -> `next_phase=plan`, `next_session_state=in_progress`, `required_artifact_actions += plan.rewrite_required`
    - `HOLD` -> `next_phase=step`, `next_session_state=paused`
  - `phase=implementation`
    - `GO | GO_WITH_NOTE` + remaining pending step exists -> `next_phase=implementation`, `next_session_state=in_progress`, `required_artifact_actions += steps.mark_current_step_done -> steps.clear_current_step -> steps.select_next_go_step`
    - `GO | GO_WITH_NOTE` + no remaining pending step -> `next_phase=verification`, `next_session_state=in_progress`, `pending_approval_for=null`, `required_artifact_actions += steps.mark_current_step_done -> steps.clear_current_step`
    - `REWORK` -> `next_phase=implementation`, `next_session_state=in_progress`, step 유지, step-done action 없음
    - `REWRITE_STEP` -> `next_phase=step`, `next_session_state=in_progress`, `required_artifact_actions += steps.rewrite_required`
    - `REWRITE_PLAN` -> `next_phase=plan`, `next_session_state=in_progress`, `required_artifact_actions += plan.rewrite_required`
    - `ROLLBACK` -> `next_phase=implementation`, `next_session_state=paused`, artifact action 없음
    - `HOLD` -> `next_phase=implementation`, `next_session_state=paused`, artifact action 없음

- `source=verify`
  - `GO | GO_WITH_NOTE` -> `next_phase=review`, `next_session_state=in_progress`, `pending_approval_for=null`
  - `REWORK` -> `next_phase=verification`, `next_session_state=in_progress`, `pending_approval_for=null`, artifact action 없음
  - `REWRITE_STEP` -> `next_phase=step`, `next_session_state=in_progress`, artifact action 없음, `current_step_ref=null`로 step phase를 다시 연다
  - `REWRITE_PLAN` -> `next_phase=plan`, `next_session_state=in_progress`, `required_artifact_actions += plan.rewrite_required`
  - `ROLLBACK` -> `next_phase=verification`, `next_session_state=paused`, artifact action 없음
  - `HOLD` -> `next_phase=verification`, `next_session_state=paused`, artifact action 없음
  - `source=verify`의 `GO_WITH_NOTE` note는 `plan.record_contract_note`로만 변환한다
  - `source=verify / REWORK`는 이미 verification phase 안에서의 재수행이므로 승인 게이트를 다시 요구하지 않는다

- `source=review`
  - `DONE | DONE_WITH_NOTE` -> `next_phase=review`, `next_session_state=awaiting_approval`, `pending_approval_for=closure`, `review_outcome=<same judgement>`, `closure_authorized=false`
  - `REWORK` -> `next_phase=step`, `next_session_state=in_progress`, `review_outcome=REWORK`, artifact action 없음, `current_step_ref=null`로 step phase를 다시 연다
  - `REWRITE_PLAN` -> `next_phase=plan`, `next_session_state=in_progress`, `review_outcome=REWRITE_PLAN`, `required_artifact_actions += plan.rewrite_required`
  - `HOLD` -> `next_phase=review`, `next_session_state=paused`, `review_outcome=HOLD`, artifact action 없음
  - `source=review`에서는 review log가 canonical sink이므로 `DONE_WITH_NOTE`를 추가 artifact action으로 변환하지 않는다

- `source=approval`
  - `pending_approval_for=pre_plan_to_plan` -> `next_phase=plan`, `next_session_state=in_progress`, `pending_approval_for=null`, `approvals_granted += 1`
  - `pending_approval_for=plan_to_implementation` -> `next_phase=implementation`, `next_session_state=in_progress`, `pending_approval_for=null`, `approvals_granted += 2`
  - `pending_approval_for=closure` -> `next_phase=review`, `next_session_state=done`, `pending_approval_for=null`, `closure_authorized=true`, `approvals_granted += 3`

- `source=verify | review`에서 `step` phase로 재개하는 경로는 메인 에이전트가 `plan.md` inline `Steps` semantic rewrite를 직접 수행하는 경로다
- 따라서 이 경로들에서는 `/wf-next`가 synthetic `current_step_ref_snapshot`을 만들거나 `steps.rewrite_required` action을 합성하지 않는다

**하지 않는 것**
- guard precondition 검사
- verification/review 실행
- review input packet 조립
- review log 저장
- `plan.md` 직접 수정
- step source를 직접 읽고 `(go)` marker를 붙이거나 제거하는 실행

`/wf-next`는 다음 `(go)` step의 selection policy를 결정할 수는 있지만, 그 결정을 markdown 수정으로 집행하지는 않는다.

다음 `(go)` step의 실제 marker 반영과 `plan.md` inline step 갱신은 `/wf-apply` 책임이다.

**출력**
최소:
- `next_phase`
- `next_session_state`
- `pending_approval_for`
- `required_artifact_actions`
- `reason_code`
- `routing_basis_ref`
- `deferred_state_transition` (`null | object`)

`routing_basis_ref`는 기본적으로 `resolved_result_ref`와 동일하되, 예외 경로에서는 실제 라우팅 판단 근거를 가리킨다.
`review_outcome`은 별도 top-level 출력 필드가 아니라, 필요 시 `deferred_state_transition.review_outcome`으로 운반되거나 immediate-write 경로에서는 갱신된 `state.json`에만 반영된다.

`deferred_state_transition`은 `/wf-next`가 계산한 state mutation package다.
- 현재 shared Python runtime은 정상 checkpoint routing 경로에서 `required_artifact_actions` 유무와 무관하게 `deferred_state_transition`을 반환한다
- `required_artifact_actions=[]`인 경로에서는 `deferred_state_transition = null`일 수 있다는 기존 semantic은 adapter compatibility 여지로 남기되, shared runtime output은 transition package를 선호한다
- `required_artifact_actions`가 하나라도 있는 경로에서는 `/wf-next`가 직접 state를 쓰지 않고 `deferred_state_transition`을 출력한다
- `deferred_state_transition`은 최소 `session_state`, `current_phase`, `pending_approval_for`, `review_outcome`, `closure_authorized`, `counters`, `approvals_granted`, 필요 시 `blocked_transition`, `blocked_reason_ref`, `stop_condition_ref`를 포함한다
- `deferred_state_transition`에는 `current_step_ref`를 포함하지 않는다

`required_artifact_actions`는 `/wf-apply`가 소비하는 구조화된 action list다.
각 항목은 최소 다음 필드를 가진다:
- `target` (`plan | steps`)
- `action`
- `params`
- `basis_ref`

이 값은 raw diff나 자유 서술이 아니라 symbolic artifact action이어야 한다.

현재 `/wf-next` checkpoint-slice reason code inventory:
- `STATE_ARTIFACT_INVALID`
- `NEXT_SOURCE_UNSUPPORTED`
- `NEXT_RESULT_REF_MISSING`
- `NEXT_RESULT_REF_UNREADABLE`
- `NEXT_RESULT_REF_NOT_LATEST`
- `NEXT_CURRENT_STEP_CONTEXT_UNRESOLVABLE`
- `NEXT_CHECKPOINT_PHASE_UNSUPPORTED`
- `NEXT_VERIFY_JUDGEMENT_UNSUPPORTED`
- `NEXT_REVIEW_JUDGEMENT_UNSUPPORTED`
- `NEXT_APPROVAL_CONTEXT_INVALID`
- `NEXT_APPROVAL_RESULT_REF_MISMATCH`
- `CHECKPOINT_NOTE_TARGET_INVALID_FOR_PHASE`
- `VERIFY_NOTE_TARGET_INVALID_FOR_PHASE`

추가 원칙:
- `target=steps`인 모든 action의 `params`에는 `current_step_ref_snapshot`을 포함한다
- `current_step_ref_snapshot`의 null 허용 여부는 `/wf-apply` action contract를 따른다
- `/wf-next`는 step selection을 하지 않지만, steps-targeted action이 있을 때 `/wf-apply`가 사용할 현재 step 문맥 snapshot은 넘겨야 한다
- `/wf-next`는 steps-targeted action에 synthetic placeholder snapshot을 넣지 않는다
- steps-targeted action의 `current_step_ref_snapshot`은 checkpoint output에서 전달받거나, 위 복원 규칙으로 재구성한 값이어야 한다
- `target=plan` action은 step snapshot을 요구하지 않는다

초기 허용 `action` 집합:
- `target=steps`
  - `steps.mark_current_step_done`
    - `params`: `current_step_ref_snapshot`
  - `steps.clear_current_step`
    - `params`: `current_step_ref_snapshot`
  - `steps.record_working_note`
    - `params`: `current_step_ref_snapshot`, `note_text`, `note_basis_refs`
  - `steps.select_next_go_step`
    - `params`: `current_step_ref_snapshot`, `selection_basis`
    - `selection_basis.mode`: `next_pending_after_current | first_pending | explicit_step_ref`
    - `selection_basis.explicit_step_ref`: `selection_basis.mode=explicit_step_ref`일 때 필수
  - `steps.rewrite_required`
    - `params`: `current_step_ref_snapshot`, `rewrite_reason_code`
- `target=plan`
  - `plan.record_contract_note`
    - `params`: `note_text`, `note_basis_refs`
  - `plan.rewrite_required`
    - `params`: `rewrite_reason_code`

필요 시 사용자에게 짧은 routing summary를 함께 노출한다.

**state 갱신**
직접 파일을 임의 수정하지 않고, shared state writer를 통해 다음 항목만 반영한다:
- `session_state`
- `current_phase`
- `current_step_ref`
- `pending_approval_for`
- `review_outcome` (`null | DONE | DONE_WITH_NOTE | REWORK | REWRITE_PLAN | HOLD`)
- `closure_authorized`
- `counters`
  - `rework_count`
  - `rewrite_count`
  - `rollback_count`
- 필요 시 `blocked_transition`, `blocked_reason_ref`, `stop_condition_ref`

원칙:
- `latest_checkpoint_ref`, `latest_verification_ref`, `latest_review_ref`는 각각 `/wf-checkpoint`, `/wf-verify`, `/wf-review`(또는 대응 sink)가 기록한다
- `/wf-next`는 최신 결과 ref 포인터를 갱신하지 않고 읽기만 한다
- `counters` 갱신은 `/wf-next`의 state transition을 기록하는 shared state writer가 담당한다
- `counters`는 `/wf-next`가 확정하고 shared state writer가 durable하게 반영한 routing outcome을 기준으로 증가한다
- `required_artifact_actions`가 있는 경로에서 `/wf-apply=BLOCKED`면 대응 `deferred_state_transition` 전체를 버리므로 `counters`도 증가하지 않는다
- `judgement_code=REWORK`로 라우팅되면 `counters.rework_count += 1`이다
- rewrite-class routing(`REWRITE_STEP`, `REWRITE_PLAN`, 이후 추가될 `REWRITE_*`)이면 `counters.rewrite_count += 1`이다
- `judgement_code=ROLLBACK`로 라우팅되면 `counters.rollback_count += 1`이다
- `GO`, `GO_WITH_NOTE`, `DONE`, `DONE_WITH_NOTE`, `HOLD`, approval-only transition, invalid context failure는 `counters`를 증가시키지 않는다
- `/wf-next`는 다음 `(go)` step을 직접 선정하지 않는다
- `(go)` marker 이동 결과로 바뀌는 최종 `current_step_ref`는 `/wf-next`가 아니라 `/wf-apply` 출력(`current_step_ref_update_mode`, `resolved_current_step_ref`)을 canonical로 본다
- `required_artifact_actions`가 있는 경로에서는 `/wf-next`가 `current_step_ref` 최종값을 직접 확정하지 않는다
- 다만 deferred 합성에서는 `/wf-apply` 결과만 보지 않고, `deferred_state_transition`의 target phase/session invariant도 함께 적용한다
- `required_artifact_actions`가 있는 경로에서는 `/wf-next`가 `session_state`, `current_phase`, `pending_approval_for`, `review_outcome`, `closure_authorized`, `counters`도 즉시 쓰지 않고 `deferred_state_transition`으로만 넘긴다
- `required_artifact_actions=[]`인 경로에서만 `/wf-next`가 shared state writer를 통해 state를 즉시 반영할 수 있다
- `required_artifact_actions=[]`인 경로에서 `next_phase=step | implementation`이면 기존 `current_step_ref`를 유지할 수 있다
- `required_artifact_actions=[]`인 경로에서 `next_phase=pre-planning | plan | verification | review`이면 `current_step_ref=null`로 clear한다
- `next_session_state=done`이면 `current_step_ref=null`로 clear한다
- 다만 clear 전의 현재 step 문맥은 `required_artifact_actions[*].params.current_step_ref_snapshot`으로 `/wf-apply`에 넘긴다
- 새 step 선정이나 step source 수정은 직접 하지 않고 `required_artifact_actions`로 `/wf-apply`에 넘긴다

### /wf-apply

현재 최소 구현 범위:
- `/wf-next(source=checkpoint)`가 생성하는 초기 허용 action 집합만 지원한다
- semantic rewrite 본문 생성은 하지 않고, rewrite-required marker/note/step marker 조작만 수행한다
- `deferred_state_transition`이 있으면 artifact apply 성공 후 shared state writer로 state를 반영한다

**목적**
- `/wf-apply`는 `/wf-next`가 만든 `required_artifact_actions`를 받아 `plan.md` inline step sections에 적용하는 shared applier다
- semantic routing은 하지 않는다
- 허용 action만 적용한다
- `plan.md`만 직접 수정한다. legacy `steps.md` task는 `plan.md`에 inline `Steps` section이 없을 때 compatibility path로 처리할 수 있다
- `state.json`은 직접 쓰지 않는다
- `logs/` 직접 기록은 `APPLY_COMMIT_PARTIAL` recovery record를 shared apply sink로 남기는 경우만 허용한다
- `/wf-next`가 결정한 selection policy를 실제 `(go)` marker 변경으로 반영하는 것은 `/wf-apply` 책임이다
- semantic rewrite 자체는 `/wf-apply` 책임이 아니다
- `required_artifact_actions=[]`이고 `deferred_state_transition`이 non-null인 lifecycle transition에서는 `/wf-apply` runtime 또는 adapter/orchestrator가 shared state writer를 호출해 transition만 반영할 수 있다

**입력**
- `task_root`
- `required_artifact_actions`
- `routing_basis_ref`
- `deferred_state_transition` (`null | object`)

입력 원칙:
- `required_artifact_actions`의 순서는 authoritative하다
- `/wf-apply`는 action을 재정렬하거나 새 action을 합성하지 않는다
- `/wf-apply`는 `validate -> in-memory apply -> write` 순서로 동작한다

**읽는 artifact / 참조**
- `required_artifact_actions`
- `plan.md` (`target=plan` action이 하나라도 있으면 필수)
- `plan.md` inline `Steps` / `Working Notes` (`target=steps` action이 하나라도 있으면 필수). legacy task에서 inline section이 없으면 `steps.md`를 fallback source로 읽을 수 있다
- `state.json` (`deferred_state_transition`이 있으면 shared state writer handoff에서 필수)

**inline steps parse contract**
- `/wf-next`와 `/wf-apply`는 같은 shared steps parser가 해석한 canonical structure를 소비한다
- canonical execution step은 `Steps` section 안 top-level checklist item만 포함한다
- 들여쓴 nested checklist item은 note/example로 취급하며 execution step으로 파싱하지 않는다
- leading whitespace가 있는 checklist item은 top-level execution step이 아니라 nested checklist로 간주한다
- fenced code block 안의 `## Steps` 또는 checklist item은 canonical execution step으로 파싱하지 않는다
- `Steps` section heading은 top-level `## Steps` 또는 `## 진행 단계 (Steps)` alias다
- `(go)` marker는 no-ref inline step에서는 line 끝의 ` (go)`, legacy `[step_ref=...]` step에서는 `[step_ref=...]` 바로 앞의 ` (go)` sentinel만 의미한다
- step 본문 중간의 literal `(go)` 문자열은 marker로 보지 않는다
- `next_pending_after_current`, `first_pending`는 그 canonical parse 결과의 문서 순서를 따른다

**snapshot validation base state**
- `/wf-apply`의 `current_step_ref_snapshot` matching 기준은 action 적용 전 원본 step source(`plan.md` inline steps 또는 legacy `steps.md`)의 base state다
- snapshot은 base-state execution step의 `step_ref`, `step_text`, `go_marker_present`와 모두 일치해야 한다
- 같은 batch 안의 earlier action이 step source를 바꿔도 snapshot matching 자체는 base state를 기준으로 판단한다
- 반면 action sequence 유효성, `(go)` cardinality, postcondition 검사는 각 action 적용 후의 in-memory state를 기준으로 판단한다
- 따라서 `steps.clear_current_step -> steps.select_next_go_step` sequence에서는 두 action이 같은 base snapshot을 공유할 수 있다

**Guard / Precondition**
- 허용되지 않은 `target` 또는 `action`이 있으면 `reason_code=APPLY_UNSUPPORTED_ACTION`으로 차단한다
- 필요한 target artifact가 없으면 `reason_code=APPLY_TARGET_ARTIFACT_MISSING`으로 차단한다
- `deferred_state_transition`이 있는데 `state.json`이 없으면 `reason_code=STATE_ARTIFACT_MISSING`으로 차단한다
- `deferred_state_transition`이 있는데 `state.json`이 runbook state가 아니거나 읽을 수 없는 shape이면 `reason_code=STATE_ARTIFACT_INVALID`로 차단하며, 파일을 마이그레이션하거나 재작성하지 않는다
- `STATE_ARTIFACT_MISSING` / `STATE_ARTIFACT_INVALID` precondition은 artifact write 전에 평가한다
- legacy `[step_ref=...]` 값이 중복되면 `reason_code=APPLY_STEP_REF_INVALID`로 차단한다. no-ref inline steps는 `step_ref` 누락으로 차단하지 않는다
- step source에 `(go)` marker가 2개 이상이면 `reason_code=APPLY_GO_CARDINALITY_INVALID`로 차단한다
- `steps.record_working_note`, `steps.clear_current_step`, `steps.rewrite_required`는 `current_step_ref_snapshot`이 필수다
- `steps.mark_current_step_done`는 `current_step_ref_snapshot`이 필수다
- `steps.select_next_go_step`는 모든 `selection_basis.mode`에서 `current_step_ref_snapshot`이 필수다
- 위 필수 snapshot이 없으면 `reason_code=APPLY_CURRENT_STEP_REF_SNAPSHOT_REQUIRED`로 차단한다
- steps-targeted action이 가진 `current_step_ref_snapshot`을 base-state step source에 대응시킬 수 없거나 snapshot의 `step_text` / `go_marker_present`가 base state와 다르면 `reason_code=APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH`로 차단한다
- `selection_basis.mode=explicit_step_ref`인데 대상 step을 찾지 못하면 `reason_code=APPLY_SELECTION_TARGET_NOT_FOUND`로 차단한다
- in-memory apply 중 기존 `(go)` marker가 남아 있는 상태에서 `steps.select_next_go_step`가 들어오면 `reason_code=APPLY_GO_SEQUENCE_INVALID`로 차단한다

**실패 정책**
- `/wf-apply`는 pre-write 단계에서 fail-fast를 사용한다
- fail-fast는 validation + in-memory render 단계의 all-or-nothing을 뜻한다
- action 하나라도 guard/precondition에 실패하면 어떤 artifact도 write하지 않는다
- postcondition 검사와 `current_step_ref_update_mode` 계산은 in-memory render 직후, file write 이전에 끝내야 한다
- 모든 action 검증과 in-memory 결과 생성이 끝난 뒤에만 파일을 쓴다
- file write는 temp file + rename으로 각 artifact별 atomic write를 사용한다
- `plan.md`와 legacy `steps.md` 사이의 cross-file atomic commit은 보장하지 않는다. 신규 inline task의 plan + steps-targeted actions는 같은 `plan.md` write로 commit된다
- 일부 artifact만 commit된 뒤 후속 write가 실패하면 `apply_status=BLOCKED`, `reason_code=APPLY_COMMIT_PARTIAL`로 반환한다
- `APPLY_COMMIT_PARTIAL`이면 `updated_artifacts`에는 실제로 commit된 artifact만 기록한다
- `APPLY_COMMIT_PARTIAL`이면 `applied_actions`에는 실제로 commit된 target artifact에 대응하는 action만 기록한다
- `APPLY_COMMIT_PARTIAL`이면 shared state writer는 어떤 state field도 후속 반영하지 않는다
- `/wf-apply`는 partial commit 이후 자동 rollback을 시도하지 않는다
- `APPLY_COMMIT_PARTIAL`이면 shared apply sink가 partial recovery record를 durable하게 남긴다
- 현재 최소 구현에서 partial recovery record ref는 task root 기준 상대 경로(`logs/apply-recovery/*.json`)다

현재 `/wf-apply` reason code inventory:
- `STATE_ARTIFACT_MISSING`
- `STATE_ARTIFACT_INVALID`
- `APPLY_UNSUPPORTED_ACTION`
- `APPLY_TARGET_ARTIFACT_MISSING`
- `APPLY_STEP_REF_INVALID`
- `APPLY_GO_CARDINALITY_INVALID`
- `APPLY_CURRENT_STEP_REF_SNAPSHOT_REQUIRED`
- `APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH`
- `APPLY_SELECTION_TARGET_NOT_FOUND`
- `APPLY_GO_SEQUENCE_INVALID`
- `APPLY_GO_POSTCONDITION_INVALID`
- `APPLY_COMMIT_PARTIAL`

**note / marker dedupe 규칙**
- 중복 note 또는 marker는 failure가 아니라 `noop`으로 처리한다
- `plan.record_contract_note` dedupe key는 `normalized(note_text) + sorted(note_basis_refs)`다
- `steps.record_working_note` dedupe key는 `step_text + normalized(note_text) + sorted(note_basis_refs)`다
- `plan.rewrite_required` dedupe key는 `rewrite_reason_code + basis_ref`다
- `steps.rewrite_required` dedupe key는 `step_text + rewrite_reason_code + basis_ref`다

**action별 적용 규칙**
- `steps.mark_current_step_done`
  - snapshot이 가리키는 현재 execution step의 checklist 상태를 `- [x]`로 변경한다
  - 이 action은 `(go)` marker를 제거하지 않는다
  - 이미 checked 상태면 `noop`으로 처리한다
- `plan.record_contract_note`
  - `plan.md`의 `Contract Notes` section에 note entry를 추가한다
  - `Contract Notes` section이 없으면 `/wf-apply`가 생성한다
- `plan.rewrite_required`
  - `plan.md`의 `Contract Notes` section에 rewrite-required entry를 추가한다
  - 이 action은 plan 본문을 semantic하게 재작성하지 않는다
- `steps.record_working_note`
  - `plan.md`의 `Working Notes` section에 현재 step text 기준 note entry를 추가한다. legacy task에서는 fallback step source의 `Working Notes` section에 기존 `[step_ref=...]` entry shape로 추가한다
  - `Working Notes` section이 없으면 `/wf-apply`가 생성한다
- `steps.clear_current_step`
  - snapshot이 가리키는 현재 `(go)` step에서 `(go)` marker를 제거한다
  - snapshot의 `go_marker_present=false`이고 이미 제거된 상태면 `noop`으로 처리한다
  - snapshot의 `go_marker_present=true`인데 in-memory state에서 이미 제거된 상태면 stale action sequence로 보고 `reason_code=APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH`로 차단한다
- `steps.select_next_go_step`
  - 이 action은 기존 `(go)` marker를 implicit하게 제거하지 않는다
  - current step 완료 후 `(go)` 이동이 필요하면 `steps.mark_current_step_done -> steps.clear_current_step -> steps.select_next_go_step` 순서가 명시적으로 와야 한다
  - `selection_basis.mode=next_pending_after_current`이면 snapshot 뒤의 첫 pending step에 `(go)`를 붙인다
  - `selection_basis.mode=first_pending`이면 문서상 첫 pending step에 `(go)`를 붙인다
  - `selection_basis.mode=explicit_step_ref`이면 지정 step에 `(go)`를 붙인다
  - 선택 대상은 canonical execution step 중 정확히 1개로 resolve되어야 한다
  - 선택 가능한 step이 없으면 `reason_code=APPLY_SELECTION_TARGET_NOT_FOUND`로 차단한다
  - terminal clear path에서는 `/wf-next`가 `steps.select_next_go_step`를 만들지 않고 `steps.clear_current_step`만 넘겨야 한다
  - 대상 step이 이미 유일한 `(go)` step이면 `noop`으로 처리한다
- `steps.rewrite_required`
  - `plan.md`의 `Working Notes` section에 현재 step text 기준 rewrite-required entry를 추가한다. legacy task에서는 fallback step source의 `Working Notes` section에 기존 `[step_ref=...]` entry shape로 추가한다
  - 이 action은 step 본문을 semantic하게 재작성하지 않는다

**rewrite 이후 후속 흐름**
- `plan.rewrite_required` 또는 `steps.rewrite_required`는 semantic rewrite를 대체하지 않는다
- marker apply 이후의 semantic rewrite executor는 별도 `/wf-*` skill이 아니라 메인 에이전트다
- `/wf-next`가 `next_phase=plan`으로 라우팅하고 `plan.rewrite_required`를 생성했으면, 메인 에이전트는 `plan.md` 본문을 직접 재작성한 뒤 `plan` phase의 `/wf-checkpoint`를 다시 수행한다
- `/wf-next`가 `next_phase=step`으로 라우팅하고 `steps.rewrite_required`를 생성했으면, 메인 에이전트는 `plan.md` inline `Steps` 본문을 직접 재작성한 뒤 `step` phase의 `/wf-checkpoint`를 다시 수행한다
- `/wf-next`가 `next_phase=step`으로 라우팅하되 action 없이 들어온 경우(`source=verify | review`의 step 재개), 메인 에이전트는 `plan.md` inline `Steps` 전체를 다시 읽고 필요한 execution step 재구성을 직접 수행한 뒤 `step` phase의 `/wf-checkpoint`를 다시 수행한다
- `REWORK`로 `next_phase=implementation`인 경우에는 같은 current step을 기준으로 메인 에이전트가 구현 변경을 계속 수행한 뒤 `implementation` phase의 `/wf-checkpoint`를 다시 수행한다
- 즉 `/wf-next -> /wf-apply`는 rewrite 필요 상태와 control-plane 위치만 정렬하고, 실제 내용 재작성과 재진입은 메인 에이전트가 담당한다

**post-apply invariant**
- canonical execution step 기준 `(go)` marker는 최종적으로 `0개 또는 1개`만 허용한다
- post-apply 결과 `(go)` marker가 2개 이상이면 `reason_code=APPLY_GO_POSTCONDITION_INVALID`로 차단한다
- `/wf-apply`는 각 action의 local signal이 아니라 최종 rendered step source의 `(go)` marker postcondition으로 `current_step_ref_update_mode`와 `resolved_current_step_ref`를 계산한다

**출력**
- `apply_status` (`APPLIED | NOOP | BLOCKED`)
- `reason_code`
- `applied_actions`
- `noop_actions`
- `updated_artifacts`
- `current_step_ref_update_mode` (`unchanged | set | clear`)
- `resolved_current_step_ref`
- `summary`

출력 원칙:
- `current_step_ref_update_mode=unchanged`이면 `/wf-apply` 자체는 `current_step_ref`를 새로 계산하지 않았다
- `current_step_ref_update_mode=set`이면 post-apply 기준 canonical `(go)` step ref를 `resolved_current_step_ref`에 담는다
- `current_step_ref_update_mode=clear`이면 post-apply 기준 `(go)` step이 없으며 `resolved_current_step_ref=null`이다
- `resolved_current_step_ref`는 `current_step_ref_update_mode=set`일 때만 canonical output이다
- commit 이전 failure면 `apply_status=BLOCKED`, `applied_actions=[]`, `updated_artifacts=[]`다
- 성공했지만 모든 action이 dedupe/noop이면 `apply_status=NOOP`다
- `deferred_state_transition`이 있고 모든 action이 dedupe/noop인 경우에도 `apply_status=NOOP`이며, shared state writer는 `apply_status != BLOCKED` 조건으로 transition을 반영한다
- `APPLY_COMMIT_PARTIAL`이면 `apply_status=BLOCKED`이며 `updated_artifacts`에는 실제 commit된 artifact만 기록한다
- `APPLY_COMMIT_PARTIAL`이면 `applied_actions`에는 실제 commit된 target artifact의 action만 남긴다
- `APPLY_COMMIT_PARTIAL`이면 `current_step_ref_update_mode=unchanged`, `resolved_current_step_ref=null`이다

**쓰기 책임 / handoff**
- `/wf-apply`는 `plan.md`만 직접 수정한다. legacy `steps.md`는 inline section이 없는 기존 task에서만 compatibility fallback으로 수정될 수 있다
- `/wf-apply`는 `state.json`을 직접 수정하지 않는다
- `logs/` 직접 기록은 `APPLY_COMMIT_PARTIAL` recovery record를 shared apply sink로 남기는 경우만 허용한다
- `required_artifact_actions`가 있는 경로에서는 shared state writer가 `apply_status != BLOCKED`일 때만 `/wf-next.deferred_state_transition`과 `/wf-apply` 결과를 합쳐 한 번에 후속 반영한다
- 이 합성 반영에서 `current_step_ref`는 `/wf-apply` 결과와 `/wf-next.deferred_state_transition`의 target phase/session invariant를 함께 사용하고, 나머지 state field는 `/wf-next.deferred_state_transition`을 사용한다
- `apply_status=NOOP`이어도 `deferred_state_transition`이 있으면 shared state writer는 transition을 반영한다
- `required_artifact_actions=[]`이고 `deferred_state_transition`이 non-null이면 `/wf-apply`는 actions를 적용하지 않고 transition만 shared state writer로 반영한다
- `current_step_ref_update_mode=set`이면 `resolved_current_step_ref`로 갱신한다
- `current_step_ref_update_mode=clear`이면 `state.json.current_step_ref=null`로 갱신한다
- `current_step_ref_update_mode=unchanged`이면 `/wf-apply`는 step pointer를 새로 계산하지 않았다는 뜻이다
- `current_step_ref_update_mode=set`은 `deferred_state_transition.current_phase=step | implementation`이고 `deferred_state_transition.session_state != done`일 때만 반영한다
- `deferred_state_transition.current_phase=pre-planning | plan | verification | review`이거나 `deferred_state_transition.session_state=done`이면 `current_step_ref_update_mode=set`이어도 shared state writer가 `current_step_ref=null`로 clear한다
- 그 외에는 기존 `state.json.current_step_ref`를 유지한다
- `apply_status=BLOCKED`이면 `deferred_state_transition`은 폐기하며 어떤 state field도 추가 반영하지 않는다
- `APPLY_COMMIT_PARTIAL`도 `apply_status=BLOCKED`로 간주하므로 deferred state transition을 반영하지 않는다

**하지 않는 것**
- semantic routing 재판단
- `required_artifact_actions` 재생성
- plan/steps 본문 의미 재설계
- `state.json` 직접 기록
- rewrite marker 이후의 semantic rewrite 수행

### /wf-review shared boundary

- reviewer output의 semantic contract는 위 `### /wf-review result contract`를 따른다
- 입력 packet은 공용 packet builder가 생성한다
- reviewer execution만 adapter 책임이다
- review log 기록, `Input Packet` 섹션 생성, `latest_review_ref` 갱신은 공용 review sink가 담당한다

## 실패/차단/재개 처리

- guardrail 실패 시 실행을 차단한다
- 차단 시 최소 state 반영과 blocked reason/ref 기록을 남긴다
- 메인 workflow가 blocked 상태를 읽고 `HOLD` 등으로 해석한다
- 일반 재개 시에는 `state.json`의 현재 `session_state`, `current_phase`, 최신 ref를 기준으로 이어간다

**/wf-start pre-init 예외**
- `/wf-start`의 pre-initialization guard block은 canonical `state.json`이 아직 없을 수 있으므로 일반 blocked-state write 규칙의 예외다
- 이 경우 blocked 정보는 `/wf-start` output에만 담고, task artifact를 새로 만들지 않는다
- `START_TASK_ALREADY_INITIALIZED`면 `/wf-start`를 재시도하지 않고 existing task로 취급해 이후 read-only/status 또는 재개 경로를 사용한다
- `START_TASK_INIT_PARTIAL`이면 메인 workflow/orchestrator가 partial task root를 수습한 뒤에만 `/wf-start`를 다시 시도할 수 있다
- `/wf-start`는 partial init 상태를 자동 repair하거나 기존 artifact를 overwrite하지 않는다

**APPLY_COMMIT_PARTIAL 재개 예외**
- `APPLY_COMMIT_PARTIAL`은 일반 blocked/resume 규칙으로 처리하지 않는다
- 재개 시작 시 메인 workflow는 일반 state 기반 재개 전에 unresolved partial recovery record 존재 여부를 먼저 확인한다
- unresolved partial recovery record가 있으면 `state.json`만 source of truth로 사용하지 않는다
- 이 경우 메인 workflow는 partial recovery record의 `updated_artifacts`, attempted action list, `routing_basis_ref`와 실제 `plan.md`/legacy `steps.md` 내용을 함께 읽어 artifact/state divergence를 수습한다
- 수습 방법은 자동 rollback이 아니라 현재 disk 상태를 기준으로 한 정합성 복원이다
- 수습이 끝나면 해당 task의 현재 intended phase에서 `/wf-checkpoint`를 다시 수행해 state와 artifact를 재동기화한다
- partial recovery record가 unresolved인 동안에는 일반 `/wf-next -> /wf-apply` 루프를 바로 재개하지 않는다
- partial recovery가 완료되면 해당 recovery record를 resolved 처리한다

**VERIFY/REVIEW_STATE_UPDATE_FAILED 재개 예외**
- `VERIFY_STATE_UPDATE_FAILED`와 `REVIEW_STATE_UPDATE_FAILED`는 result log와 `state.json.latest_*_ref` pointer가 갈라진 partial 상태다
- 재개 시작 시 메인 workflow는 `logs/verify-recovery/*.json`, `logs/review-recovery/*.json`의 unresolved record를 일반 최신 pointer보다 먼저 확인한다
- unresolved recovery record가 있으면 orphan result log가 존재하더라도 `/wf-next(source=verify|review)`에 직접 전달하지 않는다
- 수습은 orphan result log를 폐기하고 해당 runtime을 재실행하거나, 운영자가 orphan result ref를 canonical latest pointer로 채택한 뒤 recovery record를 resolved 처리하는 방식 중 하나로 명시적으로 수행한다
- recovery record resolved 처리 시 `status=resolved`, `resolved_at`, `resolution`을 기록한다. resolved 처리는 idempotent update이며, 이미 resolved인 record에 다시 호출하면 latest call의 `resolved_at`, `resolution`으로 갱신한다
- orphan result adoption은 두 단계로 구분한다. `mark_orphan_adoption_recorded`는 recovery record에 `resolution=orphan_result_adopted`, `adopted_result_ref=<orphan result ref>`만 기록하며 `state.json` pointer를 갱신하지 않는다. `adopt_orphan_result_as_latest_ref`는 state pointer 갱신과 recovery record resolution을 함께 수행한다
- 수습이 끝날 때까지 일반 `/wf-next -> /wf-apply` lifecycle을 재개하지 않는다

## Workflow Spine Implementation Units

shared core의 first executable spine은 다음 4개 skill이다.

- `/wf-start`
- `/wf-checkpoint`
- `/wf-next`
- `/wf-apply`

`/wf-verify`, `/wf-review`, adapter wiring은 이 spine 위에 얹는다.

### 공용 foundation

이 4개 skill이 공통으로 기대는 shared foundation은 다음과 같다.

- `shared guard executor`
  - 책임: cross-skill/cross-adapter guard entrypoint 제공, 동일 입력에 대한 동일 `allow|block`, 동일 `reason_code`, 동일 최소 blocked-state mutation 보장
  - 역할: 각 skill의 `*.guard` unit은 독립 규칙 엔진이 아니라 shared guard executor 위의 skill-specific rule bundle이어야 한다
  - guided `/wf-start`처럼 guard가 repo profile을 이미 load한 경로에서는 `GuardDecision.repo_profile`으로 loaded profile을 caller에 handoff할 수 있다
  - 이 handoff는 process-global cache가 아니라 single invocation scoped cache다
- `repo profile loader`
  - 입력: `repo_profile_ref`
  - 책임: profile artifact load, `profile_id/profile_version` 확인, typed read-entry surface 노출
  - 같은 invocation 안에서는 guard가 load한 profile을 downstream runtime/classifier가 재사용해야 한다
  - profile file이 호출 도중 바뀌더라도 해당 invocation은 guard가 검증한 loaded profile을 source로 유지한다
- `phase spec loader`
  - 책임: phase 문서의 checkpoint 항목/허용 판정 집합/판정 메모 read
- `policy/rule loader`
  - 책임: judgement rules, stop-conditions, 현재 phase 완료 기준 문서 load
- `artifact readers`
  - 책임: `plan.md`, legacy `steps.md`, `state.json`, latest result ref parse
- `shared snapshot helper`
  - 책임: task-local baseline capture 요청/opaque baseline ref handoff
- `shared state writer`
  - 책임: `plan.md` Current State와 `state.json` mirror write, immediate/deferred transition 반영, counters 반영
- `shared log writer`
  - 책임: checkpoint/verification/review/apply recovery 계열 log append
- `shared apply sink`
  - 책임: `/wf-apply` partial recovery record emission, apply failure 계열 durable logging
- `shared diff helper`
  - 책임: `workspace_baseline_ref` 기준 task-scoped diff와 stable fingerprint 계산
- `plan writer`
  - 책임: `plan.md` scaffold 생성, contract note append, rewrite marker apply
- `inline steps writer`
  - 책임: `plan.md` inline `Steps`/`Working Notes` step done/clear/select, working note append, rewrite marker apply. legacy `steps.md`는 compatibility fallback

원칙:
- foundation helper는 semantic judgement를 새로 만들지 않는다
- skill은 semantic decision을 내리고, helper/writer는 parse/normalize/persist만 담당한다
- adapter는 이 foundation을 우회하지 않는다

### `/wf-start` implementation unit

구현 단위:
- `start.guard`
  - `user_request`, task root writability, init collision/partial init 검사
  - guided mode에서는 repo profile load와 initialization doc 검증을 수행하고, allow 시 loaded profile을 handoff한다
- `start.mode_resolver`
  - workspace config/convention으로 `workflow_mode`, `repo_profile_ref` resolve
  - 현재 최소 구현은 explicit `repo_profile_ref`가 있으면 guided로 resolve하고, 없으면 `<workspace_root>/contracts/repo_profile.md` convention을 확인한다
  - convention profile이 없으면 `workflow_mode=generic`, `repo_profile_ref=null`, `workflow_mode_resolved=true`로 resolve한다
  - explicit profile ref가 존재하지 않아도 resolver는 guided intent를 유지하고, unreadable profile 차단은 `/wf-start` guard가 `START_REPO_PROFILE_UNAVAILABLE`로 처리한다
- `start.profile_classifier`
  - guided mode면 profile schema로 `task_classification`, `minimum_read_set`, `default_initial_phase_hint` 계산
  - runtime validation은 guard가 handoff한 loaded profile을 우선 사용하고, handoff가 없을 때만 fallback load를 허용한다
- `start.scaffold_writer`
  - `plan.md`, `logs/` 생성
- `start.state_initializer`
  - baseline capture 요청 후 initial `state.json` 기록

직접 의존 foundation:
- `shared guard executor`
- `repo profile loader`
- `plan writer`
- `inline steps writer`
- `shared snapshot helper`
- `shared state writer`

산출물:
- initialized task root
- `minimum_read_set`
- pinned `workflow_mode`, `repo_profile_ref`, `workspace_baseline_ref`

### `/wf-checkpoint` implementation unit

구현 단위:
- `checkpoint.guard`
  - phase mismatch, `current_step_ref` precondition, guided profile availability 검사
- `checkpoint.context_loader`
  - phase spec, plan/steps/state, optional workspace evidence load
- `checkpoint.base_evaluator`
  - phase 문서 checkpoint 항목 순차 평가, base candidate 계산
- `checkpoint.supplement_evaluator`
  - guided mode면 active repo profile의 phase-specific supplement 적용
- `checkpoint.result_writer`
  - structured checkpoint result/log 기록, `latest_checkpoint_ref` 갱신

직접 의존 foundation:
- `shared guard executor`
- `repo profile loader`
- `phase spec loader`
- `policy/rule loader`
- `artifact readers`
- `shared log writer`
- `shared state writer`

산출물:
- canonical checkpoint result artifact
- optional `reason_fingerprint`, `note_signals`, `current_step_ref_snapshot`

### `/wf-next` implementation unit

구현 단위:
- `next.result_resolver`
  - `source`, `latest_result_ref`, approval context 기준 `resolved_result_ref` 계산
- `next.guard`
  - invalid approval context, result ref mismatch, unresolved current step context 검사
- `next.routing_resolver`
  - source + result judgement 기준 `next_phase`, `next_session_state`, approval gate, review outcome 계산
- `next.action_builder`
  - `required_artifact_actions`, step snapshot params, note-targeted action 생성
- `next.state_transition_builder`
  - immediate write 또는 deferred transition payload 조립

직접 의존 foundation:
- `shared guard executor`
- `policy/rule loader`
- `artifact readers`
- `shared state writer`

산출물:
- canonical routing decision
- `required_artifact_actions`
- immediate 또는 deferred state transition contract

### `/wf-apply` implementation unit

구현 단위:
- `apply.action_validator`
  - action target/schema/dedupe 가능 여부 검사
- `apply.plan_executor`
  - `plan.record_contract_note`, `plan.rewrite_required` 적용
- `apply.steps_executor`
  - `steps.mark_current_step_done`, `steps.clear_current_step`, `steps.select_next_go_step`, `steps.record_working_note`, `steps.rewrite_required` 적용
- `apply.post_apply_resolver`
  - post-apply 기준 `current_step_ref_update_mode`, `resolved_current_step_ref` 계산
- `apply.result_emitter`
  - `apply_status`, `updated_artifacts`, partial commit 정보 출력

직접 의존 foundation:
- `shared log writer`
- `shared apply sink`
- `plan writer`
- `inline steps writer`

산출물:
- updated `plan.md` and legacy `steps.md` only when compatibility fallback is used
- apply result contract

### 구현 순서

권장 구현 순서:
1. `shared guard executor`, `repo profile loader`, `phase spec loader`, `policy/rule loader`, `artifact readers`, `shared snapshot helper`, `shared state writer`, `shared log writer`, `shared apply sink`, `shared diff helper`, `plan writer`, `inline steps writer`
2. `/wf-start`
3. `/wf-checkpoint`
4. `/wf-next`
5. `/wf-apply`
6. spine loop 검증
7. `/wf-verify`, `/wf-review`
8. Codex/Claude adapter wiring

spine loop 검증 범위:
- `/wf-start -> /wf-checkpoint -> /wf-next -> /wf-apply`가 state/artifact invariant를 깨지 않는지
- guided mode와 generic mode가 모두 같은 core contract를 따르는지
- deferred transition과 apply 결과 합성이 `current_step_ref`를 stale하게 남기지 않는지
- repo profile supplement가 없는 repo에서도 core가 독립적으로 동작하는지
- `GO_WITH_NOTE` 경로에서 `note_signals -> note-targeted action -> plan/steps write`가 target hint contract를 깨지 않는지

## 기존 문서 처리

아래 문서는 shared harness 도입 이후의 canonical 위치를 따른다.

- docs로 남길 것:
  - `phases/*.md`
  - `templates/project/architecture.md`, `templates/project/code-structure.md`
- shared runtime/contract로 흡수된 대상:
  - 기존 agent policy 문서
- runtime/phase contract로 흡수된 대상:
  - 기존 운영 절차 문서
