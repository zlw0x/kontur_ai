"""The only allowed order state transitions and optimistic-locking service."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Final
from uuid import UUID

from app.contracts import ErrorCode, OrderStatus


ALLOWED_TRANSITIONS: Final[dict[OrderStatus, frozenset[OrderStatus]]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.UPLOADED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.UPLOADED: frozenset({OrderStatus.INPUT_VALIDATION, OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.INPUT_VALIDATION: frozenset({OrderStatus.WAITING_FOR_LOCAL_WORKER, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    OrderStatus.WAITING_FOR_LOCAL_WORKER: frozenset({OrderStatus.DRAWING_ANALYSIS, OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.DRAWING_ANALYSIS: frozenset({OrderStatus.WAITING_FOR_USER_ANSWERS, OrderStatus.PLAN_READY, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED}),
    OrderStatus.WAITING_FOR_USER_ANSWERS: frozenset({OrderStatus.DRAWING_ANALYSIS, OrderStatus.MANUAL_REVIEW, OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.PLAN_READY: frozenset({OrderStatus.WAITING_FOR_PLAN_APPROVAL, OrderStatus.MANUAL_REVIEW}),
    OrderStatus.WAITING_FOR_PLAN_APPROVAL: frozenset({OrderStatus.QUEUED_FOR_CAD, OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.QUEUED_FOR_CAD: frozenset({OrderStatus.CAD_BUILDING, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    OrderStatus.CAD_BUILDING: frozenset({OrderStatus.CAD_VALIDATION, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED}),
    OrderStatus.CAD_VALIDATION: frozenset({OrderStatus.READY, OrderStatus.AUTO_REPAIR, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED}),
    OrderStatus.AUTO_REPAIR: frozenset({OrderStatus.CAD_BUILDING, OrderStatus.MANUAL_REVIEW, OrderStatus.FAILED}),
    OrderStatus.MANUAL_REVIEW: frozenset({OrderStatus.DRAWING_ANALYSIS, OrderStatus.PLAN_READY, OrderStatus.QUEUED_FOR_CAD, OrderStatus.READY, OrderStatus.FAILED, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset(),
    OrderStatus.FAILED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.PAUSED: frozenset(),
}

#: Statuses the API reads off the job rather than storing on the order.
#:
#: `PAUSED` is one because a pause is a fact about a job — the worker set
#: `retry_after` on it and the reaper will return it — and copying that onto the
#: order would be a second place for one truth to live, which is the arrangement
#: `drawing-tracking.json` and `order_records` were already in. Nothing transitions
#: into or out of it: the reaper moves the *job*, and the derived answer follows on
#: the next read. Its empty transition set therefore means "not stored", not
#: "terminal", and `is_decided` is what tells the two apart.
DERIVED_FROM_THE_JOB: Final[frozenset[OrderStatus]] = frozenset({OrderStatus.PAUSED})

#: Statuses that are somebody's decision rather than an observation of a job, and
#: which therefore outrank whatever the pipeline is doing. An operator cancelling an
#: order does not stop the worker mid-build; the build finishes and its artifacts are
#: stored, and the customer's order is still cancelled.
DECIDED: Final[frozenset[OrderStatus]] = frozenset({
    OrderStatus.CANCELLED,
    OrderStatus.EXPIRED,
    OrderStatus.MANUAL_REVIEW,
})


def is_decided(status: OrderStatus) -> bool:
    return status in DECIDED


class OrderTransitionError(Exception):
    code: ErrorCode


class InvalidStateTransition(OrderTransitionError):
    code = ErrorCode.INVALID_STATE_TRANSITION


class OrderVersionConflict(OrderTransitionError):
    code = ErrorCode.ORDER_VERSION_CONFLICT


@dataclass(frozen=True)
class OrderRecord:
    id: UUID
    status: OrderStatus
    version: int
    updated_at: datetime
    # What the drawing cycle needs to find its way back: the job answering now, the
    # job holding the page every round copies, and how many rounds have been spent.
    # Defaulted because a manual CAD-IR submission has none of them, and because
    # `transition` is a pure function over the first four fields and should not have
    # to be handed the rest to say whether a status change is legal.
    latest_job_id: UUID | None = None
    source_job_id: UUID | None = None
    clarification_round: int = 0
    created_at: datetime | None = None


@dataclass(frozen=True)
class OrderStateChanged:
    order_id: UUID
    previous_status: OrderStatus
    current_status: OrderStatus
    previous_version: int
    current_version: int
    occurred_at: datetime
    reason: str | None


class OrderStateService:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def transition(self, order: OrderRecord, *, target: OrderStatus, expected_version: int, reason: str | None = None) -> tuple[OrderRecord, OrderStateChanged]:
        if order.version != expected_version:
            raise OrderVersionConflict(f"order {order.id} is at version {order.version}, not {expected_version}")
        if target not in ALLOWED_TRANSITIONS[order.status]:
            raise InvalidStateTransition(f"{order.status} cannot transition to {target}")

        occurred_at = self._clock()
        updated = replace(order, status=target, version=order.version + 1, updated_at=occurred_at)
        event = OrderStateChanged(order.id, order.status, target, order.version, updated.version, occurred_at, reason)
        return updated, event
