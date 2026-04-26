# Plan

```yaml phase-spec
phase_spec:
  phase: plan
  checkpoint_items:
    - Goal, Context, Expected Outcome이 서로 모순되지 않는가?
    - Non-Goals와 Constraints가 범위 확장을 막을 만큼 충분한가?
    - Scope가 너무 넓지 않고 수정 대상이 현실적인가?
    - Task-specific DoD가 행동 목록이 아니라 결과 상태로 적혀 있는가?
    - Verification이 작업에 필요한 검증 계약 요약을 포함하고 있는가?
    - `Risks / Pending`이 기록되어 있는가?
  allowed_judgements:
    - GO
    - GO_WITH_NOTE
    - HOLD
    - REWRITE_PLAN
```

## 목적
pre-planning 결과를 바탕으로 작업 전체 설계를 고정한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 plan 파일
- pre-planning 결과가 반영된 항목
- 관련 코드와 테스트

## 해야 할 일
- pre-planning 결과를 바탕으로 plan 본문을 정리한다.
- `Goal`, `Context`, `Expected Outcome`이 서로 모순되지 않게 맞춘다.
- `Non-Goals`, `Constraints`, `Scope`를 분명히 한다.
- `Task-specific DoD`를 행동 목록이 아니라 결과 상태 중심으로 작성한다.
- `Verification`을 실행 로그가 아니라 검증 계약 요약으로 작성한다.
- `Verification`에는 핵심 검증 목표, 검증 방식, 대표 시나리오, 실패 해석 기준이 드러나도록 적는다.
- `Risks / Pending`에 지금 처리하지 않는 문제와 후속 작업 후보를 기록한다.
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 결과 보고 형식
- `설계 요약:`
- `범위 / 비목표:`
- `완료 조건(DoD):`
- `검증 계획:`
- `리스크 / Pending:`

## 현재 상태 갱신
- `latest_checkpoint`는 `plan / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `GO`, `GO_WITH_NOTE`면 `session_state: in_progress`, `current_phase: step`, `current_step: 해당 없음`으로 갱신한다.
- `REWRITE_PLAN`이면 같은 phase를 다시 수행하므로 `session_state: in_progress`, `current_phase: plan`, `current_step: 해당 없음`으로 유지한다.
- `HOLD`면 `session_state: paused`, `current_phase: plan`, `current_step: 해당 없음`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## 하지 말아야 할 일
- `진행 단계(Steps)`를 작성하지 않는다.
- 코드를 수정하지 않는다.
- 아직 확인되지 않은 사실로 범위를 넓히지 않는다.

## 산출물
- 실행 가능한 수준으로 정리된 plan 본문
- 결과 상태 중심의 DoD
- 검증 계획과 리스크가 포함된 작업 설계

## 판정 기준 메모
- plan만 보고도 무엇을, 어디까지, 어떻게 검증할지와 실패를 어떻게 해석할지가 설명되어야 한다.
- 이 단계에서는 step 품질을 평가하지 않는다.
