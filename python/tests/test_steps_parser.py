from __future__ import annotations

from harness.shared.core.steps_parser import parse_steps


def test_steps_parser_treats_go_marker_as_step_ref_sentinel_only() -> None:
    result = parse_steps(
        "# Steps\n\n"
        "## Steps\n\n"
        "- [ ] Explain the (go) marker. [step_ref=S1]\n"
        "- [ ] Implement next. (go) [step_ref=S2]\n"
    )

    assert result.reason_code is None
    assert result.steps[0].text == "Explain the (go) marker."
    assert result.steps[0].go_marker_present is False
    assert result.steps[1].text == "Implement next."
    assert result.steps[1].go_marker_present is True


def test_steps_parser_ignores_fenced_steps_section() -> None:
    result = parse_steps(
        "# Steps\n\n"
        "```markdown\n"
        "## Steps\n"
        "- [ ] Example. (go) [step_ref=EXAMPLE]\n"
        "```\n\n"
        "## Steps\n\n"
        "- [ ] Real step. [step_ref=S1]\n"
    )

    assert result.reason_code is None
    assert [step.step_ref for step in result.steps] == ["S1"]


def test_steps_parser_allows_inline_plan_steps_without_step_ref() -> None:
    result = parse_steps(
        "# Plan\n\n"
        "## 진행 단계 (Steps)\n\n"
        "- [ ] Draft the change. (go)\n"
        "- [ ] Apply the change.\n"
    )

    assert result.reason_code is None
    assert [step.text for step in result.steps] == ["Draft the change.", "Apply the change."]
    assert result.steps[0].step_ref == "step:1"
    assert result.steps[0].go_marker_present is True
    assert result.steps[1].legacy_step_ref is None


def test_steps_parser_ignores_html_comments_in_steps_section() -> None:
    result = parse_steps(
        "# Plan\n\n"
        "## 진행 단계 (Steps)\n"
        "<!-- step은 실제 작업으로 적는다. -->\n"
        "- [ ] Implement one. (go)\n"
    )

    assert result.reason_code is None
    assert len(result.steps) == 1
    assert result.steps[0].text == "Implement one."
