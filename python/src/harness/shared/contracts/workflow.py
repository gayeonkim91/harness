"""Workflow classification contracts for shared entry routing."""

from __future__ import annotations

from enum import Enum


class WorkflowKind(str, Enum):
    """Top-level workflow kind resolved before creating task artifacts."""

    RUNBOOK = "runbook"
    DOCS_ONLY = "docs_only"
    DISCUSSION_ONLY = "discussion_only"
    UNKNOWN = "unknown"
