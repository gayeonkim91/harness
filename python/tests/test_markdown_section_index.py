from __future__ import annotations

from harness.shared.core.markdown_section_index import Section, parse_index


def test_parse_index_tracks_nested_section_ranges() -> None:
    result = parse_index(
        "# Plan\n"
        "intro\n"
        "\n"
        "## Goal\n"
        "goal body\n"
        "\n"
        "### Details\n"
        "detail body\n"
        "\n"
        "## Scope\n"
        "scope body\n"
    )

    assert result == [
        Section(title="Plan", level=1, start_line=1, end_line=11),
        Section(title="Goal", level=2, start_line=4, end_line=9),
        Section(title="Details", level=3, start_line=7, end_line=9),
        Section(title="Scope", level=2, start_line=10, end_line=11),
    ]


def test_parse_index_supports_heading_whitespace_and_trailing_hashes() -> None:
    result = parse_index(
        "   ## Current State ##\n"
        "- session_state: in_progress\n"
        "### Approvals ###"
    )

    assert result == [
        Section(title="Current State", level=2, start_line=1, end_line=3),
        Section(title="Approvals", level=3, start_line=3, end_line=3),
    ]


def test_parse_index_keeps_empty_headings_as_section_boundaries() -> None:
    result = parse_index(
        "## A\n"
        "section a\n"
        "##\n"
        "empty section\n"
        "## B\n"
        "section b\n"
    )

    assert result == [
        Section(title="A", level=2, start_line=1, end_line=2),
        Section(title="", level=2, start_line=3, end_line=4),
        Section(title="B", level=2, start_line=5, end_line=6),
    ]


def test_parse_index_ignores_headings_inside_fenced_blocks() -> None:
    result = parse_index(
        "# Plan\n"
        "```md\n"
        "## Fake\n"
        "### Also Fake\n"
        "```\n"
        "## Real\n"
        "~~~yaml\n"
        "### Hidden\n"
        "~~~\n"
        "### Nested\n"
    )

    assert result == [
        Section(title="Plan", level=1, start_line=1, end_line=10),
        Section(title="Real", level=2, start_line=6, end_line=10),
        Section(title="Nested", level=3, start_line=10, end_line=10),
    ]


def test_parse_index_does_not_open_backtick_fence_with_backtick_in_info_string() -> None:
    result = parse_index(
        "# Plan\n"
        "```invalid`info\n"
        "## Still Visible\n"
    )

    assert result == [
        Section(title="Plan", level=1, start_line=1, end_line=3),
        Section(title="Still Visible", level=2, start_line=3, end_line=3),
    ]


def test_parse_index_returns_empty_list_when_no_headings_exist() -> None:
    assert parse_index("plain text\n- bullet\n") == []
