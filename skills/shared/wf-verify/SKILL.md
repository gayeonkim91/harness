# /wf-verify

## Role
- shared verification execution skill
- 실행 주체는 agent다
- verification phase의 실제 검증 실행과 verification result 후보 생성을 담당한다

## Prompt Responsibility
- phase 문서, `plan.md`의 Verification 계약, repo profile이 요구하는 검증 게이트를 읽는다
- 필요한 자동 정리 단계와 검증 게이트를 실행한다
- 작업별 추가 verification item을 수행하고 근거를 수집한다
- `verification_items`, `judgement_code`, `basis_refs`, `note_signals`, `verified_task_diff_fingerprint` 후보 입력을 구성한다
- deterministic helper에 넘길 구조화된 값을 만든다

## Guard Expectations
- `state.json.current_phase=verification`이어야 한다
- `state.json.session_state=active`이어야 한다
- pending approval과 current step ref가 없어야 한다
- workspace baseline, `plan.md`, verification basis ref가 있어야 한다

## Python Helper Boundary
- Python helper는 verification result validation, log write, latest pointer update, state-update failure recovery를 담당한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-verify-runtime`

## Notes
- 검증 실행과 판정 근거 수집은 skill 책임이다
- persistence, guard, state pointer update semantics는 Python helper와 shared contract를 따른다
- shared contract는 `contracts/shared_implementation.md`를 따른다
