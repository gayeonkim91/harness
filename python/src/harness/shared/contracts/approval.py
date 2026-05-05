"""Approval point contracts for shared workflow transitions."""

from __future__ import annotations

from enum import Enum


class ApprovalPoint(str, Enum):
    """Official approval points in the shared workflow."""

    PRE_PLAN_TO_PLAN = "pre_plan_to_plan"
    PLAN_TO_IMPLEMENTATION = "plan_to_implementation"
    CLOSURE = "closure"


APPROVAL_POINT_NUMBERS: dict[ApprovalPoint, int] = {
    ApprovalPoint.PRE_PLAN_TO_PLAN: 1,
    ApprovalPoint.PLAN_TO_IMPLEMENTATION: 2,
    ApprovalPoint.CLOSURE: 3,
}


def approval_point_number(point: ApprovalPoint) -> int:
    """Return the durable numeric grant marker for an approval point."""

    return APPROVAL_POINT_NUMBERS[point]


def grant_approval(existing: list[int], point: ApprovalPoint) -> list[int]:
    """Return approval grants as a cumulative prefix through ``point``.

    This always backfills missing earlier approval numbers, preserving the
    invariant that grant history is cumulative even for cut-over-era tasks.
    """

    number = approval_point_number(point)
    grants = {int(item) for item in existing}
    grants.update(range(1, number + 1))
    return sorted(grants)
