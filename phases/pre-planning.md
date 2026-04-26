# Pre-Planning

```yaml phase-spec
phase_spec:
  phase: pre-planning
  checkpoint_items:
    - 해결하려는 문제가 한 문장으로 설명되는가?
    - 이번 작업에서 유지해야 할 기존 동작이 명시되었는가?
    - 이번 작업에서 하지 않을 것(Non-Goals)이 분명한가?
    - 변경 허용 범위(Scope)가 대략적으로라도 정리되었는가?
    - 검증 방법 초안이 있는가?
    - 불확실한 점이 숨겨지지 않고 `확인 필요` 또는 `Risks / Pending`으로 드러나 있는가?
  allowed_judgements:
    - GO
    - GO_WITH_NOTE
    - HOLD
    - REWRITE_PLAN
```

## 목적
구현 전에 문제, 범위, 유지해야 할 동작, 검증 방법 초안을 고정하고, plan 작성에 필요한 입력값을 준비한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 plan 파일
- 새 범위 있는 변경 작업을 시작하는 경우 `/wf-start`가 반환한 minimum read set
- plan에 적힌 추가 참고 문서와 섹션
- 관련 코드와 테스트

## 해야 할 일
- 문서로 관련 컴포넌트와 범위를 먼저 좁힌 뒤, 필요한 코드와 테스트를 읽는다.
- 관련 코드와 문서를 읽고 현재 문제를 한 문장으로 정리한다.
- 이번 작업에서 유지해야 할 기존 동작을 식별한다.
- 이번 작업에서 하지 않을 것(Non-Goals)을 정리한다.
- 변경 허용 범위(Scope)를 대략적으로라도 좁힌다.
- 작업에 필요한 검증 방법의 초안을 정리한다.
- 불확실한 점은 `확인 필요`라고 명시해 plan의 `Risks / Pending`에 기록한다.
- plan 파일의 다음 항목을 채운다.
    - `References`
    - `Goal`
    - `Context`
    - `Expected Outcome`
    - `Non-Goals`
    - `Constraints`
    - `Scope`
    - `Verification` 초안
    - `Risks / Pending`
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 결과 보고 형식
- `문제 정의:`
- `유지해야 할 동작:`
- `비목표 / 범위:`
- `검증 초안:`
- `리스크 / 확인 필요:`

## 승인 안내
- `GO`, `GO_WITH_NOTE` 판정이면 결과 보고 뒤에 별도 승인 안내를 제시한다.
- 승인 안내에는 `여기서 사용자 승인 필요`와 이번 승인 판단 기준을 포함한다.
- 판단 기준은 shared `/wf-next(source=approval)` contract와 현재 phase 결과를 따른다.

## 현재 상태 갱신
- `latest_checkpoint`는 `pre-planning / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `GO`, `GO_WITH_NOTE`면 승인 요청 전 상태를 나타내기 위해 `session_state: awaiting_approval`, `current_phase: pre-planning`, `current_step: 해당 없음`으로 갱신한다.
- `REWRITE_PLAN`이면 같은 phase를 다시 수행하므로 `session_state: in_progress`, `current_phase: pre-planning`, `current_step: 해당 없음`으로 유지한다.
- `HOLD`면 `session_state: paused`, `current_phase: pre-planning`, `current_step: 해당 없음`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## 하지 말아야 할 일
- 코드를 수정하지 않는다.
- `진행 단계(Steps)`를 작성하지 않는다.
- 추측을 사실처럼 적지 않는다.
- 구현 방향을 확정된 결론처럼 쓰지 않는다.

## 산출물
- plan 작성에 필요한 입력 항목이 채워진 plan 파일
- 불확실한 점과 리스크가 드러난 상태

## 판정 기준 메모
- 구현 방향보다 문제 정의와 범위가 더 중요하다.
- 추측으로 빈칸을 메우지 않는다.
- 이 단계에서는 코드를 수정하지 않는다.
