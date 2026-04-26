# Workflow Harness

범용 agent workflow harness를 만들기 위한 저장소다.
목표는 문서에 흩어진 agent workflow를 실행 가능한 shared workflow surface로 옮기는 것이다.

## Repository Layout

- `contracts/`
  - shared runtime contract와 repo profile schema instance
- `phases/`
  - agent-facing phase specs
- `skills/`
  - shared `/wf-*` skills와 보조 skills
- `python/`
  - deterministic runtime/helper 구현과 테스트
- `templates/`
  - harness를 도입할 대상 프로젝트의 입력 문서와 task artifact 템플릿

## Canonical Sources

- Shared runtime contract: `contracts/shared_implementation.md`
- Repo profile schema instance: `contracts/repo_profile.md`
- Runtime implementation: `python/src/harness`
- Phase specs: `phases/*.md`
- Project input templates: `templates/project/*.md`
- Task artifact templates: `templates/task/*.md`

## Development

1. Contract 변경은 `contracts/shared_implementation.md`에서 시작한다.
2. Runtime 변경은 `python/src/harness`에 구현한다.
3. 테스트는 `python/tests`에 추가한다.
4. Phase별 agent-facing 지침은 `phases/*.md`에만 둔다.

## Test

```bash
cd python
PYTHONPATH=src python3.11 -m pytest
```

## Terminology

- 사용자 승인 지점: 사용자가 승인 여부나 다음 진행 방향을 결정하는 workflow 경계
- checkpoint self-check: 각 phase 종료 시 phase spec을 기준으로 수행하는 공식 self-check 절차
- phase: `pre-planning`, `plan`, `step`, `implementation`, `verification`, `review`
- 현재 상태: `state.json`과 task artifact가 함께 나타내는 workflow 위치
