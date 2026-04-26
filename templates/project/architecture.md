# Architecture

## 시스템 개요

이 문서는 하네스가 도입될 대상 프로젝트의 구조 문서다.
`/wf-start`와 repo profile이 이 문서를 읽고 작업 분류와 최소 읽기 집합을 잡는 것을 전제로 한다.

- 시스템 유형: <대상 프로젝트의 유형>
- 주 진입 방식: <예: HTTP API / worker / CLI / batch / event consumer>
- 핵심 기술 스택: <언어, 프레임워크, 저장소, 메시징, 런타임>
- 목표: 구조와 책임 경계를 빠르게 파악할 수 있게 하는 것

## 최소 작성 기준

이 문서는 최소한 아래 질문에 답할 수 있어야 한다.

- 시스템이 무엇을 하는가
- 어디서 시작되는가
- 공통 처리 순서가 어디에 있는가
- 외부 연동과 저장 경계가 어디에 있는가
- 주요 분기와 예외 경로가 어디에 있는가

도입 유형별 최소 완료 기준:

- machine-read guard 기준은 `contracts/repo_profile.md`의 `project_context.initialization_requirements`가 정본이다.
- 아래 목록은 대상 프로젝트 문서를 작성할 때 따라야 할 사람용 요약이다.

- `greenfield`
  - `시스템 개요`, `전체 구조와 책임`, `데이터 흐름`이 채워져 있어야 한다.
- `legacy-small`
  - `시스템 개요`, `전체 구조와 책임`이 채워져 있어야 한다.
- `legacy-medium`
  - `시스템 개요`, `전체 구조와 책임`, `데이터 흐름`, `외부 의존성`이 채워져 있어야 한다.
- `legacy-large`
  - `시스템 개요`, `디렉터리 구조`, `전체 구조와 책임`, `데이터 흐름`, `외부 의존성`, `주요 분기 / 예외 경로`가 채워져 있어야 한다.

## 디렉터리 구조

```text
<repo-root>/
├── <entrypoints>/
├── <core-domain>/
├── <integration>/
├── <persistence>/
├── <config>/
└── <tests>/
```

이 섹션에는 대상 프로젝트의 실제 최상위 구조와 핵심 경로를 적는다.

## 전체 구조와 책임

```text
┌──────────────────────────────┐
│ Entry Layer                  │
│ - 사용자/이벤트/배치 진입점  │
└───────────────┬──────────────┘
                │
┌───────────────▼──────────────┐
│ Domain / Application Layer   │
│ - 공통 처리 순서             │
│ - 주요 분기                  │
└───────┬───────────────┬──────┘
        │               │
        ▼               ▼
┌──────────────┐  ┌──────────────┐
│ Integration  │  │ Persistence  │
│ / External   │  │ / Cache / DB │
└──────────────┘  └──────────────┘
```

### Entry 레이어

- <대표 진입점 1>
- <대표 진입점 2>

### Domain / Application 레이어

- <공통 처리 순서를 고정하는 위치>
- <전략/분기/정책이 적용되는 위치>

### Integration / External 레이어

- <외부 API, 메시지 큐, 서드파티, 파일 I/O>

### Persistence 레이어

- <DB, 캐시, 저장소, mapper/repository>

## 데이터 흐름

### 입력부터 후속 처리까지

```text
입력
  → 공통 처리
  → 주요 분기
  → 외부 연동 / 저장
  → 후속 처리 / 출력
```

`/wf-start`와 repo profile은 이 섹션을 읽고 end-to-end 영향 범위를 먼저 닫는다.

## 외부 의존성

| 의존성 | 위치 | 용도 |
|---|---|---|
| <dependency> | <entrypoint/module> | <purpose> |
| <dependency> | <entrypoint/module> | <purpose> |

## 주요 분기 / 예외 경로

| 영역 | 핵심 분기 |
|---|---|
| <domain-1> | <branch description> |
| <domain-2> | <branch description> |

## 설정 / 프로파일

| 프로파일 | 주요 차이 |
|---|---|
| <prod> | <dependency / endpoint / infra> |
| <dev> | <dependency / endpoint / infra> |
| <local> | <dependency / endpoint / infra> |

## 디자인 패턴 요약

- <예: Template Method>
- <예: Strategy>
- <예: Factory>

## 작성 메모

- 이 문서는 하네스 자체의 구조 문서가 아니다.
- 대상 프로젝트의 책임 경계와 상위 흐름을 설명한다.
- 구조 변경이 생기면 `templates/project/code-structure.md`, `templates/project/known-issue.md`, repo profile과 함께 갱신한다.
- 섹션 제목은 `/wf-start`와 repo profile selector가 안정적으로 참조할 수 있게 유지한다.
