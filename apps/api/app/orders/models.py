"""The order as a row.

It was two dictionaries in `app.main`:

    order_records: dict[uuid.UUID, OrderRecord] = {}
    drawing_orders: dict[uuid.UUID, dict] = {}

so a restart lost every order, and a second API process never saw the first one's.
Jobs, artifacts and the ledger have been in PostgreSQL since 0001 and 0002; the
order — the thing a customer actually has — was the half that was not.

What the row holds is deliberately narrow. Progress belongs to the job, which
already records its lease, its attempts, its failure code and its `retry_after`,
and copying that here would be a second place for one truth to live. The columns
below are the things **only the order knows**: which job is its latest, which job
holds the drawing every round re-reads, how many rounds have been spent, and the
status somebody *decided* — cancelled, expired, sent to manual review.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
# `orders.owner_id` references `users.id`, and SQLAlchemy resolves that by table
# name at mapper-configuration time — so the module defining `users` has to have
# been imported by then. Imported here rather than left to the caller, because the
# caller that forgets gets `NoReferencedTableError` from somewhere unrelated.
import app.accounts.models  # noqa: F401,E402


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    # Optimistic lock, and the reason the transition endpoint can be called twice
    # without the second call silently winning. It was already in `OrderRecord`;
    # what it lacked was somewhere to be written down.
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The drawing cycle's tracking, which lived in `drawing_orders` and in a JSON
    # file beside the artifacts. `source_job_id` is the job holding the page every
    # later round copies, and it is not `latest_job_id`: a round is a new job with a
    # new directory, and the drawing has to come from somewhere.
    #
    # Nullable because a manual CAD-IR submission has no drawing and no rounds.
    latest_job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(36))
    clarification_round: Mapped[int] = mapped_column(Integer, default=0)
    # Whose order this is (0009). Nullable and staying nullable: every order created
    # before accounts existed has no owner and there is nothing to fill it with, and
    # inventing one would be worse than admitting it. Those orders are readable by an
    # operator and by nobody else, which `app.accounts.principal.may_see_order`
    # decides in one place rather than in every handler.
    #
    # The `ForeignKey` is here as well as in the migration, and it was not at first.
    # Leaving it out looked harmless — SQLite does not enforce foreign keys by
    # default, so the tests would not have noticed either way — and it meant the
    # schema `create_all` builds and the schema `migrate.sh` builds disagreed on a
    # constraint. A test against real PostgreSQL found it by inserting an order
    # owned by an account that does not exist and watching it succeed.
    #
    # `latest_job_id` still has none, and that is a different case rather than an
    # inconsistency: it is also absent from the migration, because a job row can be
    # pruned while its order is kept.
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )


__all__ = ["OrderRow"]
