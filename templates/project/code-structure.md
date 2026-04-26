# Code Structure (Linear Walkthrough)

이 문서는 하네스가 도입될 대상 프로젝트를 어떤 순서로 읽어야 하는지 안내하는 linear walkthrough 문서다.
`/wf-start`와 repo profile이 구조 파악 기준으로 참조하는 문서 중 하나다.

## 최소 작성 기준

이 문서는 최소한 아래 질문에 답할 수 있어야 한다.

- 처음 어디서 읽기 시작해야 하는가
- 공통 처리 순서는 어떤 파일/모듈을 따라가면 되는가
- 주요 분기는 어디서 갈리는가
- 외부 연동이나 후속 처리는 어디서 확인하는가

도입 유형별 최소 완료 기준:

- machine-read guard 기준은 `contracts/repo_profile.md`의 `project_context.initialization_requirements`가 정본이다.
- 아래 목록은 대상 프로젝트 문서를 작성할 때 따라야 할 사람용 요약이다.

- `greenfield`
  - `1. 시작점`, `3. 공통 처리 플로우`가 채워져 있어야 한다.
- `legacy-small`
  - `1. 시작점`만 먼저 있어도 된다. 나머지는 필요 시 보강한다.
- `legacy-medium`
  - `1. 시작점`, `2. 주요 진입 경로`, `3. 공통 처리 플로우`가 채워져 있어야 한다.
- `legacy-large`
  - `1. 시작점`, `2. 주요 진입 경로`, `3. 공통 처리 플로우`, `4. 외부 연동 경로`, `5. Known Issue 경로`가 채워져 있어야 한다.

## 읽기 원칙

- 개념 설명보다 실제 호출 순서를 따라 읽는다.
- `architecture.md`에서 잡은 책임 경계를 코드 기준으로 따라간다.
- 한 번에 전체를 보지 말고, 시작점 → 공통 처리 → 분기점 → 외부 연동 순으로 내려간다.

## 1. 시작점

### 애플리케이션 / 시스템 부트

- `<main entrypoint>`
- `<boot/config entrypoint>`

여기서 읽을 포인트:

- 시스템이 어디서 시작되는지
- 어떤 설정과 infrastructure가 먼저 올라오는지

## 2. 주요 진입 경로

```text
<entrypoint>
  → <dispatcher/factory/router>
  → <common flow>
  → <domain-specific branch>
```

### 2-1. 입력 수신

- `<대표 진입 클래스/파일>`

여기서 읽을 포인트:

- 어떤 입력이 등록돼 있는지
- 모두 같은 공통 처리 경로로 위임하는지

### 2-2. 분기 선택

- `<factory/router/strategy selector>`

여기서 읽을 포인트:

- 어떤 기준으로 분기가 갈리는지
- 새 분기가 추가되면 어디를 읽어야 하는지

## 3. 공통 처리 플로우

### 3-1. 공통 처리 순서

- `<common flow owner>`

여기서 읽을 포인트:

1. 입력 파싱 / 정규화
2. 사전 검증
3. 데이터 준비
4. 핵심 처리
5. 외부 연동 여부 판단
6. 후속 처리 / 저장

### 3-2. 단계별 읽기 순서

1. `<parse / normalize>`
2. `<validate>`
3. `<prepare>`
4. `<main action>`
5. `<persist / publish / emit>`

## 4. 외부 연동 경로

외부 API, 메시지 큐, DB, 캐시처럼 시스템 바깥 경계를 보려면 아래 순서로 읽는다.

```text
<common flow>
  → <integration service/client>
  → <config / mapper / adapter>
```

여기서 읽을 포인트:

- 외부 연동 진입점
- 성공/실패 판정 위치
- 재시도/후속 처리 경계

## 5. Known Issue 경로

증상 기반으로 빠르게 리스크를 대조할 때는 아래 순서로 읽는다.

```text
사용자 요청의 직접 증상
  → templates/project/known-issue.md 의 해당 섹션
  → 관련 구조 문서
  → 관련 구현/테스트
```

## 6. 주요 경로별 읽기 순서

### 새 프로젝트에 하네스를 도입할 때

```text
1. templates/project/architecture.md
2. templates/project/code-structure.md
3. templates/project/known-issue.md
4. contracts/repo_profile.md
```

### /wf-start read map을 조정할 때

```text
1. contracts/repo_profile.md
2. templates/project/known-issue.md
```

### 실제 구현을 읽을 때

```text
1. templates/project/architecture.md
2. templates/project/code-structure.md
3. 관련 구현
4. 관련 테스트
```

## 7. 추가 읽기 순서

### 구조 파악 deep dive

1. `templates/project/architecture.md`
2. `templates/project/code-structure.md`
3. 관련 구현/설정

### Guided onboarding deep dive

1. `contracts/repo_profile.md`
2. `templates/project/known-issue.md`

## 작성 메모

- 이 문서는 설계 설명보다 실제 읽기 순서가 중요하다.
- 섹션 제목과 번호는 `/wf-start`와 repo profile이 안정적으로 참조할 수 있게 유지한다.
- 구조가 크게 바뀌면 `architecture.md`와 함께 갱신한다.
