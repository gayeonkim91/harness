---
name: test-report
description: Summarize test, lint, build, or static-analysis results either as a standalone report or as verification-assist output for a task's `verification.md`.
---

# test-report

이 skill은 테스트나 검증 게이트를 직접 설계하거나 구현하는 용도가 아니라, 필요하면 검증 명령을 실행하거나 이미 실행된 결과를 읽고 목적에 맞는 형식으로 압축·해석하는 용도로 사용한다.

## 사용 모드

이 skill은 아래 두 모드를 가진다.

### 1. standalone mode
- 테스트가 잘 돌았는지 빠르게 확인하고 사용자에게 요약해서 보여주는 용도다.
- 테스트, 린트, 빌드, 정적 분석 결과와 실패 목록, skip 상태, 대표 실패 원인을 빠르게 정리할 때 쓴다.
- 기본적으로는 먼저 테스트를 실행하거나, 방금 실행한 최신 결과가 있는지 확인한 뒤 그 결과를 요약한다.

### 2. verification assist mode
- 현재 task의 `plan.md` 중 `Verification` 요약과 함께 테스트 결과를 읽고, `verification.md`에 넣을 수 있는 판단 보조 정보를 만드는 용도다.
- 이 모드에서는 단순 요약보다 실패 분류, task 관련성, 판정 영향을 더 중요하게 본다.
- 이 모드는 verification에서 이미 실행한 테스트 결과를 해석하는 쪽에 더 가깝다.

## 언제 이 skill을 사용하는가

다음 상황에서 사용한다.

- 테스트, 린트, 빌드, 정적 분석 실행 결과를 빠르게 요약해서 알려줘야 할 때
- 실패한 테스트 목록, `Skipped` 개수, 대표 실패 원인을 정리해야 할 때
- verification 단계에서 테스트 결과를 `verification.md`에 반영할 수 있는 형태로 압축해야 할 때
- 테스트 report, coverage report, lint report, 빌드 로그 같은 산출물을 근거로 결과를 정리해야 할 때

다음 상황에는 이 skill을 사용하지 않는다.

- 테스트 자체를 새로 작성하거나 수정하는 작업
- 테스트 실행 전 계획만 세우는 경우
- verification 전체 판정을 대신 내려야 하는 경우

## 기본 원칙

- 실행 명령과 작업 디렉터리는 repo profile, plan, 사용자 지시, 또는 직전에 실행한 명령을 따른다.
- 이 skill은 특정 언어, 빌드 도구, 테스트 프레임워크를 기본값으로 가정하지 않는다.
- standalone mode에서는 최신 실행 결과가 없으면 테스트를 먼저 실행하는 쪽을 기본으로 본다.
- verification assist mode에서는 verification phase가 이미 실행한 검증 결과를 해석하는 것을 기본으로 본다.
- verification assist mode에서는 같은 검증 명령을 다시 실행하지 않고, 방금 실행한 결과나 생성된 report 산출물을 우선 읽는다.
- 사용자가 기존 산출물만 정리하라고 명시한 경우에는 실행하지 않고 주어진 결과만 해석할 수 있다.
- 가능하면 긴 콘솔 출력보다 구조화된 report, 종료 상태, 실패 목록, artifact 경로를 우선 근거로 사용한다.
- 테스트가 임시 비활성화된 경우 `Skipped` 개수를 반드시 명시한다.
- 클래스 단위 비활성화와 메서드 단위 비활성화는 구분해서 설명한다.
- 테스트 로그 원문이나 stack trace 전문은 복붙하지 않는다.
- 실패 수 자체보다 실패 성격과 현재 task와의 관련성을 더 중요하게 본다.
- 최종 판정은 이 skill이 하지 않고, verification 전체 맥락에서 판단한다.

## 우선 확인할 입력

필수 입력:

1. 방금 실행한 테스트 명령
2. 테스트 종료 상태
   - 성공
   - 실패
   - 일부 실패 또는 경고 있음
3. 집계 수치
   - `Tests run`
   - `Failures`
   - `Errors`
   - `Skipped`

가능하면 추가로 확인할 입력:

4. 실패 테스트 목록
5. 테스트 report, lint report, coverage report, 빌드 로그 같은 관련 산출물
6. 현재 task의 `plan.md` 중 `Verification` 요약
7. 현재 task 범위 또는 최근 변경 파일

## standalone mode에서 반드시 남겨야 하는 정보 축

- 어떤 테스트를 실행했고 성공/실패했는가
- 집계 수치가 무엇인가
- 실패/스킵의 핵심 묶음이 무엇인가

## verification assist mode에서 반드시 남겨야 하는 정보 축

- 어떤 테스트를 실행했고 성공/실패했는가
- 집계 수치가 무엇인가
- 실패/스킵의 핵심 묶음이 무엇인가
- 현재 task와의 관련성이 무엇인가
- 이 결과가 verification 판정에 어떤 영향을 주는가
- 하네스 verification bridge로 호출된 경우 근거 marker `skill:test-report#verification-assist`를 verification result `basis_refs`에 포함할 수 있게 출력에 명시한다

## standalone mode 출력 형식

항상 아래 순서로 정리한다.

1. 실행한 테스트 또는 확인한 최신 실행 결과
2. 최종 결과
3. 집계 수치
4. 실패 또는 스킵된 테스트 목록
5. 대표 실패 원인
6. 필요하면 재현 명령
7. 필요하면 다음 액션 제안

## verification assist mode 출력 형식

항상 아래 순서로 정리한다.

1. 실행한 테스트
2. 집계
3. 실패 / 스킵 요약
4. 분류
5. task 관련성
6. 판정 영향
7. `verification.md` 반영용 요약
8. 하네스 bridge basis marker (해당 시)

## 실패 분류 기준

가능하면 실패를 아래 중 하나로 분류한다.

- 환경 문제
- 기대값 불일치
- 실제 회귀 가능성
- 미확인

원인을 확신할 수 없으면 `미확인`으로 둔다.

## task 관련성 기준

verification assist mode에서는 가능하면 아래 중 하나로 정리한다.

- 현재 task 범위에 직접 영향 있음
- 간접 영향 가능성 있음
- 현재 task와 직접 관련 없음
- 판단 불가

task 범위를 모르면 관련성 판단을 약하게 하고, 그 사실을 함께 적는다.

## 보고 규칙

- 사용자는 명령 출력 원문을 직접 보지 못한다고 가정하고, 중요한 내용을 답변에 포함한다.
- 장황한 로그 복붙은 하지 않는다.
- 실패 클래스가 많으면 클래스 기준으로 먼저 묶고, 필요할 때만 메서드까지 내린다.
- `Skipped`가 있으면 성공 케이스에서도 반드시 언급한다.
- 테스트를 실행하지 못했으면 그 사실을 분명히 적는다.
- verification assist mode에서는 테스트 결과 자체보다 `판정 영향`과 `verification.md` 반영용 요약의 품질을 우선한다.

## 금지 사항

- 로그 원문 복붙 금지
- stack trace 전문 복붙 금지
- 실패 테스트를 끝없이 나열하는 보고 금지
- task 문맥 없이 무조건 `REWORK`처럼 단정 금지
- verification 전체를 대신하는 최종 결론 금지

## standalone mode 예시

```markdown
실행한 테스트: `cd <workdir> && <test-command>`

최종 결과: 실패
집계: `Tests run: 68, Failures: 19, Errors: 0, Skipped: 0`

실패 테스트:
- `StateArtifactTest`: 7 failures
- `ApplyRuntimeTest`: 3 failures
- `ReviewPacketBuilderTest`: 3 failures

대표 원인:
- 현재 구현과 테스트 기대 artifact shape가 다름
- apply 실패 시 후속 state transition이 반영되지 않음
- packet builder 출력 필드가 테스트 기대값과 다름

재현:
- `cd <workdir> && <test-command>`

다음 액션:
- 실패 테스트를 현재 task 범위 기준으로 다시 묶어서 확인
- 필요하면 테스트 report나 실패 artifact를 열어 대표 실패 원인을 좁힘
```

## verification assist mode 예시

```markdown
실행한 테스트:
- 명령: `cd <workdir> && <test-command>`
- 종료 상태: 실패

집계:
- `Tests run: 68, Failures: 19, Errors: 0, Skipped: 0`

실패 / 스킵 요약:
- `StateArtifactTest`, `ApplyRuntimeTest`, `ReviewPacketBuilderTest`에서 실패 다수

분류:
- `StateArtifactTest`: 기대값 불일치
- `ApplyRuntimeTest`: 실제 회귀 가능성
- `ReviewPacketBuilderTest`: 미확인

task 관련성:
- 현재 task 범위에 직접 영향 있음

판정 영향:
- 현재 테스트 결과만 보면 `REWORK` 쪽 근거가 강함

verification.md 반영용 요약:
- `<test-command>`는 실패했다.
- 주요 실패는 `StateArtifactTest`, `ApplyRuntimeTest`, `ReviewPacketBuilderTest`에 집중됐다.
- 일부는 기대값 불일치로 보이지만, 현재 task 범위에 직접 영향 있는 실제 회귀 가능성도 있다.
```

## 이 skill의 목적

이 skill의 목표는 테스트 결과를 읽기 좋게 정리하는 데서 끝나지 않고, 현재 workflow 안에서 verification 판단에 실제로 도움이 되는 정보로 압축하는 것이다.
