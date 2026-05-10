# /wf-verify

## Role
- shared verification execution skill
- 실행 주체는 agent다
- verification phase의 실제 검증 실행과 verification result 후보 생성을 담당한다

## Prompt Responsibility
- phase 문서, `plan.md`의 Verification 계약, repo profile이 요구하는 검증 게이트를 읽는다
- 변경 path 기준 gate 추천이 필요하면 `core/verification_gate_selector.py`의 `java_spring | frontend | mixed | docs_only` selector를 참고하되, 최종 실행 계약은 최신 `plan.md`의 Verification 섹션으로 확정한다
- 필요한 자동 정리 단계와 검증 게이트를 실행한다
- `spotlessApply`, `pnpm format` 같은 자동 수정 command는 직접 실행하지 않는다. 필요한 경우 사용자/후속 조치로 안내하고, `spotlessCheck`, `pnpm format:check` 같은 check-only command를 사용한다
- Gradle 검증 결과는 `build/test-results`, `build/reports/tests`를 우선 근거로 요약하고, `spotlessCheck` / `checkstyle` 선행 gate 실패는 테스트 실패와 분리한다
- 작업별 추가 verification item을 수행하고 근거를 수집한다
- test/lint/build/static-analysis 결과 요약은 가능하면 `skills/test-report/SKILL.md` verification assist mode를 거친 뒤 basis ref에 `skill:test-report#verification-assist`를 포함한다
- `verification_items`, `judgement_code`, `basis_refs`, `note_signals`, `verified_task_diff_fingerprint` 후보 입력을 구성한다
- deterministic helper에 넘길 구조화된 값을 만든다

## Guard Expectations
- `state.json.current_phase=verification`이어야 한다
- `state.json.session_state=in_progress`이어야 한다
- pending approval과 current step ref가 없어야 한다
- workspace baseline, `plan.md`, verification basis ref가 있어야 한다

## Python Helper Boundary
- Python helper는 verification result validation, log write, latest pointer update, state-update failure recovery를 담당한다
- helper command: `cd python && PYTHONPATH=src python3 -m harness.runtime_cli wf-verify-runtime`

## Notes
- 검증 실행과 판정 근거 수집은 skill 책임이다
- `verification.md`와 verification result에는 긴 콘솔 원문이나 stack trace 전문을 붙이지 않고, 대표 원인과 report/log artifact ref를 남긴다
- 선행 gate 실패 때문에 테스트를 실행하지 못했으면 `verification.md`에 `테스트 미실행`을 명시한다
- persistence, guard, state pointer update semantics는 Python helper와 shared contract를 따른다
- shared contract는 `contracts/shared_implementation.md`를 따른다
