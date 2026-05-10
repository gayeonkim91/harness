# Claude Adapter Wiring

이 디렉터리는 Claude용 wiring 계층을 둔다.

역할:
- shared `skills/shared/*/SKILL.md`를 Claude surface에 연결
- native hook / metadata / invocation transport만 담당
- shared skill 의미를 재정의하지 않음
- 지원해야 하는 shared entrypoint는 `/wf-start`, `/wf-docs-only`, `/wf-checkpoint`, `/wf-next`, `/wf-apply`, `/wf-verify`, `/wf-review`다

원칙:
- 실행 주체는 Claude skill invocation이다
- Python helper는 Claude가 Bash 등으로 호출하는 runtime/helper다
- reviewer는 main workflow와 분리된 독립 invocation context를 사용해야 한다
- Claude adapter는 shared contract 위에 hook/native transport만 연결하고, phase 의미나 artifact shape를 자체 정의하지 않는다
- `/wf-start`에서는 도입 유형 판정 결과와 initialization 필수 문서 세트 검증 결과를 shared guard 입력으로 넘길 수 있어야 한다
- guided mode guard가 실패하면 Claude adapter는 이를 transport로 노출하되, 자체 기준으로 완화하지 않는다
