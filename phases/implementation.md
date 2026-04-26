# Implementation

```yaml phase-spec
phase_spec:
  phase: implementation
  checkpoint_items:
    - 이번 step의 목표 변경이 실제로 반영되었는가?
    - 결과 상태를 코드나 실행 흐름으로 확인했는가?
    - 이번 step 범위를 넘는 변경이 섞이지 않았는가?
    - 새로 발견한 이슈가 있다면 `Risks / Pending` 또는 후속 작업으로 기록되었는가?
    - 다음 단계로 넘어갈 준비가 되었는가?
  allowed_judgements:
    - GO
    - GO_WITH_NOTE
    - HOLD
    - REWORK
    - REWRITE_STEP
    - ROLLBACK
```

## 목적
현재 `(go)`가 붙은 step만 구현한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 plan 파일
- 현재 `(go)`가 붙은 step
- 관련 코드와 테스트

## 해야 할 일
- 현재 `(go)` step의 목표에 해당하는 변경만 구현한다.
- plan의 `Scope`, `Constraints`, `Non-Goals`를 넘지 않는다.
- 다음 step의 작업을 미리 하지 않는다.
- 새 이슈를 발견하면 코드로 해결하지 말고 `Risks / Pending` 또는 후속 작업 후보로 기록한다.
- 변경한 코드가 컴파일되는지 확인한다.
- 구현이 끝나면 implementation checkpoint를 위한 완료 보고를 남긴다.
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 현재 상태 갱신
- `latest_checkpoint`는 `implementation / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `GO`, `GO_WITH_NOTE`면 해당 step의 체크박스를 `[x]`로 갱신한다.
- `GO`, `GO_WITH_NOTE`면 shared `/wf-next -> /wf-apply` routing에 따라 `(go)`를 다음 step으로 옮긴 뒤 `현재 상태`를 갱신한다.
- 남은 step이 있으면 `session_state: in_progress`, `current_phase: implementation`, `current_step: 다음 (go) step`으로 갱신한다.
- 남은 step이 없으면 `session_state: in_progress`, `current_phase: verification`, `current_step: 해당 없음`으로 갱신한다.
- `REWORK`면 같은 step을 다시 수행하므로 `session_state: in_progress`, `current_phase: implementation`, `current_step: 현재 (go) step`으로 유지한다.
- `REWRITE_STEP`이면 `session_state: in_progress`, `current_phase: step`, `current_step: 현재 (go) step`으로 갱신한다.
- `HOLD`, `ROLLBACK`이면 `session_state: paused`, `current_phase: implementation`, `current_step: 현재 (go) step`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## Step 완료 보고 형식
- `Step:`
- `목표:`
- `변경 파일:`
- `실제 반영 결과:`
- `범위 밖 변경 여부:`
- `Risks / Pending:`
- `제안 판정:`

## 하지 말아야 할 일
- `(go)`가 아닌 step을 미리 수행하지 않는다.
- 보이는 김에 관련 없는 리팩토링을 같이 하지 않는다.
- 전체 검증 게이트를 여기서 강제하지 않는다.
- checkpoint 없이 다음 step으로 넘어가지 않는다.

## 산출물
- 현재 step에 해당하는 코드 변경
- step 완료 보고

## 판정 기준 메모
- 구현만 됐다고 끝이 아니다. 검증으로 넘길 자격이 있는지를 본다.
- "보이는 김에" 함께 수정한 부분이 있으면 최소 GO_WITH_NOTE로 판정한다.
