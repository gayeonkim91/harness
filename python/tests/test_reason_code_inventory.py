from __future__ import annotations

import re
from pathlib import Path


REASON_CODE_PATTERN = re.compile(r"\b(?:START|DOCS_ONLY|CHECKPOINT|NEXT|APPLY|VERIFY|REVIEW|STATE|PLAN)_[A-Z0-9_]+\b")
NON_REASON_SYMBOLS = {
    "CHECKPOINT_PHASES",
    "DOCS_ONLY_SCHEMA_VERSION",
    "NEXT_PENDING_AFTER_CURRENT",
    "PLAN_TO_IMPLEMENTATION",
    "PLAN_TEMPLATE",
    "STATE_FIELD",
}


def test_runtime_reason_codes_are_documented_in_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source_root = repo_root / "python" / "src"
    contract = (repo_root / "contracts" / "shared_implementation.md").read_text(encoding="utf-8")

    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    runtime_codes = set(REASON_CODE_PATTERN.findall(source_text)) - NON_REASON_SYMBOLS
    documented_codes = set(REASON_CODE_PATTERN.findall(contract))

    assert "DOCS_ONLY_STATE_INVALID" in runtime_codes
    assert sorted(runtime_codes - documented_codes) == []
