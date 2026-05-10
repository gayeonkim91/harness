from __future__ import annotations

from harness.shared.core.verification_gate_selector import (
    DOCS_ONLY,
    FRONTEND,
    JAVA_SPRING,
    MIXED,
    classify_verification_impact,
    is_autofix_command,
    select_verification_gates,
)


def test_select_verification_gates_for_java_spring_paths() -> None:
    selection = select_verification_gates(["src/main/java/com/example/App.java", "build.gradle"])

    commands = [gate.command for gate in selection.recommended_gates]
    assert selection.impact_area == JAVA_SPRING
    assert "./gradlew spotlessCheck" in commands
    assert "./gradlew test" in commands
    assert all("spotlessApply" not in command for command in commands)


def test_select_verification_gates_for_frontend_paths() -> None:
    selection = select_verification_gates(["package.json", "src/components/Button.tsx"])

    commands = [gate.command for gate in selection.recommended_gates]
    assert selection.impact_area == FRONTEND
    assert "pnpm format:check" in commands
    assert "pnpm lint" in commands
    assert not is_autofix_command("pnpm format:check")
    assert is_autofix_command("pnpm format")


def test_autofix_command_detects_gradle_multi_module_spotless_apply() -> None:
    assert is_autofix_command("./gradlew :spotlessApply")
    assert is_autofix_command("./gradlew :api:spotlessApply")
    assert is_autofix_command("./gradlew :api:sub:spotlessApply")


def test_autofix_command_detects_workspace_package_manager_format_variants() -> None:
    assert is_autofix_command("pnpm run format")
    assert is_autofix_command("pnpm --filter web format")
    assert is_autofix_command("pnpm --filter web run format")
    assert is_autofix_command("pnpm -r format")
    assert is_autofix_command("npm --prefix frontend run format")
    assert is_autofix_command("yarn workspace web format")


def test_select_verification_gates_for_docs_only_paths() -> None:
    selection = select_verification_gates(["docs/api.md", "README.md"])

    assert selection.impact_area == DOCS_ONLY
    assert selection.recommended_gates == ()
    assert selection.manual_checks


def test_txt_fixture_outside_docs_is_not_docs_only() -> None:
    selection = select_verification_gates(["src/test/resources/input.txt"])

    assert selection.impact_area == MIXED
    assert selection.recommended_gates


def test_doc_like_fixture_outside_docs_is_not_docs_only() -> None:
    for path in (
        "src/test/resources/input.md",
        "src/test/resources/docs/input.md",
        "src/main/resources/template.mdx",
    ):
        selection = select_verification_gates([path])

        assert selection.impact_area == MIXED
        assert selection.recommended_gates


def test_txt_doc_inside_docs_is_docs_only() -> None:
    selection = select_verification_gates(["docs/release-notes.txt"])

    assert selection.impact_area == DOCS_ONLY


def test_readme_prefixed_frontend_component_is_not_docs_only() -> None:
    selection = select_verification_gates(["src/components/ReadmePanel.tsx"])

    assert selection.impact_area == FRONTEND
    assert selection.recommended_gates


def test_frontend_mdx_build_target_is_not_docs_only() -> None:
    selection = select_verification_gates(["frontend/src/pages/Guide.mdx"])

    assert selection.impact_area == FRONTEND
    assert selection.recommended_gates


def test_root_level_frontend_mdx_build_targets_are_not_docs_only() -> None:
    for path in ("src/pages/Guide.mdx", "app/page.mdx", "pages/index.mdx"):
        selection = select_verification_gates([path])

        assert selection.impact_area == FRONTEND
        assert selection.recommended_gates


def test_docs_frontend_mdx_remains_docs_only() -> None:
    selection = select_verification_gates(["docs/frontend/Guide.mdx"])

    assert selection.impact_area == DOCS_ONLY


def test_classify_mixed_when_frontend_and_java_paths_overlap() -> None:
    impact = classify_verification_impact(["src/main/java/App.java", "frontend/src/App.tsx"])

    assert impact == MIXED
