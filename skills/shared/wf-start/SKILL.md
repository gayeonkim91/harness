# /wf-start

## Role
- shared skill-first entrypoint
- 실행 주체는 Python이 아니라 agent다
- 이 skill은 작업 분류와 초기 phase 판단을 수행한다

## Prompt Responsibility
- `workflow_kind`를 `runbook | docs_only | discussion_only | unknown` 중 하나로 분류한다
- `workflow_kind=runbook`일 때만 아래 task classification과 initial phase 판단을 계속한다
- `user_request`와 repo profile을 바탕으로 `task_classification`을 결정한다
- guided mode라면 도입 유형 판정 결과와 필수 문서 세트 충족 여부를 먼저 확인한다
- repo 최초 세팅 시에는 `contracts/repo_profile.md`의 `verification_toolchain`에 실제 build/test/gate 도구가 정해져 있는지 확인한다
- `initial_phase`를 `pre-planning | plan` 중 하나로 결정한다
- `minimum_read_set`과 `phase_doc_ref`를 구성한다
- deterministic helper에 넘길 구조화된 값을 만든다

## Guard Expectations

- guided mode에서 도입 유형을 판정할 수 없으면 `START_PROJECT_CONTEXT_UNRESOLVED` 차단 또는 generic fallback 대상이다
- guided mode에서 도입 유형별 필수 문서 세트가 없거나 최소 작성 기준을 만족하지 않으면 `START_INIT_REQUIRED_DOCS_MISSING` 차단 대상이다
- runbook이 아니거나 workflow kind를 확정하지 못한 요청은 `START_NOT_RUNBOOK` 차단 대상이며, Python helper가 artifact를 만들지 않는다
- broad exploration 전에 위 guard 조건을 먼저 본다

## Python Helper Boundary
- Python helper는 scaffold/state write만 담당한다
- repo profile의 `verification_toolchain.configured=true`이면 helper는 이를 `plan.md` Verification 초기 계약에 우선 반영한다
- 신규 runbook task에서는 `steps.md`를 만들지 않고 `plan.md` 안의 `Steps` / `Working Notes` section을 scaffold한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-start-runtime`

## Notes
- broad codebase exploration 없이 repo profile, 도입 유형, 요청을 우선 사용한다
- shared contract는 `contracts/shared_implementation.md`와 `contracts/repo_profile.md`를 따른다
