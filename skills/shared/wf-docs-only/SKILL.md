# /wf-docs-only

## Role
- document-only workflow entrypoint
- runbook `plan.md` / `steps.md` / checkpoint flow와 분리된 5단계 문서 변경 흐름을 추적한다

## Prompt Responsibility
- 요청이 `workflow_kind=docs_only`로 확정된 경우에만 사용한다
- 문서 변경 논의, 제안 표시, 제안 수락, diff 표시, 적용 완료 중 현재 event를 하나로 구조화한다
- runbook 승인 문구(`GO`, `GO_WITH_NOTE`, `DONE`, `DONE_WITH_NOTE`)를 docs-only event로 사용하지 않는다

## Python Helper Boundary
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-docs-only-runtime`
- Python helper는 state/log write와 deterministic transition validation만 담당한다

## Events
- `start`: no state -> `discussion`
- `present_proposal`: `discussion` -> `proposal_visualized`
- `accept_proposal`: `proposal_visualized` -> `proposal_accepted`
- `present_diff`: `proposal_accepted` -> `diff_presented`
- `apply`: `diff_presented` -> `applied`

## Notes
- docs-only state는 task root의 `state.json`에 `workflow_kind=docs_only`로 저장된다
- docs-only flow에는 `awaiting_approval` 또는 `pending_approval_for`가 없다
- `accept_proposal`의 `artifact_ref`는 state pointer가 아니라 event log 근거로만 남는다
- start 이후 `adapter_meta`는 기존 state metadata에 merge되고, 같은 key는 최신 입력이 우선한다
