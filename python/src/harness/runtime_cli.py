"""Common launcher for skill-invoked Python runtime helpers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.shared.core.json_util import to_jsonable
from harness.shared.runtime.apply_runtime import ApplyRuntimeInput, execute_apply_runtime
from harness.shared.runtime.checkpoint_runtime import CheckpointRuntimeInput, persist_checkpoint_runtime
from harness.shared.core.start_mode_resolver import StartModeResolverInput, resolve_start_mode
from harness.shared.runtime.next_runtime import NextRuntimeInput, execute_next_runtime
from harness.shared.runtime.review_runtime import ReviewRuntimeInput, persist_review_runtime
from harness.shared.runtime.start_runtime import StartRuntimeInput, execute_start_runtime
from harness.shared.runtime.verify_runtime import VerifyRuntimeInput, persist_verify_runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-runtime")
    parser.add_argument(
        "helper_name",
        choices=(
            "wf-start-mode-resolver",
            "wf-start-runtime",
            "wf-checkpoint-runtime",
            "wf-next-runtime",
            "wf-apply-runtime",
            "wf-verify-runtime",
            "wf-review-runtime",
        ),
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="JSON input file. When omitted, JSON is read from stdin.",
    )
    return parser


def _load_payload(input_file: Path | None) -> dict[str, object]:
    if input_file is not None:
        return json.loads(input_file.read_text(encoding="utf-8"))

    raw = sys.stdin.read().strip()
    if not raw:
        raise ValueError("Runtime helper input JSON is required.")
    return json.loads(raw)


def _dispatch(helper_name: str, payload: dict[str, object]) -> object:
    if helper_name == "wf-start-mode-resolver":
        return resolve_start_mode(StartModeResolverInput(**payload)).to_payload()
    if helper_name == "wf-start-runtime":
        return execute_start_runtime(StartRuntimeInput(**payload))
    if helper_name == "wf-checkpoint-runtime":
        return persist_checkpoint_runtime(CheckpointRuntimeInput(**payload))
    if helper_name == "wf-next-runtime":
        return execute_next_runtime(NextRuntimeInput(**payload))
    if helper_name == "wf-apply-runtime":
        return execute_apply_runtime(ApplyRuntimeInput(**payload))
    if helper_name == "wf-verify-runtime":
        return persist_verify_runtime(VerifyRuntimeInput(**payload))
    if helper_name == "wf-review-runtime":
        return persist_review_runtime(ReviewRuntimeInput(**payload))
    raise ValueError(f"Unsupported helper: {helper_name}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    payload = _load_payload(args.input_file)
    try:
        result = _dispatch(args.helper_name, payload)
    except ValueError as exc:
        if args.helper_name == "wf-start-runtime":
            result = {
                "task_classification": None,
                "initial_phase": None,
                "minimum_read_set": [],
                "repo_profile_ref": None,
                "phase_doc_ref": None,
                "created_artifacts": [],
                "reason_code": "START_INPUT_CONTRACT_INVALID",
                "message_summary": str(exc),
            }
        else:
            raise
    if result is not None:
        print(json.dumps(to_jsonable(result), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
