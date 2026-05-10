# Verification

```yaml phase-spec
phase_spec:
  phase: verification
  checkpoint_items:
    - 검증 계획에 정의된 자동 정리 단계와 검증 게이트를 수행했는가?
    - 검증 게이트 실행 결과가 모두 기록되었는가?
    - `plan.md`에 정의한 검증 계약 기준으로 필요한 작업별 검증을 수행했는가?
    - 작업 특성상 필요한 추가 검증(수동 검증, 정적 분석 등)을 수행했는가?
    - 실패 또는 경고가 있다면 원인과 처리 방향이 기록되었는가?
    - 현재 변경이 최소한 품질 게이트는 통과했는가?
  allowed_judgements:
    - GO
    - GO_WITH_NOTE
    - HOLD
    - REWORK
    - REWRITE_STEP
    - ROLLBACK
    - REWRITE_PLAN
```

## 목적
모든 step이 끝난 뒤 plan의 Verification 계약과 repo profile이 요구하는 최종 검증 게이트를 실행하고 결과를 기록한다.

## 적용 조건
- 이 phase는 코드, 설정, 테스트, 빌드/배포 구성, 실행 흐름처럼 시스템 동작에 영향을 주는 변경 작업에 사용한다.
- 문서만 수정한 작업은 관련 문서 교차 검토와 상호 참조 확인으로 마감한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 `plan.md`
- `Verification` 섹션
- 마지막 step까지 완료된 변경 상태

## 해야 할 일
- 같은 task 폴더에 `verification.md`가 없으면 `templates/task/verification.md`를 기준으로 생성한다.
- plan의 `Verification` 계약과 repo profile이 정의한 자동 정리 단계와 검증 게이트를 순서대로 실행한다.
- repo 최초 세팅에서 `verification_toolchain`이 정해졌다면 `/wf-start`가 이를 `plan.md`의 `Verification` 초기 계약에 반영한다. `/wf-verify`는 이 결과로 만들어진 최신 task-local 계약을 따른다.
- shared harness는 테스트, 린트, 빌드, 정적 분석 명령을 고정하지 않는다. 각 검증 게이트의 명령, 작업 디렉터리, 환경 전제는 repo profile 또는 plan이 제공한 값을 따른다.
- 변경 path 기준 gate 추천이 필요하면 PR8 selector(`core/verification_gate_selector.py`)의 `java_spring | frontend | mixed | docs_only` 분류를 사용하되, 최신 `plan.md`의 `Verification` 계약을 우선한다.
- Java/Spring 검증은 가능하면 Gradle report 산출물(`build/test-results`, `build/reports/tests`)을 먼저 읽고, `spotlessCheck` / `checkstyle` 선행 gate 실패는 테스트 실패와 분리해서 기록한다.
- `spotlessCheck` 같은 선행 gate 실패로 테스트를 실행하지 못했으면 `verification.md`에 `테스트 미실행`을 명시한다.
- 검증 결과 정리가 필요한 경우 repo별 보조 skill이나 `skills/test-report/SKILL.md` verification assist mode를 사용한다. 보조 skill은 이미 실행된 검증 결과를 요약하는 용도이며 검증 게이트 자체를 대체하지 않는다.
- 검증 결과 요약은 긴 콘솔 원문 대신 실행 명령, 종료 상태, 집계, 실패 목록, 대표 원인, 근거 artifact 경로를 우선 근거로 삼는다.
- 테스트, 린트, 빌드, 정적 분석 결과를 test-report skill 없이 직접 요약하면 runtime lint warning 대상이다.
- `spotlessApply`, `pnpm format` 같은 자동 수정 command는 `/wf-verify`에서 자동 실행하지 않는다. 필요한 경우 수동 조치로 안내하고, gate는 `spotlessCheck`, `pnpm format:check` 같은 check-only command를 사용한다.
- `plan.md`의 `Verification`에 정의된 검증 계약을 기준으로 작업별 검증을 수행한다.
- 작업 특성상 추가 검증이 필요하면 실행하고, 결과를 정리한다.
    - 수동 검증
    - 정적 분석
    - 특정 API 호출 확인
    - 로그/예외 흐름 확인
- 검증 결과를 `verification.md`와 checkpoint 형식으로 기록한다.
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 현재 상태 갱신
- `latest_checkpoint`는 `verification / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `GO`, `GO_WITH_NOTE`면 `session_state: in_progress`, `current_phase: review`, `current_step: 해당 없음`으로 갱신한다.
- `REWORK`면 verification을 다시 수행하므로 `session_state: in_progress`, `current_phase: verification`, `current_step: 해당 없음`으로 유지한다.
- `REWRITE_STEP`이면 `session_state: in_progress`, `current_phase: step`, `current_step: 현재 (go) step`으로 갱신한다.
- `REWRITE_PLAN`이면 `session_state: in_progress`, `current_phase: plan`, `current_step: 해당 없음`으로 갱신한다.
- `HOLD`, `ROLLBACK`이면 `session_state: paused`, `current_phase: verification`, `current_step: 해당 없음`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## `verification.md` 기록 형식
- `검증 대상:`
- `실행한 검증 게이트:`
- `작업별 검증 시나리오 결과:`
- `실패/경고 항목:`
- `추가 확인 필요 사항:`
- `제안 판정:`
- 검증 게이트는 항목당 1줄 요약으로 적는다.
- 검증 게이트 항목에는 `명령 또는 검사명 / 작업 디렉터리 / 결과 / 근거 artifact / 판정 영향`을 포함한다.
- 필요하면 `실행한 검증 게이트` 아래에 게이트별 요약 소항목을 두고 집계, 실패/스킵 요약, 대표 원인을 함께 적는다.
- 시나리오는 최대 5개까지만 기록한다.
- 시나리오당 `실행 / 결과 / 관찰 / 판정 영향` 4줄 형식을 유지한다.

## 하지 말아야 할 일
- 검증 실패를 숨기지 않는다.
- 실패 상태를 GO처럼 보고하지 않는다.
- 이 단계에서 새 기능이나 새 구조 변경을 추가하지 않는다.
- 테스트, 린트, 빌드, 정적 분석 콘솔 로그 원문을 그대로 `verification.md`에 복붙하지 않는다.
- 콘솔 stack trace 전문을 `verification.md`나 verification result summary에 직접 복붙하지 않는다. 대표 원인과 report/log artifact ref만 남긴다.
- 긴 콘솔 출력만 보고 장문 요약하지 않는다. 가능한 경우 구조화된 report, 종료 상태, 실패 목록, artifact 경로를 근거로 삼는다.
- shared harness 문서에 특정 언어, 빌드 도구, 테스트 프레임워크 명령을 새 기본값으로 추가하지 않는다.

## 산출물
- `verification.md`
- checkpoint 판단용 보고

## 판정 기준 메모
- 검증 게이트 실패 상태에서는 리뷰로 넘기지 않는다.
- 경고를 무시하고 진행할 때는 근거와 리스크를 반드시 남긴다.
- verification만 다시 수행하면 해결되는 경우에만 `REWORK`를 선택한다.
- 현재 step 기준으로 다시 구현해야 하거나 step 구성을 조정해야 하면 `REWRITE_STEP`을 선택한다.
