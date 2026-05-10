<!--
Plan 작성 메모
- `사전 계획 정리`는 요구사항, 범위, 접근 방식이 아직 불명확할 때만 plan 안에 먼저 작성한다.
- `사전 계획 정리`를 쓰는 동안에는 구현을 시작하지 않고, `진행 단계(Steps)`도 아직 작성하지 않는다.
- Steps는 배경 설명이나 분석 반복이 아니라 실제 작업 순서로 적는다.
- 각 step은 파일, 메서드, 기대 결과처럼 완료 여부를 확인할 수 있게 구체적으로 적는다.
- 각 step은 수행 행동뿐 아니라 완료 후 확인할 수 있는 결과 상태가 드러나게 적는다.
- 첫 번째 step도 하나의 독립 작업 단위로 시작한다.
- step 수행 중 새 이슈가 보여도 현재 step 범위를 임의로 넓히지 않는다.
- 새 이슈는 `리스크 / 보류 사항(Risks / Pending)`에 기록하고, 필요하면 후속 step 또는 별도 plan으로 분리한다.
- `(go)`는 현재 시작할 step 하나에만 붙인다.
- `현재 상태 (Current State)`의 `session_state`는 `draft`, `in_progress`, `awaiting_approval`, `paused`, `done`만 사용한다.
- `current_step`과 `latest_checkpoint`는 사람이 읽는 요약 전용이다. `current_step_ref`는 legacy/runtime mirror이며 step 식별 정본은 `(go)` marker 위치다.
- 신규 step에는 `[step_ref=...]`를 쓰지 않는다.
- `latest_checkpoint`는 `<phase> / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `last_updated`는 YYYY-MM-dd HH:mm:ss KST 형식으로 기록한다.
-->

# Plan: <task-name>

## 현재 상태 (Current State)
- session_state: draft
- current_phase:
- current_step: 해당 없음
- pending_approval_for:
- latest_checkpoint:
- approvals_granted: []
- last_updated:

## 사전 계획 정리 (Pre-planning, 필요한 경우만 작성)
- 문제 정의:
- 확인된 사실:
- 열린 쟁점:
- 후보 접근:
- 선택한 방향:
- plan 입력값 요약:

## 추가 참고 자료 (References)
- <`/wf-start`가 반환한 문서와 섹션>
- <예: templates/project/architecture.md → 전체 구조와 책임, 데이터 흐름>
- <예: templates/project/code-structure.md → 3. 공통 처리 플로우, 4. 외부 연동 경로>
- <예: templates/project/known-issue.md → 문서 정본과 실제 구조 불일치>

## 목표 (Goal)
- <이번 작업의 목표>
- <기능 추가 / 버그 수정 / 동작 보존형 리팩토링 중 무엇인지 명시>

## 배경 / 현재 문제 (Context)
- <현재 확인된 문제나 불편>
- <왜 이 작업이 필요한지>
- <확인된 사실만 적고 추측은 적지 않는다>

## 기대 결과 (Expected Outcome)
- <작업 후 달라져야 하는 상태>
- <반드시 유지되어야 하는 기존 동작>

## 비목표 (Non-Goals)
- <이번 작업에서 하지 않을 것>
- <예: 아키텍처 재설계, public API 변경, DB 스키마 변경, 범위 밖 코드 정리>

## 제약 (Constraints)
- 불필요한 추상화/유틸/프레임워크 도입 금지
- 새 의존성 추가 금지
- 변경은 작은 단위로 나눌 것
- 추측으로 동작을 바꾸지 말 것
- 자동 테스트 작성이 어렵다면 수동 검증 절차를 먼저 정의할 것

## 변경 허용 범위 (Scope)
- <수정 가능한 경로 또는 모듈>
- <필요 시 추가>

## 작업별 완료 조건 (Task-specific DoD)
<!-- 최종 상태만 적는다. "테스트한다", "검증한다", "검증 게이트를 거친다" 같은 검증 행위는 적지 않는다. -->
- [ ] <이번 작업이 끝났다고 볼 수 있는 결과 상태 1>
- [ ] <이번 작업이 끝났다고 볼 수 있는 결과 상태 2>
- [ ] <예: 기존 API 응답 형식과 상태코드가 유지됨>
- [ ] <예: 중복 로직이 지정한 한 곳으로 모임>

## 공통 완료 조건 (Global DoD)
- [ ] 목표 범위 내 변경만 반영됨
- [ ] 작업 유형에 맞는 검증 결과 또는 문서 교차 검토 결과가 확보됨
- [ ] 변경 내용과 남은 리스크가 기록됨

<!--
Verification 작성 메모
- 이 섹션은 실행 로그가 아니라 검증 계약 요약만 적는다.
- 작성 내용은 기본 8줄 이내를 목표로 한다.
- 대표 시나리오는 최대 3개까지만 적는다.
-->
## 검증 계획 (Verification)
- 시스템 동작에 영향을 주는 변경 작업은 repo profile과 이 plan에 정의된 자동 정리 단계와 검증 게이트를 따른다.
- 문서만 수정한 작업은 관련 문서 교차 검토와 상호 참조 확인을 기본 검증으로 삼는다.
- 검증 목표:
- 검증 방식:
- 대표 시나리오:
  - 시나리오 1: <대상 / 방법 / 기대 결과>
  - 시나리오 2: <대상 / 방법 / 기대 결과>
- 실패 해석 기준:
  - <어떤 실패가 어떤 판정으로 이어지는지>

## 리스크 / 보류 사항 (Risks / Pending)
- <이번 작업에서 확인됐지만 지금 처리하지 않는 문제>
- <추가 설계가 필요한 부분>
- <후속 plan으로 넘길 항목>

## 계약 메모 (Contract Notes)

## 진행 단계 (Steps)
<!-- harness:steps-placeholder -->
<!-- 실제 step을 작성할 때 위 placeholder marker를 삭제한다. -->
- [ ] Step 1: <첫 번째 독립 작업 단위>
- [ ] Step 2: <다음 독립 작업 단위>
- [ ] ...

## 작업 노트 (Working Notes)
