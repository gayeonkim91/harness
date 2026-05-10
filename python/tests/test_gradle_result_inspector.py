from __future__ import annotations

from pathlib import Path

from harness.shared.core.gradle_result_inspector import (
    format_gradle_inspection_for_verification,
    inspect_gradle_results,
)


def test_inspect_gradle_results_aggregates_junit_xml_and_report_refs(tmp_path: Path) -> None:
    build_dir = tmp_path / "build"
    result_dir = build_dir / "test-results" / "test"
    report_dir = build_dir / "reports" / "tests" / "test"
    result_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (report_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (result_dir / "TEST-example.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="ExampleTest" tests="3" failures="1" errors="0" skipped="1">
  <testcase classname="ExampleTest" name="passes"/>
  <testcase classname="ExampleTest" name="fails">
    <failure message="expected true"/>
  </testcase>
  <testcase classname="ExampleTest" name="skipped">
    <skipped/>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = inspect_gradle_results(tmp_path)

    assert result.test_execution_status == "failed"
    assert result.tests == 3
    assert result.failures == 1
    assert result.errors == 0
    assert result.skipped == 1
    assert result.failed_tests[0].class_name == "ExampleTest"
    assert "build/test-results" in result.report_refs
    assert "build/reports/tests/test/index.html" in result.report_refs


def test_inspect_gradle_results_resolves_relative_build_dir_under_workspace(tmp_path: Path) -> None:
    result_dir = tmp_path / "custom-build" / "test-results" / "test"
    result_dir.mkdir(parents=True)
    (result_dir / "TEST-example.xml").write_text(
        """<testsuite name="ExampleTest" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="ExampleTest" name="passes"/>
</testsuite>
""",
        encoding="utf-8",
    )

    result = inspect_gradle_results(tmp_path, build_dir="custom-build")

    assert result.test_execution_status == "passed"
    assert result.tests == 1


def test_inspect_gradle_results_counts_failure_children_when_suite_attributes_missing(tmp_path: Path) -> None:
    result_dir = tmp_path / "build" / "test-results" / "test"
    result_dir.mkdir(parents=True)
    (result_dir / "TEST-example.xml").write_text(
        """<testsuite name="ExampleTest">
  <testcase classname="ExampleTest" name="fails">
    <failure message="expected true"/>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = inspect_gradle_results(tmp_path)

    assert result.test_execution_status == "failed"
    assert result.tests == 1
    assert result.failures == 1
    assert result.failed_tests[0].test_name == "fails"


def test_inspect_gradle_results_marks_broken_junit_xml_unknown(tmp_path: Path) -> None:
    result_dir = tmp_path / "build" / "test-results" / "test"
    result_dir.mkdir(parents=True)
    (result_dir / "TEST-broken.xml").write_text("<testsuite", encoding="utf-8")

    result = inspect_gradle_results(tmp_path)
    lines = format_gradle_inspection_for_verification(result)

    assert result.test_execution_status == "unknown"
    assert result.tests == 0
    assert "Gradle JUnit XML parse failed: build/test-results/test/TEST-broken.xml" in result.warnings
    assert any("TEST-broken.xml" in line for line in lines)


def test_inspect_gradle_results_marks_tests_not_run_after_spotless_failure(tmp_path: Path) -> None:
    console_output = "> Task :spotlessCheck FAILED\nExecution failed for task ':spotlessCheck'."

    result = inspect_gradle_results(tmp_path, console_output=console_output)
    lines = format_gradle_inspection_for_verification(result)

    assert result.test_execution_status == "not_run"
    assert result.gate_failures[0].gate_key == "spotless-check"
    assert any("테스트 미실행" in line for line in lines)


def test_inspect_gradle_results_prioritizes_pre_gate_failure_over_stale_xml(tmp_path: Path) -> None:
    result_dir = tmp_path / "build" / "test-results" / "test"
    result_dir.mkdir(parents=True)
    (result_dir / "TEST-stale.xml").write_text(
        """<testsuite name="StaleTest" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="StaleTest" name="passes"/>
</testsuite>
""",
        encoding="utf-8",
    )
    console_output = "> Task :spotlessCheck FAILED\nExecution failed for task ':spotlessCheck'."

    result = inspect_gradle_results(tmp_path, console_output=console_output)
    lines = format_gradle_inspection_for_verification(result)

    assert result.test_execution_status == "not_run"
    assert result.tests == 1
    assert result.gate_failures[0].gate_key == "spotless-check"
    assert any("테스트 미실행" in line for line in lines)
    assert not any("테스트 집계" in line for line in lines)


def test_inspect_gradle_results_detects_spotless_subcheck_tasks_before_stale_xml(tmp_path: Path) -> None:
    result_dir = tmp_path / "build" / "test-results" / "test"
    result_dir.mkdir(parents=True)
    (result_dir / "TEST-stale.xml").write_text(
        """<testsuite name="StaleTest" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="StaleTest" name="passes"/>
</testsuite>
""",
        encoding="utf-8",
    )
    console_output = "> Task :spotlessJavaCheck FAILED\nExecution failed for task ':spotlessJavaCheck'."

    result = inspect_gradle_results(tmp_path, console_output=console_output)

    assert result.test_execution_status == "not_run"
    assert result.gate_failures[0].gate_key == "spotless-check"
    assert result.gate_failures[0].task_name == "spotlessJavaCheck"


def test_format_gradle_inspection_includes_pre_gate_evidence_refs(tmp_path: Path) -> None:
    report_dir = tmp_path / "build" / "reports" / "spotless"
    report_dir.mkdir(parents=True)
    console_output = "> Task :spotlessCheck FAILED\nExecution failed for task ':spotlessCheck'."

    result = inspect_gradle_results(tmp_path, console_output=console_output)
    lines = format_gradle_inspection_for_verification(result)

    assert result.gate_failures[0].evidence_refs == ("build/reports/spotless",)
    assert any("build/reports/spotless" in line for line in lines)


def test_inspect_gradle_results_does_not_match_plain_non_gradle_task_failure(tmp_path: Path) -> None:
    console_output = "> Task spotlessCheck FAILED"

    result = inspect_gradle_results(tmp_path, console_output=console_output)

    assert result.test_execution_status == "unknown"
    assert result.gate_failures == ()


def test_inspect_gradle_results_detects_checkstyle_report_violations(tmp_path: Path) -> None:
    report_dir = tmp_path / "build" / "reports" / "checkstyle"
    report_dir.mkdir(parents=True)
    (report_dir / "main.xml").write_text(
        """<checkstyle>
  <file name="Example.java">
    <error line="1" message="bad import"/>
  </file>
</checkstyle>
""",
        encoding="utf-8",
    )

    result = inspect_gradle_results(tmp_path)

    assert result.gate_failures[0].gate_key == "checkstyle"
    assert "1 violation" in result.gate_failures[0].summary
