from __future__ import annotations

import pytest

from harness.shared.integrations.test_report_skill_bridge import (
    TEST_REPORT_STANDALONE_REF,
    TEST_REPORT_VERIFICATION_ASSIST_REF,
    TestReportSkillBridgeInput,
    append_test_report_basis_ref,
    build_test_report_skill_payload,
    uses_test_report_verification_assist,
)


def test_build_test_report_skill_payload_for_verification_assist() -> None:
    payload = build_test_report_skill_payload(
        TestReportSkillBridgeInput(
            mode="verification_assist",
            command="./gradlew test",
            exit_status="failed",
            task_root="tasks/example",
            plan_ref="plan.md#verification",
            report_refs=["build/test-results/test"],
            aggregate={"tests": 3, "failures": 1},
            failure_summary=["ExampleTest.fails"],
            task_scope_summary="Java service change",
        )
    )

    assert payload["skill"] == "test-report"
    assert payload["mode"] == "verification_assist"
    assert payload["basis_ref"] == TEST_REPORT_VERIFICATION_ASSIST_REF
    assert payload["aggregate"] == {"tests": 3, "failures": 1}


def test_append_and_detect_test_report_basis_ref() -> None:
    refs = append_test_report_basis_ref(["build/test-results/test"])

    assert refs == ["build/test-results/test", TEST_REPORT_VERIFICATION_ASSIST_REF]
    assert append_test_report_basis_ref(refs) == refs
    assert uses_test_report_verification_assist(refs)
    assert not uses_test_report_verification_assist([TEST_REPORT_STANDALONE_REF])


def test_bridge_input_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        TestReportSkillBridgeInput(mode="unknown", command="./gradlew test", exit_status="passed")
