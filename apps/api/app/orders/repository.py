"""Where an order is kept, in the two places the service is ever configured for.

The same split the worker protocol has had since 0001 and for the same reason: the
isolated API tests need something with no database behind it, and the thing that
actually runs is SQL. Two implementations of one interface, and the tests run over
both — a repository that worked only in memory would be a repository nobody has.

`OrderStateService.transition` stays a pure function of the record and does the
deciding; a repository only reads a row, hands it over, and writes back what comes
out. The SQL one does that under `SELECT … FOR UPDATE`, so two requests arriving
together cannot both read version 3 and both write version 4 — which is the failure
the `version` column existed to prevent and, while orders lived in a dictionary, did
not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.contracts import OrderStatus
from app.orders.models import OrderRow
from app.orders.state_machine import (
    OrderRecord,
    OrderStateChanged,
    OrderStateService,
)


class OrderRepository(Protocol):
    """What `app.main` needs of an order store, and nothing more."""

    def create(
        self,
        order_id: UUID,
        status: OrderStatus,
        *,
        latest_job_id: UUID | None = None,
        source_job_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> OrderRecord: ...

    def get(self, order_id: UUID) -> OrderRecord | None: ...

    def transition(
        self,
        order_id: UUID,
        *,
        target: OrderStatus,
        expected_version: int,
        reason: str | None = None,
    ) -> tuple[OrderRecord, OrderStateChanged]: ...

    def record_round(
        self, order_id: UUID, *, latest_job_id: UUID, clarification_round: int
    ) -> OrderRecord: ...


class InMemoryOrderRepository:
    """For the isolated API tests. Holds records, not rows."""

    def __init__(
        self,
        state_service: OrderStateService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._orders: dict[UUID, OrderRecord] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states = state_service or OrderStateService(self._clock)

    def create(
        self,
        order_id: UUID,
        status: OrderStatus,
        *,
        latest_job_id: UUID | None = None,
        source_job_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> OrderRecord:
        if order_id in self._orders:
            # What the primary key does in SQL, so the two implementations answer a
            # duplicate the same way. Silently overwriting would have made the
            # in-memory one the more forgiving of the pair, which is the wrong way
            # round: the tests run on this and production runs on the other.
            raise IntegrityError("orders", None, Exception(f"order {order_id} already exists"))
        now = self._clock()
        record = OrderRecord(
            id=order_id,
            status=status,
            version=0,
            updated_at=now,
            created_at=now,
            latest_job_id=latest_job_id,
            source_job_id=source_job_id,
            clarification_round=0,
            owner_id=owner_id,
        )
        self._orders[order_id] = record
        return record

    def get(self, order_id: UUID) -> OrderRecord | None:
        return self._orders.get(order_id)

    def transition(
        self,
        order_id: UUID,
        *,
        target: OrderStatus,
        expected_version: int,
        reason: str | None = None,
    ) -> tuple[OrderRecord, OrderStateChanged]:
        current = self._orders[order_id]
        updated, event = self._states.transition(
            current, target=target, expected_version=expected_version, reason=reason
        )
        self._orders[order_id] = updated
        return updated, event

    def record_round(
        self, order_id: UUID, *, latest_job_id: UUID, clarification_round: int
    ) -> OrderRecord:
        current = self._orders[order_id]
        updated = OrderRecord(
            id=current.id,
            status=current.status,
            version=current.version,
            updated_at=self._clock(),
            created_at=current.created_at,
            latest_job_id=latest_job_id,
            source_job_id=current.source_job_id,
            clarification_round=clarification_round,
            owner_id=current.owner_id,
        )
        self._orders[order_id] = updated
        return updated


class SqlOrderRepository:
    """What runs. One row per order, one transaction per call."""

    def __init__(
        self,
        session_factory,
        state_service: OrderStateService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states = state_service or OrderStateService(self._clock)

    def create(
        self,
        order_id: UUID,
        status: OrderStatus,
        *,
        latest_job_id: UUID | None = None,
        source_job_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> OrderRecord:
        now = self._clock()
        with self.sessions.begin() as session:
            row = OrderRow(
                id=str(order_id),
                status=status.value,
                version=0,
                created_at=now,
                updated_at=now,
                latest_job_id=str(latest_job_id) if latest_job_id else None,
                source_job_id=str(source_job_id) if source_job_id else None,
                clarification_round=0,
                owner_id=str(owner_id) if owner_id else None,
            )
            session.add(row)
            session.flush()
            return _record(row)

    def get(self, order_id: UUID) -> OrderRecord | None:
        with self.sessions.begin() as session:
            row = session.scalar(select(OrderRow).where(OrderRow.id == str(order_id)))
            return _record(row) if row is not None else None

    def transition(
        self,
        order_id: UUID,
        *,
        target: OrderStatus,
        expected_version: int,
        reason: str | None = None,
    ) -> tuple[OrderRecord, OrderStateChanged]:
        with self.sessions.begin() as session:
            # Locked for the whole decision, not just the write. Reading the version,
            # deciding on it and then writing without the lock is the interleaving the
            # optimistic check is meant to catch and cannot: both requests see 3.
            row = session.get(OrderRow, str(order_id), with_for_update=True)
            if row is None:
                raise KeyError(order_id)
            updated, event = self._states.transition(
                _record(row), target=target, expected_version=expected_version, reason=reason
            )
            row.status = updated.status.value
            row.version = updated.version
            row.updated_at = updated.updated_at
            return updated, event

    def record_round(
        self, order_id: UUID, *, latest_job_id: UUID, clarification_round: int
    ) -> OrderRecord:
        with self.sessions.begin() as session:
            row = session.get(OrderRow, str(order_id), with_for_update=True)
            if row is None:
                raise KeyError(order_id)
            row.latest_job_id = str(latest_job_id)
            row.clarification_round = clarification_round
            row.updated_at = self._clock()
            session.flush()
            return _record(row)


def _record(row: OrderRow) -> OrderRecord:
    return OrderRecord(
        id=UUID(row.id),
        status=OrderStatus(row.status),
        version=row.version,
        updated_at=row.updated_at,
        created_at=row.created_at,
        latest_job_id=UUID(row.latest_job_id) if row.latest_job_id else None,
        source_job_id=UUID(row.source_job_id) if row.source_job_id else None,
        clarification_round=row.clarification_round,
        owner_id=UUID(row.owner_id) if row.owner_id else None,
    )


__all__ = ["InMemoryOrderRepository", "OrderRepository", "SqlOrderRepository"]
