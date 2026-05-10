"""Deterministic applier helper used by /wf-apply."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.shared.artifacts.apply_sink import record_apply_partial_recovery
from harness.shared.artifacts.plan_artifact import append_to_section
from harness.shared.artifacts.state_artifact import apply_deferred_transition_with_apply_result, read_state
from harness.shared.contracts.actions import (
    ArtifactAction,
    ArtifactTarget,
    CurrentStepRefSnapshot,
    SelectionBasis,
    SelectionMode,
)
from harness.shared.contracts.results import ApplyResult, ApplyStatus
from harness.shared.contracts.state import (
    CurrentPhase,
    DeferredStateTransition,
    HarnessCounters,
    HarnessState,
    ReviewOutcome,
    SessionState,
)
from harness.shared.core.json_util import to_jsonable
from harness.shared.core.state_migration import StateMigrationError
from harness.shared.core.step_source import resolve_step_artifact
from harness.shared.core.steps_parser import ParsedStep, StepParseResult, find_step, parse_steps
from harness.shared.core.task_paths import get_task_paths


@dataclass(slots=True)
class ApplyRuntimeInput:
    """Normalized apply input passed from the /wf-apply skill prompt."""

    task_root: Path
    required_artifact_actions: list[ArtifactAction] = field(default_factory=list)
    routing_basis_ref: str = ""
    deferred_state_transition: DeferredStateTransition | None = None

    def __post_init__(self) -> None:
        self.task_root = Path(self.task_root)
        self.required_artifact_actions = [_normalize_action(action) for action in self.required_artifact_actions]
        if isinstance(self.deferred_state_transition, dict):
            self.deferred_state_transition = _normalize_transition(self.deferred_state_transition)


def execute_apply_runtime(input_data: ApplyRuntimeInput) -> ApplyResult:
    """Apply deterministic artifact actions and state handoff."""

    task_paths = get_task_paths(input_data.task_root)
    actions = input_data.required_artifact_actions
    plan_actions = [action for action in actions if action.target == ArtifactTarget.PLAN]
    steps_actions = [action for action in actions if action.target == ArtifactTarget.STEPS]

    base_state: HarnessState | None = None
    if input_data.deferred_state_transition is not None:
        state_reason, base_state = _validate_deferred_state_precondition(task_paths.state_path)
        if state_reason is not None:
            return _blocked(state_reason)

    unsupported = _first_unsupported_action(actions)
    if unsupported is not None:
        return _blocked(unsupported)

    step_artifact = None
    if steps_actions:
        try:
            step_artifact = resolve_step_artifact(task_paths.task_root)
        except OSError:
            return _blocked("APPLY_TARGET_ARTIFACT_MISSING")
        if step_artifact is None:
            return _blocked("APPLY_TARGET_ARTIFACT_MISSING")
    steps_target_is_plan = step_artifact is not None and step_artifact.path == task_paths.plan_path

    if plan_actions and not task_paths.plan_path.exists():
        return _blocked("APPLY_TARGET_ARTIFACT_MISSING")

    try:
        plan_content = None
        if plan_actions or steps_target_is_plan:
            plan_content = (
                step_artifact.content
                if steps_target_is_plan and step_artifact is not None
                else task_paths.plan_path.read_text(encoding="utf-8")
            )
        steps_content = step_artifact.content if step_artifact is not None else None
    except OSError:
        return _blocked("APPLY_TARGET_ARTIFACT_MISSING")

    base_steps = None
    if steps_content is not None:
        base_steps = parse_steps(steps_content)
        if base_steps.reason_code is not None:
            return _blocked(base_steps.reason_code)

    applied: list[ArtifactAction] = []
    noop: list[ArtifactAction] = []
    updated_artifacts: set[str] = set()

    next_plan = plan_content
    next_steps = None if steps_target_is_plan else steps_content
    for action in actions:
        if action.target == ArtifactTarget.PLAN:
            assert next_plan is not None
            rendered, changed = _apply_plan_action(next_plan, action)
            next_plan = rendered
            artifact_name = "plan"
        else:
            step_content = next_plan if steps_target_is_plan else next_steps
            assert step_content is not None
            assert base_steps is not None
            normalized_action, validation_reason = _normalize_step_action_against_base(action, base_steps)
            if validation_reason is not None:
                return _blocked(validation_reason)
            assert normalized_action is not None
            rendered, changed, reason = _apply_steps_action(
                step_content,
                normalized_action,
                legacy_note_format=step_artifact is not None and step_artifact.artifact_name == "steps",
            )
            if reason is not None:
                return _blocked(reason)
            if steps_target_is_plan:
                next_plan = rendered
            else:
                next_steps = rendered
            artifact_name = step_artifact.artifact_name if step_artifact is not None else action.target.value

        if changed:
            applied.append(normalized_action if action.target == ArtifactTarget.STEPS else action)
            updated_artifacts.add(artifact_name)
        else:
            noop.append(normalized_action if action.target == ArtifactTarget.STEPS else action)

    final_steps_content = next_plan if steps_target_is_plan else next_steps
    current_step_ref_update_mode, resolved_current_step_ref, pointer_reason = (
        _resolve_current_step_ref_update(steps_content, final_steps_content)
        if steps_actions
        else ("unchanged", None, None)
    )
    if pointer_reason is not None:
        return _blocked(pointer_reason)

    committed_artifacts: list[str] = []
    try:
        if next_plan is not None and next_plan != plan_content:
            _atomic_write(task_paths.plan_path, next_plan)
            committed_artifacts.append("plan")
        if (
            not steps_target_is_plan
            and step_artifact is not None
            and next_steps is not None
            and next_steps != steps_content
        ):
            _atomic_write(step_artifact.path, next_steps)
            committed_artifacts.append(step_artifact.artifact_name)
    except OSError:
        committed_targets = set(committed_artifacts)
        recovery_ref = record_apply_partial_recovery(
            task_paths.logs_dir,
            reason_code="APPLY_COMMIT_PARTIAL",
            updated_artifacts=committed_artifacts,
            required_artifact_actions=[to_jsonable(action) for action in actions],
            routing_basis_ref=input_data.routing_basis_ref,
        )
        return ApplyResult(
            apply_status=ApplyStatus.BLOCKED,
            reason_code="APPLY_COMMIT_PARTIAL",
            applied_actions=[action for action in applied if action.target.value in committed_targets],
            noop_actions=noop,
            updated_artifacts=committed_artifacts,
            current_step_ref_update_mode="unchanged",
            resolved_current_step_ref=None,
            summary=f"Artifact write failed after in-memory apply. recovery_ref={recovery_ref}",
        )

    status = ApplyStatus.APPLIED if applied else ApplyStatus.NOOP
    result = ApplyResult(
        apply_status=status,
        reason_code=None,
        applied_actions=applied,
        noop_actions=noop,
        updated_artifacts=sorted(updated_artifacts),
        current_step_ref_update_mode=current_step_ref_update_mode,
        resolved_current_step_ref=resolved_current_step_ref,
        summary="Applied artifact actions." if applied else "No artifact changes.",
    )
    if input_data.deferred_state_transition is not None and result.apply_status != ApplyStatus.BLOCKED:
        apply_deferred_transition_with_apply_result(
            task_paths.state_path,
            input_data.deferred_state_transition,
            result,
            base_state=base_state,
        )
    return result


SUPPORTED_ACTIONS = {
    (ArtifactTarget.PLAN, "plan.record_contract_note"),
    (ArtifactTarget.PLAN, "plan.rewrite_required"),
    (ArtifactTarget.STEPS, "steps.mark_current_step_done"),
    (ArtifactTarget.STEPS, "steps.clear_current_step"),
    (ArtifactTarget.STEPS, "steps.record_working_note"),
    (ArtifactTarget.STEPS, "steps.select_next_go_step"),
    (ArtifactTarget.STEPS, "steps.rewrite_required"),
}


def _normalize_action(action: ArtifactAction | dict[str, Any]) -> ArtifactAction:
    if isinstance(action, ArtifactAction):
        return ArtifactAction(
            target=ArtifactTarget(action.target),
            action=str(action.action),
            params=_normalize_action_params(action.params),
            basis_ref=str(action.basis_ref),
        )
    payload = dict(action)
    return ArtifactAction(
        target=ArtifactTarget(payload["target"]),
        action=str(payload["action"]),
        params=_normalize_action_params(dict(payload.get("params", {}))),
        basis_ref=str(payload.get("basis_ref", "")),
    )


def _normalize_action_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    snapshot = normalized.get("current_step_ref_snapshot")
    if isinstance(snapshot, dict):
        normalized["current_step_ref_snapshot"] = CurrentStepRefSnapshot(
            step_ref=str(snapshot["step_ref"]),
            step_text=str(snapshot["step_text"]),
            go_marker_present=bool(snapshot["go_marker_present"]),
        )
    selection_basis = normalized.get("selection_basis")
    if isinstance(selection_basis, dict):
        normalized["selection_basis"] = SelectionBasis(
            mode=SelectionMode(selection_basis["mode"]),
            explicit_step_ref=selection_basis.get("explicit_step_ref"),
        )
    return normalized


def _normalize_transition(payload: dict[str, Any]) -> DeferredStateTransition:
    counters_payload = payload.get("counters", {})
    approvals_payload = payload.get("approvals_granted") if "approvals_granted" in payload else None
    return DeferredStateTransition(
        session_state=SessionState(payload["session_state"]),
        current_phase=CurrentPhase(payload["current_phase"]),
        pending_approval_for=payload.get("pending_approval_for"),
        review_outcome=ReviewOutcome(payload["review_outcome"]) if payload.get("review_outcome") is not None else None,
        closure_authorized=bool(payload["closure_authorized"]),
        counters=HarnessCounters(
            rework_count=int(counters_payload.get("rework_count", 0)),
            rewrite_count=int(counters_payload.get("rewrite_count", 0)),
            rollback_count=int(counters_payload.get("rollback_count", 0)),
        ),
        blocked_transition=payload.get("blocked_transition"),
        blocked_reason_ref=payload.get("blocked_reason_ref"),
        stop_condition_ref=payload.get("stop_condition_ref"),
        approvals_granted=None if approvals_payload is None else [int(item) for item in approvals_payload],
    )


def _blocked(reason_code: str) -> ApplyResult:
    return ApplyResult(apply_status=ApplyStatus.BLOCKED, reason_code=reason_code, summary="Apply blocked.")


def _validate_deferred_state_precondition(state_path: Path) -> tuple[str | None, HarnessState | None]:
    if not state_path.exists():
        return "STATE_ARTIFACT_MISSING", None
    try:
        state = read_state(state_path)
    except (StateMigrationError, OSError, KeyError, TypeError, ValueError):
        return "STATE_ARTIFACT_INVALID", None
    return None, state


def _first_unsupported_action(actions: list[ArtifactAction]) -> str | None:
    for action in actions:
        if (action.target, action.action) not in SUPPORTED_ACTIONS:
            return "APPLY_UNSUPPORTED_ACTION"
    return None


def _atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _apply_plan_action(content: str, action: ArtifactAction) -> tuple[str, bool]:
    if action.action == "plan.record_contract_note":
        note_text = str(action.params["note_text"])
        basis_refs = [str(item) for item in action.params.get("note_basis_refs", [])]
        entry = f"- [contract-note] {note_text}"
        if basis_refs:
            entry += f" [basis_refs={', '.join(basis_refs)}]"
    else:
        entry = f"- [rewrite-required] {action.params['rewrite_reason_code']} [basis_ref={action.basis_ref}]"
    rendered = append_to_section(content, "Contract Notes", entry)
    return rendered, rendered != content


def _normalize_step_action_against_base(
    action: ArtifactAction,
    base_steps: StepParseResult,
) -> tuple[ArtifactAction | None, str | None]:
    snapshot = action.params.get("current_step_ref_snapshot")
    if not isinstance(snapshot, CurrentStepRefSnapshot):
        return None, "APPLY_CURRENT_STEP_REF_SNAPSHOT_REQUIRED"
    matching_step = find_step(base_steps.steps, snapshot.step_ref)
    if matching_step is None:
        return None, "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    if matching_step.text != snapshot.step_text.strip():
        return None, "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    if matching_step.go_marker_present != snapshot.go_marker_present:
        return None, "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    normalized_params = dict(action.params)
    normalized_params["current_step_ref_snapshot"] = CurrentStepRefSnapshot(
        step_ref=matching_step.step_ref,
        step_text=matching_step.text,
        go_marker_present=matching_step.go_marker_present,
    )
    return (
        ArtifactAction(
            target=action.target,
            action=action.action,
            params=normalized_params,
            basis_ref=action.basis_ref,
        ),
        None,
    )


def _apply_steps_action(
    content: str,
    action: ArtifactAction,
    *,
    legacy_note_format: bool = False,
) -> tuple[str, bool, str | None]:
    snapshot = action.params["current_step_ref_snapshot"]
    if action.action == "steps.record_working_note":
        if legacy_note_format:
            entry = f"- [step_ref={snapshot.step_ref}] {action.params['note_text']}"
        else:
            entry = f"- [step] {snapshot.step_text}: {action.params['note_text']}"
        basis_refs = [str(item) for item in action.params.get("note_basis_refs", [])]
        if basis_refs:
            entry += f" [basis_refs={', '.join(basis_refs)}]"
        rendered = append_to_section(content, "Working Notes", entry)
        return rendered, rendered != content, None
    if action.action == "steps.rewrite_required":
        if legacy_note_format:
            entry = (
                f"- [step_ref={snapshot.step_ref}] rewrite-required:{action.params['rewrite_reason_code']} "
                f"[basis_ref={action.basis_ref}]"
            )
        else:
            entry = (
                f"- [step] {snapshot.step_text}: rewrite-required:{action.params['rewrite_reason_code']} "
                f"[basis_ref={action.basis_ref}]"
            )
        rendered = append_to_section(content, "Working Notes", entry)
        return rendered, rendered != content, None

    parsed = parse_steps(content)
    if parsed.reason_code is not None:
        return content, False, parsed.reason_code
    step = find_step(parsed.steps, snapshot.step_ref)
    if step is None:
        return content, False, "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
    lines = content.splitlines()
    if action.action == "steps.mark_current_step_done":
        if step.mark.lower() == "x":
            return content, False, None
        lines[step.line_index] = lines[step.line_index].replace("- [ ]", "- [x]", 1)
        return "\n".join(lines) + ("\n" if content.endswith("\n") else ""), True, None
    if action.action == "steps.clear_current_step":
        if not step.go_marker_present:
            if snapshot.go_marker_present:
                return content, False, "APPLY_CURRENT_STEP_REF_SNAPSHOT_MISMATCH"
            return content, False, None
        lines[step.line_index] = _render_step_go_marker(lines[step.line_index], step, go_present=False)
        return "\n".join(lines) + ("\n" if content.endswith("\n") else ""), True, None
    selection_basis = action.params.get("selection_basis")
    if not isinstance(selection_basis, SelectionBasis):
        return content, False, "APPLY_SELECTION_TARGET_NOT_FOUND"
    if any(step_item.go_marker_present for step_item in parsed.steps):
        return content, False, "APPLY_GO_SEQUENCE_INVALID"
    target = _select_step(parsed.steps, snapshot.step_ref, selection_basis)
    if target is None:
        return content, False, "APPLY_SELECTION_TARGET_NOT_FOUND"
    lines[target.line_index] = _render_step_go_marker(lines[target.line_index], target, go_present=True)
    return "\n".join(lines) + ("\n" if content.endswith("\n") else ""), True, None


def _render_step_go_marker(line: str, step: ParsedStep, *, go_present: bool) -> str:
    if step.legacy_step_ref is not None:
        marker = f" [step_ref={step.legacy_step_ref}]"
        if go_present:
            return line.replace(marker, f" (go){marker}", 1)
        return line.replace(f" (go){marker}", marker, 1)
    stripped = line.rstrip()
    if go_present:
        return stripped if stripped.endswith(" (go)") else f"{stripped} (go)"
    if stripped.endswith(" (go)"):
        return stripped[: -len(" (go)")]
    return stripped


def _resolve_current_step_ref_update(
    previous_steps: str | None,
    next_steps: str | None,
) -> tuple[str, str | None, str | None]:
    if previous_steps is None or next_steps is None or previous_steps == next_steps:
        return "unchanged", None, None
    parsed = parse_steps(next_steps)
    if parsed.reason_code is not None:
        return "unchanged", None, parsed.reason_code
    go_steps = [step for step in parsed.steps if step.go_marker_present]
    if len(go_steps) > 1:
        return "unchanged", None, "APPLY_GO_POSTCONDITION_INVALID"
    if len(go_steps) == 1:
        return "set", go_steps[0].step_ref, None
    return "clear", None, None


def _select_step(steps: list[ParsedStep], current_step_ref: str, selection_basis: SelectionBasis) -> ParsedStep | None:
    if selection_basis.mode == SelectionMode.EXPLICIT_STEP_REF:
        if selection_basis.explicit_step_ref is None:
            return None
        return find_step(steps, selection_basis.explicit_step_ref)
    if selection_basis.mode == SelectionMode.FIRST_PENDING:
        return next((step for step in steps if step.mark == " "), None)
    if selection_basis.mode == SelectionMode.NEXT_PENDING_AFTER_CURRENT:
        seen_current = False
        for step in steps:
            if step.step_ref == current_step_ref:
                seen_current = True
                continue
            if seen_current and step.mark == " ":
                return step
    return None
