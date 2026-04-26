# /wf-checkpoint

## Role
- shared checkpoint skill
- 실행 주체는 agent다
- checkpoint 평가와 note/rewrite 판단은 skill이 수행한다

## Prompt Responsibility
- phase 문서 checkpoint 항목을 평가한다
- 필요 시 repo profile supplement를 함께 본다
- `judgement_code`, `note_signals`, `current_step_ref_snapshot`을 포함한 구조화된 결과를 만든다

## Python Helper Boundary
- Python helper는 checkpoint log/state sink만 담당한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-checkpoint-runtime`

## Notes
- evaluation semantics는 skill이 가진다
- persistence semantics는 Python helper가 가진다
