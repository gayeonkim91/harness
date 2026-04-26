# Known Issues

이 문서는 하네스가 도입될 대상 프로젝트에서 반복적으로 깨지기 쉬운 지점을 정리하는 known issue 문서다.
`/wf-start`와 repo profile이 사용자 요청의 직접 증상을 이 문서의 섹션과 대조하는 것을 전제로 한다.

## 최소 작성 기준

이 문서는 최소한 아래 조건을 만족해야 한다.

- 증상으로 빠르게 대조할 수 있는 안정적인 섹션 제목이 있다.
- 각 이슈에 직접 관찰 가능한 symptom이 적혀 있다.
- 구조 문서와 연결되는 리스크만 우선 적는다.

도입 유형별 최소 완료 기준:

- machine-read guard 기준은 `contracts/repo_profile.md`의 `project_context.initialization_requirements`가 정본이다.
- 아래 목록은 대상 프로젝트 문서를 작성할 때 따라야 할 사람용 요약이다.

- `greenfield`
  - 필수는 아니다. 반복 증상이 생기면 추가한다.
- `legacy-small`
  - 필수는 아니다. 직접 반복되는 문제만 짧게 적는다.
- `legacy-medium`
  - 선택이지만, 운영 중 반복되는 증상이 있으면 최소 1개 이상 적는 것이 좋다.
- `legacy-large`
  - 필수다. `문서 정본과 실제 구조 불일치`를 포함해 최소 3개의 level-two known issue 섹션이 있어야 한다.
  - 즉 stable entry 1개와 concrete issue 섹션 최소 2개가 필요하다.

## 문서 정본과 실제 구조 불일치

- `architecture.md`, `code-structure.md`, 실제 코드/설정이 서로 다른 구조를 설명하면 guided read set이 잘못된 맥락으로 이어질 수 있다.
- 구조 변경 뒤 문서가 stale하면 `/wf-start`와 repo profile이 잘못된 섹션을 읽게 된다.
- symptom:
  - repo profile이 가리키는 섹션이 실제 문서에 없음
  - code-structure가 실제 시작점과 다른 순서를 안내함
  - architecture의 책임 경계가 실제 구조와 다름

## <예시 known issue 1>

- <반복적으로 나타나는 증상과 깨지기 쉬운 경계>
- symptom:
  - <직접 관찰 가능한 단서 1>
  - <직접 관찰 가능한 단서 2>

## <예시 known issue 2>

- <외부 연동, 데이터 정합성, 동시성, 캐시, 트랜잭션, 배치 등 프로젝트별 이슈>
- symptom:
  - <직접 관찰 가능한 단서 1>
  - <직접 관찰 가능한 단서 2>

## 작성 메모

- 이 문서는 하네스 자체의 알려진 이슈 목록이 아니다.
- 대상 프로젝트에서 반복적으로 나타나는 증상과 리스크를 적는다.
- 각 섹션은 `/wf-start`와 repo profile이 selector로 참조할 수 있게 안정적인 제목을 유지한다.
- 원인 설명보다 symptom과 대조 포인트가 먼저 드러나야 한다.
