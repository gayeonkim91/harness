"""Verification gate recommendation helpers.

The selector is intentionally conservative: it recommends check-only gates and
never suggests formatter/apply commands that would mutate the workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable


JAVA_SPRING = "java_spring"
FRONTEND = "frontend"
MIXED = "mixed"
DOCS_ONLY = "docs_only"

AUTOFIX_COMMANDS = ("spotlessApply", "pnpm format", "npm run format", "yarn format")
# Detection uses the regex inventory below; this tuple is only a compact label list.
_AUTOFIX_COMMAND_PATTERNS = (
    re.compile(r"(^|\s)spotlessApply(\s|$)"),
    re.compile(r"(^|\s)(?::[^\s:]+)*:spotlessApply(\s|$)"),
    re.compile(r"(^|\s)pnpm\s+format(\s|$)"),
    re.compile(r"(^|\s)pnpm\s+run\s+format(\s|$)"),
    re.compile(
        r"(^|\s)pnpm(?:\s+(?:(?:--filter|-F|--dir|-C)(?:=|\s+)\S+|(?:-r|--recursive|-w|--workspace-root)))*\s+(?:run\s+)?format(\s|$)"
    ),
    re.compile(r"(^|\s)npm\s+run\s+format(\s|$)"),
    re.compile(
        r"(^|\s)npm(?:\s+(?:(?:--prefix|--workspace|-w)(?:=|\s+)\S+))*\s+run\s+format(\s|$)"
    ),
    re.compile(r"(^|\s)yarn\s+format(\s|$)"),
    re.compile(r"(^|\s)yarn\s+workspace\s+\S+\s+format(\s|$)"),
)

_DOC_EXTENSIONS = {".adoc", ".md", ".mdx", ".rst"}
_JAVA_EXTENSIONS = {".java", ".kt", ".kts", ".gradle", ".groovy"}
_FRONTEND_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".css", ".scss"}
_DOC_CONTEXT_DIRS = {"doc", "docs", "documentation"}
_FRONTEND_CONTEXT_DIRS = {"frontend", "web", "ui"}
_FRONTEND_SOURCE_DIRS = {"app", "components", "pages", "routes"}
_JAVA_FILENAMES = {
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
    "gradlew.bat",
    "pom.xml",
}
_FRONTEND_FILENAMES = {
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
}


@dataclass(frozen=True, slots=True)
class GateRecommendation:
    """One check-only verification gate recommendation."""

    gate_key: str
    label: str
    command: str
    working_directory: str
    reason: str
    evidence: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class VerificationGateSelection:
    """Selected gates for a changed path set."""

    impact_area: str
    changed_paths: tuple[str, ...]
    recommended_gates: tuple[GateRecommendation, ...] = field(default_factory=tuple)
    manual_checks: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-friendly representation for adapters/skills."""

        return {
            "impact_area": self.impact_area,
            "changed_paths": list(self.changed_paths),
            "recommended_gates": [
                {
                    "gate_key": gate.gate_key,
                    "label": gate.label,
                    "command": gate.command,
                    "working_directory": gate.working_directory,
                    "reason": gate.reason,
                    "evidence": gate.evidence,
                    "required": gate.required,
                }
                for gate in self.recommended_gates
            ],
            "manual_checks": list(self.manual_checks),
            "warnings": list(self.warnings),
        }


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip()


def _path_parts(path: str) -> set[str]:
    return {part.lower() for part in path.split("/") if part}


def _looks_like_source_resource(path: str) -> bool:
    normalized = f"/{path.strip('/')}"
    return any(
        marker in normalized
        for marker in (
            "/src/main/resources/",
            "/src/test/resources/",
            "/test/resources/",
            "/tests/resources/",
        )
    )


def _looks_like_doc(path: str) -> bool:
    normalized = path.lower()
    parts = _path_parts(normalized)
    suffix = Path(normalized).suffix
    stem = Path(normalized).stem
    if _looks_like_source_resource(normalized):
        return False
    if parts & _DOC_CONTEXT_DIRS:
        return suffix in _DOC_EXTENSIONS or suffix in {"", ".txt"}
    if suffix in _DOC_EXTENSIONS:
        return True
    if stem in {"readme", "changelog"} and suffix in {"", ".txt"}:
        return True
    return False


def _looks_like_java_spring(path: str) -> bool:
    normalized = path.lower()
    name = Path(normalized).name
    parts = _path_parts(normalized)
    return (
        Path(normalized).suffix in _JAVA_EXTENSIONS
        or name in _JAVA_FILENAMES
        or "gradle" in parts
        or "src/main/java" in normalized
        or "src/test/java" in normalized
        or "src/main/kotlin" in normalized
        or "src/test/kotlin" in normalized
    )


def _looks_like_frontend(path: str) -> bool:
    normalized = path.lower()
    name = Path(normalized).name
    parts = _path_parts(normalized)
    suffix = Path(normalized).suffix
    return (
        suffix in _FRONTEND_EXTENSIONS
        or name in _FRONTEND_FILENAMES
        or (
            suffix == ".mdx"
            and bool(parts & _FRONTEND_SOURCE_DIRS)
        )
        or (
            suffix not in _DOC_EXTENSIONS
            and bool(parts & _FRONTEND_CONTEXT_DIRS)
        )
    )


def classify_verification_impact(changed_paths: Iterable[str | Path]) -> str:
    """Classify changed paths into the PR8 verification impact buckets."""

    normalized_paths = tuple(path for path in (_normalize_path(item) for item in changed_paths) if path)
    if not normalized_paths:
        return MIXED

    has_java = any(_looks_like_java_spring(path) for path in normalized_paths)
    has_frontend = any(_looks_like_frontend(path) for path in normalized_paths)

    if has_java and has_frontend:
        return MIXED
    if has_java:
        return JAVA_SPRING
    if has_frontend:
        return FRONTEND
    if all(_looks_like_doc(path) for path in normalized_paths):
        return DOCS_ONLY
    return MIXED


def _java_gates() -> tuple[GateRecommendation, ...]:
    return (
        GateRecommendation(
            gate_key="gradle-spotless-check",
            label="Gradle Spotless check",
            command="./gradlew spotlessCheck",
            working_directory="<repo root>",
            reason="Java/Spring formatting drift must be detected without running spotlessApply.",
            evidence="Gradle console summary plus build/reports/spotless output when present.",
        ),
        GateRecommendation(
            gate_key="gradle-checkstyle",
            label="Gradle Checkstyle",
            command="./gradlew checkstyleMain checkstyleTest",
            working_directory="<repo root>",
            reason="Style/static-analysis failures should be separated from test failures.",
            evidence="build/reports/checkstyle report path and summarized violation count.",
        ),
        GateRecommendation(
            gate_key="gradle-test",
            label="Gradle tests",
            command="./gradlew test",
            working_directory="<repo root>",
            reason="Java/Spring behavior changes need the narrowest relevant regression test gate.",
            evidence="build/test-results and build/reports/tests summary.",
        ),
    )


def _frontend_gates() -> tuple[GateRecommendation, ...]:
    return (
        GateRecommendation(
            gate_key="frontend-format-check",
            label="Frontend format check",
            command="pnpm format:check",
            working_directory="<frontend root>",
            reason="Frontend formatting drift must be detected without running pnpm format.",
            evidence="Command summary or formatter report.",
        ),
        GateRecommendation(
            gate_key="frontend-lint",
            label="Frontend lint",
            command="pnpm lint",
            working_directory="<frontend root>",
            reason="Frontend code changes need static-analysis coverage.",
            evidence="Lint summary and report path when present.",
        ),
        GateRecommendation(
            gate_key="frontend-test",
            label="Frontend tests",
            command="pnpm test",
            working_directory="<frontend root>",
            reason="Frontend behavior changes need the narrowest relevant test gate.",
            evidence="Test runner summary and report path when present.",
        ),
        GateRecommendation(
            gate_key="frontend-build",
            label="Frontend build",
            command="pnpm build",
            working_directory="<frontend root>",
            reason="Build/type integration must be checked for frontend changes.",
            evidence="Build command summary and artifact/report path when present.",
        ),
    )


def _docs_manual_checks() -> tuple[str, ...]:
    return (
        "Confirm changed docs match the task contract and do not contradict plan.md.",
        "Check links, anchors, and referenced artifact paths touched by the change.",
    )


def select_verification_gates(changed_paths: Iterable[str | Path]) -> VerificationGateSelection:
    """Recommend verification gates for a set of changed paths.

    Returned working directories are placeholders; callers must resolve them
    before turning recommendations into persisted verification items.
    """

    normalized_paths = tuple(path for path in (_normalize_path(item) for item in changed_paths) if path)
    impact = classify_verification_impact(normalized_paths)
    warnings = [
        "Run check-only format gates. Do not auto-run spotlessApply or pnpm format from /wf-verify.",
    ]

    if impact == JAVA_SPRING:
        gates = _java_gates()
        manual_checks = ()
    elif impact == FRONTEND:
        gates = _frontend_gates()
        manual_checks = ()
    elif impact == DOCS_ONLY:
        gates = ()
        manual_checks = _docs_manual_checks()
    else:
        gates = _java_gates() + _frontend_gates()
        manual_checks = (
            "Verify cross-boundary behavior where Java/Spring and frontend changes meet.",
        )

    if not normalized_paths:
        warnings.append("No changed paths were supplied; mixed verification gates are a conservative fallback.")
    if impact != DOCS_ONLY:
        warnings.append("Resolve placeholder working_directory values before persisting verification items.")

    return VerificationGateSelection(
        impact_area=impact,
        changed_paths=normalized_paths,
        recommended_gates=gates,
        manual_checks=manual_checks,
        warnings=tuple(warnings),
    )


def is_autofix_command(command: str) -> bool:
    """Return True for formatter/apply commands that /wf-verify should not run automatically."""

    normalized = " ".join(command.strip().split())
    return any(pattern.search(normalized) for pattern in _AUTOFIX_COMMAND_PATTERNS)
