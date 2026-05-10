# Codex Adapter Wiring

이 디렉터리는 Codex용 wiring 계층을 둔다.

역할:
- shared `skills/shared/*/SKILL.md`를 Codex surface에 연결
- preflight guard / metadata / invocation transport만 담당
- shared skill 의미를 재정의하지 않음
- 지원해야 하는 shared entrypoint는 `/wf-start`, `/wf-docs-only`, `/wf-checkpoint`, `/wf-next`, `/wf-apply`, `/wf-verify`, `/wf-review`다

원칙:
- 실행 주체는 Codex skill invocation이다
- Python helper는 Codex가 Bash 등으로 호출하는 runtime/helper다
- 기존 task에서는 pinned `workflow_mode`, `repo_profile_ref`, `workspace_baseline_ref`를 따라야 한다
- Codex adapter는 shared contract 위에 Codex-specific UX만 얹고, phase 의미나 artifact shape를 자체 정의하지 않는다
- `/wf-start`에서는 도입 유형 판정 결과와 initialization 필수 문서 세트 검증 결과를 shared guard 입력으로 넘길 수 있어야 한다
- guided mode guard가 실패하면 Codex adapter는 이를 UX로 노출하되, 자체 기준으로 완화하지 않는다
