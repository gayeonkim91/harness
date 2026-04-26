# /wf-apply

## Role
- shared artifact apply skill
- `/wf-next`가 만든 symbolic action을 artifact에 반영한다

## Prompt Responsibility
- 입력 action batch와 적용 맥락을 점검한다
- deterministic helper 실행 결과를 사용자/상위 workflow에 전달한다

## Python Helper Boundary
- action validation, in-memory apply, file write, deferred state handoff는 Python helper가 담당한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-apply-runtime`

## Notes
- semantic rewrite는 이 skill이나 Python helper가 대신하지 않는다
- plan/steps 본문 재작성은 main agent 책임이다
