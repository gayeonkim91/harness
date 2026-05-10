"""Schema helpers for invoking the test-report skill from verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar


TEST_REPORT_SKILL_NAME = "test-report"
TEST_REPORT_STANDALONE_REF = "skill:test-report#standalone"
TEST_REPORT_VERIFICATION_ASSIST_REF = "skill:test-report#verification-assist"
VALID_TEST_REPORT_MODES = {"standalone", "verification_assist"}


@dataclass(frozen=True, slots=True)
class TestReportSkillBridgeInput:
    """Input contract for a test-report skill invocation payload."""

    __test__: ClassVar[bool] = False

    mode: str
    command: str
    exit_status: str
    task_root: str | Path | None = None
    plan_ref: str | None = None
    verification_ref: str | None = None
    report_refs: list[str] = field(default_factory=list)
    aggregate: dict[str, Any] = field(default_factory=dict)
    failure_summary: list[str] = field(default_factory=list)
    task_scope_summary: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in VALID_TEST_REPORT_MODES:
            raise ValueError(f"Unsupported test-report mode: {self.mode}")
        if not self.command.strip():
            raise ValueError("test-report bridge command is required.")
        if not self.exit_status.strip():
            raise ValueError("test-report bridge exit_status is required.")


def test_report_basis_ref(mode: str = "verification_assist") -> str:
    """Return the marker ref proving that test-report was used."""

    if mode == "standalone":
        return TEST_REPORT_STANDALONE_REF
    if mode == "verification_assist":
        return TEST_REPORT_VERIFICATION_ASSIST_REF
    raise ValueError(f"Unsupported test-report mode: {mode}")


def uses_test_report_verification_assist(basis_refs: list[str] | tuple[str, ...]) -> bool:
    """Return True when basis refs include the verification-assist marker."""

    return any(str(ref) == TEST_REPORT_VERIFICATION_ASSIST_REF for ref in basis_refs)


def build_test_report_skill_payload(input_data: TestReportSkillBridgeInput) -> dict[str, object]:
    """Build the structured payload handed to the test-report skill."""

    payload: dict[str, object] = {
        "skill": TEST_REPORT_SKILL_NAME,
        "mode": input_data.mode,
        "command": input_data.command,
        "exit_status": input_data.exit_status,
        "report_refs": list(input_data.report_refs),
        "aggregate": dict(input_data.aggregate),
        "failure_summary": list(input_data.failure_summary),
        "basis_ref": test_report_basis_ref(input_data.mode),
    }
    if input_data.task_root is not None:
        payload["task_root"] = str(input_data.task_root)
    if input_data.plan_ref is not None:
        payload["plan_ref"] = input_data.plan_ref
    if input_data.verification_ref is not None:
        payload["verification_ref"] = input_data.verification_ref
    if input_data.task_scope_summary is not None:
        payload["task_scope_summary"] = input_data.task_scope_summary
    return payload


def append_test_report_basis_ref(basis_refs: list[str], mode: str = "verification_assist") -> list[str]:
    """Return basis refs with the appropriate test-report marker added once."""

    marker = test_report_basis_ref(mode)
    if marker in basis_refs:
        return list(basis_refs)
    return [*basis_refs, marker]
