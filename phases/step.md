# Step

```yaml phase-spec
phase_spec:
  phase: step
  checkpoint_items:
    - Steps가 실제 작업 순서로 작성되었는가?
    - 각 step이 배경 설명 반복이 아니라 실행 작업인가?
    - 각 step이 독립적으로 완료 여부를 판단할 수 있는가?
    - 각 step이 너무 크지 않은가?
    - 첫 번째 step도 하나의 독립 작업 단위인가?
    - `(go)`가 현재 시작할 단계 하나에만 붙어 있는가?
  allowed_judgements:
    - GO
    - GO_WITH_NOTE
    - HOLD
    - REWRITE_STEP
    - REWRITE_PLAN
```

## 목적
plan을 실제 실행 가능한 step으로 분해한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 plan 파일
- 확정된 `Goal`, `Scope`, `Task-specific DoD`, `Verification`

## 해야 할 일
- `진행 단계(Steps)`를 실제 작업 순서로 작성한다.
- 각 step을 완료 여부를 독립적으로 판단할 수 있는 실행 단위로 쪼갠다.
- 각 step은 수정/제거/복구/정리/연결 같은 실제 작업으로 쓴다.
- 첫 번째 step도 실제 작업으로 시작한다.
- 현재 시작할 step 하나에만 `(go)`를 붙인다.
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 결과 보고 형식
- `step 요약:`
- `현재 (go) step:`
- `다음 진행 기준:`

## 승인 안내
- `GO`, `GO_WITH_NOTE` 판정이면 결과 보고 뒤에 별도 승인 안내를 제시한다.
- 승인 안내에는 `여기서 사용자 승인 필요`와 이번 승인 판단 기준을 포함한다.
- 판단 기준은 shared `/wf-next(source=approval)` contract와 현재 phase 결과를 따른다.

## 현재 상태 갱신
- `latest_checkpoint`는 `step / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `GO`, `GO_WITH_NOTE`면 승인 요청 전 상태를 나타내기 위해 `session_state: awaiting_approval`, `current_phase: step`, `current_step: 현재 (go) step`으로 갱신한다.
- `REWRITE_STEP`이면 같은 phase를 다시 수행하므로 `session_state: in_progress`, `current_phase: step`, `current_step: 현재 (go) step`으로 유지한다.
- `REWRITE_PLAN`이면 `session_state: in_progress`, `current_phase: plan`, `current_step: 해당 없음`으로 갱신한다.
- `HOLD`면 `session_state: paused`, `current_phase: step`, `current_step: 현재 (go) step`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## 하지 말아야 할 일
- 분석 반복 step을 쓰지 않는다.
- `구조 개선`, `리팩토링`, `정리`처럼 추상 표현만으로 step을 쓰지 않는다.
- 코드를 수정하지 않는다.
- 범위를 넓히기 위해 step 개수를 억지로 늘리지 않는다.

## 산출물
- 실행 가능한 `Steps`
- `(go)`가 붙은 현재 시작 step

## 판정 기준 메모
- step은 TODO 제목이 아니라 실행 단위여야 한다.
- 분석 반복, 구조 개선, 리팩토링 같은 추상 표현만 있으면 통과시키지 않는다.
- plan 자체의 범위나 전제가 흔들리면 REWRITE_STEP이 아니라 REWRITE_PLAN이다.
