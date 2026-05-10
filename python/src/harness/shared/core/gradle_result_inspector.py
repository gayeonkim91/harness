"""Inspect Gradle verification artifacts without depending on Gradle itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class FailedTest:
    """One failed JUnit testcase discovered in build/test-results."""

    class_name: str
    test_name: str
    failure_type: str
    message: str
    suite_name: str | None = None


@dataclass(frozen=True, slots=True)
class GradleGateFailure:
    """A pre-test Gradle gate failure such as spotlessCheck or checkstyle."""

    gate_key: str
    task_name: str
    summary: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GradleInspectionResult:
    """Aggregated Gradle test/gate result for verification reporting."""

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    failed_tests: tuple[FailedTest, ...] = field(default_factory=tuple)
    report_refs: tuple[str, ...] = field(default_factory=tuple)
    gate_failures: tuple[GradleGateFailure, ...] = field(default_factory=tuple)
    test_execution_status: str = "unknown"
    test_not_run_reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_failures(self) -> bool:
        return bool(self.failures or self.errors or self.gate_failures)

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-friendly payload for skill bridge use."""

        return {
            "tests": self.tests,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "failed_tests": [
                {
                    "class_name": item.class_name,
                    "test_name": item.test_name,
                    "failure_type": item.failure_type,
                    "message": item.message,
                    "suite_name": item.suite_name,
                }
                for item in self.failed_tests
            ],
            "report_refs": list(self.report_refs),
            "gate_failures": [
                {
                    "gate_key": item.gate_key,
                    "task_name": item.task_name,
                    "summary": item.summary,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in self.gate_failures
            ],
            "test_execution_status": self.test_execution_status,
            "test_not_run_reason": self.test_not_run_reason,
            "warnings": list(self.warnings),
        }


def _safe_int(value: str | None) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


def _ref_for_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_test_suites(root: ET.Element) -> list[ET.Element]:
    tag = _strip_namespace(root.tag)
    if tag == "testsuite":
        return [root]
    if tag == "testsuites":
        return [item for item in root if _strip_namespace(item.tag) == "testsuite"]
    return []


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _failure_children(testcase: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in testcase
        if _strip_namespace(child.tag) in {"failure", "error"}
    ]


def _skipped_children(testcase: ET.Element) -> list[ET.Element]:
    return [child for child in testcase if _strip_namespace(child.tag) == "skipped"]


def _parse_junit_xml(path: Path) -> tuple[int, int, int, int, list[FailedTest], str | None]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0, 0, 0, 0, [], "parse failed"
    except OSError:
        return 0, 0, 0, 0, [], "read failed"

    tests = failures = errors = skipped = 0
    failed_tests: list[FailedTest] = []
    for suite in _iter_test_suites(root):
        testcases = [item for item in suite.iter() if _strip_namespace(item.tag) == "testcase"]
        tests += _safe_int(suite.get("tests")) if suite.get("tests") is not None else len(testcases)
        count_failure_children = suite.get("failures") is None
        count_error_children = suite.get("errors") is None
        failures += _safe_int(suite.get("failures"))
        errors += _safe_int(suite.get("errors"))
        skipped += _safe_int(suite.get("skipped"))
        suite_name = suite.get("name")
        for testcase in testcases:
            failure_children = _failure_children(testcase)
            for child in failure_children:
                tag = _strip_namespace(child.tag)
                failed_tests.append(
                    FailedTest(
                        class_name=testcase.get("classname") or "",
                        test_name=testcase.get("name") or "",
                        failure_type=tag,
                        message=(child.get("message") or "").strip(),
                        suite_name=suite_name,
                    )
                )
                if tag == "failure" and count_failure_children:
                    failures += 1
                if tag == "error" and count_error_children:
                    errors += 1
            if _skipped_children(testcase) and suite.get("skipped") is None:
                skipped += 1
    return tests, failures, errors, skipped, failed_tests, None


def _discover_test_result_xml(build_dir: Path) -> list[Path]:
    test_results = build_dir / "test-results"
    if not test_results.exists():
        return []
    return sorted(path for path in test_results.glob("**/*.xml") if path.is_file())


def _discover_test_report_refs(workspace_root: Path, build_dir: Path) -> list[str]:
    refs: list[str] = []
    test_results = build_dir / "test-results"
    test_reports = build_dir / "reports" / "tests"
    if test_results.exists():
        refs.append(_ref_for_path(workspace_root, test_results))
    if test_reports.exists():
        for index_path in sorted(test_reports.glob("**/index.html")):
            refs.append(_ref_for_path(workspace_root, index_path))
    return refs


_GRADLE_FAILED_TASK_PATTERN = re.compile(
    r"(?:Execution failed for task ['\"](?P<quoted>:[^'\"]+)['\"]|> Task (?P<plain>:[^\s]+) FAILED)"
)


def _failed_tasks_from_console(console_output: str) -> set[str]:
    tasks: set[str] = set()
    for match in _GRADLE_FAILED_TASK_PATTERN.finditer(console_output):
        task = match.group("quoted") or match.group("plain")
        if task:
            tasks.add(task)
    return tasks


def _is_spotless_check_task(task_name: str) -> bool:
    leaf_name = task_name.rsplit(":", 1)[-1]
    return leaf_name == "spotlessCheck" or (leaf_name.startswith("spotless") and leaf_name.endswith("Check"))


def _spotless_failures(workspace_root: Path, build_dir: Path, console_output: str) -> list[GradleGateFailure]:
    failed_tasks = _failed_tasks_from_console(console_output)
    spotless_tasks = sorted(task for task in failed_tasks if _is_spotless_check_task(task))
    if not spotless_tasks:
        return []

    task_name = spotless_tasks[0].rsplit(":", 1)[-1]
    evidence_refs: list[str] = []
    spotless_reports = build_dir / "reports" / "spotless"
    if spotless_reports.exists():
        evidence_refs.append(_ref_for_path(workspace_root, spotless_reports))
    return [
        GradleGateFailure(
            gate_key="spotless-check",
            task_name=task_name,
            summary=f"{task_name} failed before tests could be trusted.",
            evidence_refs=tuple(evidence_refs),
        )
    ]


def _checkstyle_failures(workspace_root: Path, build_dir: Path, console_output: str) -> list[GradleGateFailure]:
    evidence_refs: list[str] = []
    violation_count = 0
    checkstyle_reports = build_dir / "reports" / "checkstyle"
    if checkstyle_reports.exists():
        evidence_refs.append(_ref_for_path(workspace_root, checkstyle_reports))
        for report in sorted(checkstyle_reports.glob("*.xml")):
            try:
                root = ET.parse(report).getroot()
            except (ET.ParseError, OSError):
                continue
            violation_count += len(root.findall(".//error"))

    failed_tasks = _failed_tasks_from_console(console_output)
    console_failed = any("checkstyle" in task.lower() for task in failed_tasks) or (
        ":checkstyle" in console_output.lower() and "FAILED" in console_output
    )
    if violation_count == 0 and not console_failed:
        return []

    summary = "checkstyle failed"
    if violation_count:
        summary = f"checkstyle failed with {violation_count} violation(s)."
    return [
        GradleGateFailure(
            gate_key="checkstyle",
            task_name="checkstyle",
            summary=summary,
            evidence_refs=tuple(evidence_refs),
        )
    ]


def inspect_gradle_results(
    workspace_root: str | Path,
    *,
    build_dir: str | Path | None = None,
    console_output: str = "",
) -> GradleInspectionResult:
    """Inspect Gradle test result/report directories and known pre-test gate failures."""

    root = Path(workspace_root)
    if build_dir is None:
        resolved_build_dir = root / "build"
    else:
        candidate_build_dir = Path(build_dir)
        resolved_build_dir = candidate_build_dir if candidate_build_dir.is_absolute() else root / candidate_build_dir
    xml_paths = _discover_test_result_xml(resolved_build_dir)
    report_refs = _discover_test_report_refs(root, resolved_build_dir)

    tests = failures = errors = skipped = 0
    failed_tests: list[FailedTest] = []
    warnings: list[str] = []
    for xml_path in xml_paths:
        (
            parsed_tests,
            parsed_failures,
            parsed_errors,
            parsed_skipped,
            parsed_failed_tests,
            parse_warning,
        ) = _parse_junit_xml(xml_path)
        tests += parsed_tests
        failures += parsed_failures
        errors += parsed_errors
        skipped += parsed_skipped
        failed_tests.extend(parsed_failed_tests)
        if parse_warning is not None:
            warnings.append(f"Gradle JUnit XML {parse_warning}: {_ref_for_path(root, xml_path)}")

    gate_failures = _spotless_failures(root, resolved_build_dir, console_output)
    gate_failures.extend(_checkstyle_failures(root, resolved_build_dir, console_output))

    if gate_failures:
        test_execution_status = "not_run"
        test_not_run_reason = "pre-test Gradle gate failed before test reports were produced"
    elif xml_paths:
        if failures or errors:
            test_execution_status = "failed"
        elif warnings:
            test_execution_status = "unknown"
        else:
            test_execution_status = "passed"
        test_not_run_reason = None
    else:
        test_execution_status = "unknown"
        test_not_run_reason = None
        warnings.append("No Gradle test result XML was found under build/test-results.")

    return GradleInspectionResult(
        tests=tests,
        failures=failures,
        errors=errors,
        skipped=skipped,
        failed_tests=tuple(failed_tests),
        report_refs=tuple(report_refs),
        gate_failures=tuple(gate_failures),
        test_execution_status=test_execution_status,
        test_not_run_reason=test_not_run_reason,
        warnings=tuple(warnings),
    )


def format_gradle_inspection_for_verification(result: GradleInspectionResult) -> list[str]:
    """Render concise Korean lines suitable for verification.md."""

    lines: list[str] = []
    for failure in result.gate_failures:
        lines.append(f"- 선행 게이트 실패: {failure.task_name} - {failure.summary}")
    if result.test_execution_status == "not_run":
        lines.append(f"- 테스트 미실행: {result.test_not_run_reason or '선행 게이트 실패로 테스트 report가 없음'}")
    elif result.test_execution_status in {"passed", "failed"}:
        lines.append(
            "- 테스트 집계: "
            f"tests={result.tests}, failures={result.failures}, errors={result.errors}, skipped={result.skipped}"
        )
    else:
        if result.warnings:
            lines.append(f"- 테스트 상태 미확인: {result.warnings[0]}")
        else:
            lines.append("- 테스트 상태 미확인: build/test-results XML을 찾지 못함")
    artifact_refs: list[str] = []
    for ref in result.report_refs:
        if ref not in artifact_refs:
            artifact_refs.append(ref)
    for failure in result.gate_failures:
        for ref in failure.evidence_refs:
            if ref not in artifact_refs:
                artifact_refs.append(ref)
    if artifact_refs:
        lines.append(f"- 근거 artifact: {', '.join(artifact_refs)}")
    return lines
