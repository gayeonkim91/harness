# Python Runtime

이 디렉터리는 skill-first harness에서 Python helper/runtime만 담는다.

포함:
- `shared/contracts`
- `shared/core`
- `shared/artifacts`
- `shared/runtime`

포함하지 않음:
- skill prompt 본체
- Claude/Codex adapter wiring

호출 전제:
- source-layout package이므로 helper 호출 시 `python` 기준 `PYTHONPATH=src` 또는 editable install 전제가 필요하다
- 공통 helper 호출 형식은 `python3 -m harness.runtime_cli <helper-name>`로 고정한다
- skill prompt는 Bash 등을 통해 이 runtime helper를 호출한다

현재 helper:
- `wf-start-mode-resolver`
- `wf-start-runtime`
- `wf-docs-only-runtime`
- `wf-checkpoint-runtime`
- `wf-next-runtime`
- `wf-apply-runtime`
- `wf-verify-runtime`
- `wf-review-runtime`

설계 원칙:

- Python은 의미 판단을 하지 않는다
- runtime helper는 artifact 생성, 상태 저장, apply, diff 같은 deterministic 작업만 담당한다
- guided mode든 generic mode든 같은 helper surface를 사용해야 한다
- guided mode의 도입 유형 판정과 필수 문서 세트 판단은 shared contract가 정하고, Python은 그 결과에 따라 scaffold/state write만 수행한다
- `/wf-start` runtime entry는 caller가 넘긴 mode/profile/adoption kind를 그대로 신뢰하지 않고 `start.mode_resolver`를 재실행해 canonical input으로 덮어쓴다
- shared guard direct-call/preflight에서는 `workflow_mode_resolved=true`가 함께 와야 하며, 없으면 mode 입력을 신뢰하지 않고 block 결과를 반환한다
- 새 adapter는 resolver에 명시 profile을 넘길 때 `explicit_repo_profile_ref`를 사용한다. `repo_profile_ref`는 resolver 결과로 state에 pin되는 locator다
- 따라서 generic fallback은 caller가 임의로 `generic`을 넣는 경로가 아니라, resolver가 active guided profile을 찾지 못했을 때만 허용된다
- `wf-start-mode-resolver` helper는 explicit profile ref 또는 `contracts/repo_profile.md` convention으로 guided mode를 resolve하고, 둘 다 없으면 generic mode를 반환한다
- guided `/wf-start`는 guard가 load한 repo profile을 `GuardDecision.repo_profile`으로 runtime validation에 넘긴다. 이 handoff는 process-global cache가 아니라 단일 invocation scoped cache다
- `/wf-start`는 `logs/workspace-baseline.json`을 만들고 그 경로를 `state.json.workspace_baseline_ref`에 기록한다
- `wf-docs-only-runtime`은 runbook `plan.md`/`steps.md`를 만들지 않고, 별도 docs-only `state.json`(`workflow_kind=docs_only`)과 `logs/docs-only/*.json` event log만 기록한다
- PR5(`PlanCurrentState` parser/writer 도입)부터 `/wf-start`와 shared state writer는 같은 상태를 `plan.md`의 `Current State`에도 기록하며, `state.json`과 충돌하면 `plan.md`를 우선한다. `read_state()`는 in-memory reconcile만 수행하고, mirror 파일 갱신은 명시 reconcile helper가 담당한다
- `plan.md`와 `state.json` mirror가 drift되면 `reconcile_state_from_plan()`을 한 번 실행해 mirror를 재생성한다
- baseline artifact는 최소 workspace root, capture 시각, git `HEAD` 가능 여부, `git status --porcelain=v1`, working tree diff, staged diff 결과를 담는다
- `diff_helper`는 baseline artifact 기준으로 task-scoped raw diff와 `sha256:<digest>` fingerprint를 계산한다
- task 시작 전에 이미 있던 tracked/staged dirty diff는 baseline artifact에 기록되며, 이후 task-scoped diff에서 제외된다
- baseline artifact는 plaintext log라 secret-bearing dirty diff가 남을 수 있다. 운영 adapter는 필요하면 `/wf-start` 전에 secret scan 또는 size cap 정책을 적용한다
- working tree / staged diff 변화는 `## working-tree-diff` 또는 `## staged-diff` 아래에 `### baseline`, `### current` subsection으로 표현된다
- git diff 명령 실패는 `## diff-error: <kind>` 블록으로 raw diff와 fingerprint material에 포함된다
- git `HEAD`가 없는 baseline은 status delta 기반으로 처리한다
