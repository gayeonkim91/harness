from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.core.phase_spec_loader import PhaseSpecLoadError, load_phase_spec, resolve_workspace_root


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_phase_spec_parses_plan_checkpoint() -> None:
    spec = load_phase_spec("plan", workspace_root=REPO_ROOT)

    assert spec.phase == "plan"
    assert spec.checkpoint_items == [
        "Goal, Context, Expected Outcome이 서로 모순되지 않는가?",
        "Non-Goals와 Constraints가 범위 확장을 막을 만큼 충분한가?",
        "Scope가 너무 넓지 않고 수정 대상이 현실적인가?",
        "Task-specific DoD가 행동 목록이 아니라 결과 상태로 적혀 있는가?",
        "Verification이 작업에 필요한 검증 계약 요약을 포함하고 있는가?",
        "`Risks / Pending`이 기록되어 있는가?",
    ]
    assert spec.allowed_judgements == ["GO", "GO_WITH_NOTE", "HOLD", "REWRITE_PLAN"]


def test_load_phase_spec_supports_review_done_judgements() -> None:
    spec = load_phase_spec("review", workspace_root=REPO_ROOT)

    assert spec.allowed_judgements == [
        "HOLD",
        "REWORK",
        "REWRITE_PLAN",
        "DONE",
        "DONE_WITH_NOTE",
    ]


def test_load_phase_spec_rejects_unknown_phase(tmp_path: Path) -> None:
    with pytest.raises(PhaseSpecLoadError):
        load_phase_spec("not-a-phase", workspace_root=tmp_path)


def test_load_phase_spec_rejects_missing_checkpoint_sections(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")

    with pytest.raises(PhaseSpecLoadError):
        load_phase_spec("plan", workspace_root=tmp_path)


def test_load_phase_spec_accepts_heading_aliases_and_trailing_hashes(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

## 체크포인트 ##

### Check Items ###
- first item

### Judgments ###
- GO
""",
        encoding="utf-8",
    )

    spec = load_phase_spec("plan", workspace_root=tmp_path)

    assert spec.checkpoint_items == ["first item"]
    assert spec.allowed_judgements == ["GO"]


def test_load_phase_spec_ignores_headings_inside_fenced_blocks(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

```yaml
## Checkpoint
### 확인 항목
- wrong item
### 판정
- HOLD
```

## Checkpoint

### 확인 항목
- real item

### 판정
- GO
""",
        encoding="utf-8",
    )

    spec = load_phase_spec("plan", workspace_root=tmp_path)

    assert spec.checkpoint_items == ["real item"]
    assert spec.allowed_judgements == ["GO"]


def test_load_phase_spec_prefers_embedded_yaml_spec(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

```yaml phase-spec
phase_spec:
  phase: plan
  checkpoint_items:
    - yaml item
  allowed_judgements:
    - GO
    - HOLD
```

## Checkpoint

### 확인 항목
- markdown item

### 판정
- REWRITE_PLAN
""",
        encoding="utf-8",
    )

    spec = load_phase_spec("plan", workspace_root=tmp_path)

    assert spec.checkpoint_items == ["yaml item"]
    assert spec.allowed_judgements == ["GO", "HOLD"]


def test_load_phase_spec_rejects_embedded_yaml_phase_mismatch(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

```yaml phase-spec
phase_spec:
  phase: review
  checkpoint_items:
    - item
  allowed_judgements:
    - GO
```
""",
        encoding="utf-8",
    )

    with pytest.raises(PhaseSpecLoadError):
        load_phase_spec("plan", workspace_root=tmp_path)


def test_load_phase_spec_ignores_non_phase_spec_yaml_blocks(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

```yaml
phase_spec: [not valid
```

## Checkpoint

### 확인 항목
- markdown item

### 판정
- GO
""",
        encoding="utf-8",
    )

    spec = load_phase_spec("plan", workspace_root=tmp_path)

    assert spec.checkpoint_items == ["markdown item"]
    assert spec.allowed_judgements == ["GO"]


def test_load_phase_spec_rejects_unknown_embedded_judgement(tmp_path: Path) -> None:
    phase_dir = tmp_path / "phases"
    phase_dir.mkdir(parents=True)
    (phase_dir / "plan.md").write_text(
        """# Plan

```yaml phase-spec
phase_spec:
  phase: plan
  checkpoint_items:
    - item
  allowed_judgements:
    - MAYBE
```
""",
        encoding="utf-8",
    )

    with pytest.raises(PhaseSpecLoadError):
        load_phase_spec("plan", workspace_root=tmp_path)


def test_resolve_workspace_root_climbs_from_nested_path() -> None:
    nested = REPO_ROOT / "python/tests"

    assert resolve_workspace_root(nested) == REPO_ROOT


def test_resolve_workspace_root_requires_explicit_input() -> None:
    with pytest.raises(PhaseSpecLoadError):
        resolve_workspace_root(None)
