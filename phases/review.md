# Review

```yaml phase-spec
phase_spec:
  phase: review
  checkpoint_items:
    - 최종 코드 변경, 관련 diff, 테스트 결과를 다시 읽는 코드리뷰가 실제로 수행되었는가?
    - 발견한 버그, 회귀 위험, 검증 공백이 findings로 기록되었는가? findings가 없다면 그 근거가 기록되었는가?
    - 리뷰 지적 사항이 반영되었거나, 반영하지 않은 이유가 기록되었는가?
    - `Risks / Pending`과 후속 작업이 기록되었는가?
    - 최종 상태를 `DONE` 또는 `DONE_WITH_NOTE`로 닫아도 되는가?
    - 완료 조건(DoD) 충족 여부가 확인되었는가?
    - 추가 보정이 필요하다면 verification, step, plan 중 어느 phase로 되돌아가야 하는지가 분명한가?
  allowed_judgements:
    - HOLD
    - REWORK
    - REWRITE_PLAN
    - DONE
    - DONE_WITH_NOTE
```

## 목적
검증을 통과한 변경을 다시 검토해 plan의 의도, 범위, 품질 측면에서 문제가 없는지 점검한다.
이 phase는 문서 작성 단계가 아니라 코드리뷰 단계다.
리뷰 결과 보고는 항상 findings를 우선으로 정리한다.

## 읽을 것
- `AGENTS.md`
- 현재 작업의 `plan.md`
- 최종 코드 변경
- `verification.md`
- 변경 diff와 관련 테스트 결과

## 해야 할 일
- 같은 task 폴더에 `review.md`가 없으면 `templates/task/review.md`를 기준으로 생성한다.
- 최종 코드 변경, 관련 diff, 테스트 결과를 다시 읽고 버그, 회귀 위험, 검증 공백, 범위 이탈 가능성을 찾는 코드리뷰를 먼저 수행한다.
- `review.md` 작성은 리뷰 수행의 대체가 아니다. 실제로 다시 읽고 판단한 결과만 기록한다.
- 현재 변경이 `Goal`, `Scope`, `Task-specific DoD`와 일치하는지 검토한다.
- 범위 밖 변경이 없는지 확인한다.
- 구현이 과하게 복잡하지 않은지 확인한다.
- 검증만으로 드러나지 않는 리스크나 누락된 점이 없는지 본다.
- 필요하면 작은 범위의 수정만 반영한다.
- review에서 수정이 반영되면 verification을 다시 수행해야 하는지도 함께 판단한다.
- `review.md`에 findings, 반영한 사항, 반영하지 않은 사항과 그 이유를 기록한다.
- findings가 있으면 결과 보고와 `review.md`에서 가장 먼저 제시한다.
- findings는 버그, 동작 리스크, 회귀 가능성, 누락된 검증을 우선순위로 다룬다.
- findings가 없으면 `없음`을 명시하고, 어떤 범위를 다시 확인했고 어떤 리스크를 남겼는지 함께 적는다.
- plan의 `Risks / Pending`에 남은 리스크와 후속 작업을 반영해 최종 갱신한다.
- 반복 실패나 판정 혼선이 있었던 작업, 대표 사례로 남길 가치가 있는 작업, 사용자가 명시적으로 요청한 작업이면 `eval.md` 필요 여부를 함께 판단한다.
- `eval`이 필요하다고 판단되면 최종 승인 요청 전에 같은 task 폴더의 `eval.md` 초안을 작성한다.
- review checkpoint 형식으로 결과를 보고한다.
- checkpoint self-check 후 plan 파일의 `현재 상태 (Current State)`를 갱신한다.

## 현재 상태 갱신
- `latest_checkpoint`는 `review / <판정 코드> — <한줄 근거>` 형식으로 기록한다.
- `DONE`, `DONE_WITH_NOTE`면 plan의 완료 조건(DoD) 체크박스를 갱신한다.
- `DONE`, `DONE_WITH_NOTE`이고 `eval`이 필요 없는 경우 최종 승인 요청 전 상태를 나타내기 위해 `session_state: awaiting_approval`, `current_phase: review`, `current_step: 해당 없음`으로 갱신한다.
- `DONE`, `DONE_WITH_NOTE`이고 `eval`이 필요한 경우 `eval.md` 작성이 끝날 때까지 `session_state: in_progress`, `current_phase: review`, `current_step: 해당 없음`으로 유지한다.
- `REWORK`면 `session_state: in_progress`, `current_phase: step`, `current_step: 해당 없음`으로 갱신한다.
- `REWRITE_PLAN`이면 `session_state: in_progress`, `current_phase: plan`, `current_step: 해당 없음`으로 갱신한다.
- `HOLD`면 `session_state: paused`, `current_phase: review`, `current_step: 해당 없음`으로 갱신한다.
- `last_updated`를 함께 갱신한다.

## `review.md` 기록 형식
- `리뷰 대상:`
- `주요 findings:`
- `반영한 사항:`
- `반영하지 않은 사항과 사유:`
- `남은 리스크 / 후속 작업:`
- `eval 필요 여부:`
- `제안 판정:`
- findings는 최대 5개까지만 적는다.
- finding 하나당 3줄 이내로 유지한다.
- findings는 요약이나 변경 설명보다 먼저 제시한다.
- findings가 없으면 `없음`만 적고 끝내지 말고, 확인 범위와 남은 리스크를 함께 적는다.
- `반영한 사항` 섹션은 항상 두고, 해당 없음이면 `없음`을 명시한다.

## 최종 승인 안내
- `DONE`, `DONE_WITH_NOTE` 판정이면 리뷰 결과 보고 뒤에 별도 승인 안내를 제시한다.
- 승인 안내에는 `여기서 사용자 승인 필요`와 이번 승인 판단 기준을 포함한다.
- 판단 기준은 shared `/wf-next(source=approval)` closure contract와 리뷰 결과를 따른다.

## 하지 말아야 할 일
- `Scope`를 넓히는 새 작업을 추가하지 않는다.
- 대규모 재설계를 여기서 끼워 넣지 않는다.
- 검증 실패를 리뷰로 덮지 않는다.
- `review.md`만 채우고 코드리뷰를 했다고 간주하지 않는다.

## 산출물
- `review.md`
- plan의 `Risks / Pending` 최종 갱신
- plan의 완료 조건(DoD) 체크박스 갱신
- 최종 review 결과 보고

## 판정 기준 메모
- 리뷰는 검증 게이트를 통과한 뒤의 고차원 품질 점검이다.
- 문제가 없으면 DONE 계열로 닫고, 추가 보정이 필요하면 되돌아갈 phase를 판정 코드로 드러낸다.
- 실행 보완이나 step 재구성이 필요하면 `REWORK`로 판정하고, shared routing이 step phase 재개로 정규화한다.
- review에서 반영한 수정이 verification 결과에 영향을 주면 `DONE` 계열로 닫지 않고 `REWORK`로 판정한다.
