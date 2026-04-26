# /wf-review

## Role
- shared review execution skill
- 실행 주체는 agent다
- verification 이후 최종 review 판단과 review result 후보 생성을 담당한다

## Prompt Responsibility
- `plan.md`, task-scoped diff, latest verification result, phase 문서를 읽는다
- findings 우선의 코드리뷰를 수행한다
- out-of-scope change, key issues, verification blind spots, carry-forward notes를 구조화한다
- `judgement_code`, `summary`, `basis_refs`, remediation reason fields를 포함한 review result 후보 입력을 구성한다
- deterministic helper에 넘길 구조화된 값을 만든다

## Guard Expectations
- `state.json.current_phase=review`이어야 한다
- `state.json.session_state=active`이어야 한다
- pending approval과 current step ref가 없어야 한다
- workspace baseline, `plan.md`, latest verification ref가 있어야 한다

## Python Helper Boundary
- Python helper는 review result validation, log write, latest pointer update, state-update failure recovery를 담당한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-review-runtime`

## Notes
- review 판단과 findings 작성은 skill 책임이다
- persistence, guard, state pointer update semantics는 Python helper와 shared contract를 따른다
- shared contract는 `contracts/shared_implementation.md`를 따른다
