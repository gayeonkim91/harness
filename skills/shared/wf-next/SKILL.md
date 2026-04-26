# /wf-next

## Role
- shared transition skill
- approval event와 latest result를 받아 다음 phase/action을 정렬한다

## Prompt Responsibility
- approval intent나 ambiguous context를 해석한다
- deterministic helper 호출에 필요한 normalized input을 정리한다
- 필요한 경우 helper 출력 요약을 사용자에게 노출한다

## Python Helper Boundary
- routing matrix, `required_artifact_actions`, `deferred_state_transition` 생성은 Python helper가 담당할 수 있다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-next-runtime`

## Notes
- 이 skill은 phase 전환 실행 주체지만, 실제 matrix 적용은 deterministic helper로 위임할 수 있다
