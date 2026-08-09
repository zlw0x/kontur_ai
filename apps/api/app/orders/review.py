"""What an operator decided about an order, and why.

A table and not a log line. A log rotates, is not queryable, and cannot be joined
to the order it is about — and the question this has to answer months later is
"who released this part, and what did they say about it", which is exactly the
question a rotated log cannot answer.

Every row is written **in the same transaction as the status change it explains**.
That is the whole point: an order that became `READY` with no row saying who
approved it would be indistinguishable from one the pipeline released on its own,
which is the thing `automatic_acceptance = False` exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import OrderStatus
from app.database import Base
# `order_reviews` references both, and SQLAlchemy resolves a `ForeignKey` by table
# name when mappers are configured — so the modules defining them have to have been
# imported by then.
import app.accounts.models  # noqa: F401,E402
import app.orders.models  # noqa: F401,E402


class ReviewDecision(StrEnum):
    """Three, and each one lands the order somewhere different.

    `REQUEST_CHANGES` is the one that is not an ending: it sends the order back
    through the reading stage with the operator's note attached, so the next
    document is written by somebody who has been told what was wrong with the last
    one. Without the note it would re-run the same inputs and produce the same
    answer, which is a button that appears to do something.
    """

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


#: Where each decision leaves the order.
#:
#: A mapping rather than three endpoints, so that "which statuses can an operator
#: put an order into" is one readable list instead of something to be reconstructed
#: from handlers. The state machine still has the final say — an approval of an
#: order that was cancelled while it sat in the queue is refused there, not here.
DECISION_TARGET: dict[ReviewDecision, OrderStatus] = {
    ReviewDecision.APPROVE: OrderStatus.READY,
    ReviewDecision.REJECT: OrderStatus.FAILED,
    ReviewDecision.REQUEST_CHANGES: OrderStatus.DRAWING_ANALYSIS,
}


class OrderReviewRow(Base):
    __tablename__ = "order_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    #: Null for the manual operator key, which authenticates as staff and is not a
    #: person. Recording it as some invented user would make the audit trail say
    #: somebody approved this when nobody did.
    reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(24))
    #: Free text from the operator. Required for a rejection and for a request for
    #: changes, because "no" with no reason is not a decision anybody can act on.
    reason: Mapped[str | None] = mapped_column(Text)
    #: The version the operator was looking at. Kept even though the transition
    #: already checked it: it is what makes the row a record of *what was decided
    #: about*, rather than only of what happened afterwards.
    order_version_before: Mapped[int] = mapped_column(Integer)
    order_status_after: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class OrderReview:
    id: UUID
    order_id: UUID
    reviewer_id: UUID | None
    decision: ReviewDecision
    reason: str | None
    order_version_before: int
    order_status_after: OrderStatus
    created_at: datetime


def review_record(row: OrderReviewRow) -> OrderReview:
    return OrderReview(
        id=UUID(row.id),
        order_id=UUID(row.order_id),
        reviewer_id=UUID(row.reviewer_id) if row.reviewer_id else None,
        decision=ReviewDecision(row.decision),
        reason=row.reason,
        order_version_before=row.order_version_before,
        order_status_after=OrderStatus(row.order_status_after),
        created_at=row.created_at,
    )


__all__ = [
    "DECISION_TARGET",
    "OrderReview",
    "OrderReviewRow",
    "ReviewDecision",
    "review_record",
]
