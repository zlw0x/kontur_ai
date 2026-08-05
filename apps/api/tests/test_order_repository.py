"""An order survives the process that took it, and two requests cannot both win.

Orders lived in two dictionaries in `app.main` until 0008:

    order_records: dict[uuid.UUID, OrderRecord] = {}
    drawing_orders: dict[uuid.UUID, dict] = {}

so a restart of the API lost every order in flight, and a second API process never
saw the first one's. The drawing cycle survived only because its tracking was also
written to a JSON file beside the artifacts — a database with no transactions and
no constraints, which is what these tests replace.

Both implementations, every case. The in-memory one is what the isolated API tests
run against and the SQL one is what runs; a repository that worked only in memory
would be a repository nobody has.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.contracts import OrderStatus
from app.database import Base, create_session_factory
from app.orders.repository import InMemoryOrderRepository, SqlOrderRepository
from app.orders.state_machine import InvalidStateTransition, OrderVersionConflict
from sqlalchemy.exc import IntegrityError


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def memory_repository():
    return InMemoryOrderRepository(clock=Clock()), None


def sql_repository():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return SqlOrderRepository(sessions, clock=Clock()), sessions


REPOSITORIES = [
    pytest.param(memory_repository, id="memory"),
    pytest.param(sql_repository, id="sql"),
]


@pytest.mark.parametrize("build", REPOSITORIES)
def test_an_order_reads_back_the_way_it_was_written(build):
    repository, _ = build()
    order_id, job_id = uuid4(), uuid4()

    repository.create(
        order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER,
        latest_job_id=job_id, source_job_id=job_id,
    )

    order = repository.get(order_id)
    assert (order.id, order.status, order.version) == (
        order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER, 0,
    )
    assert (order.latest_job_id, order.source_job_id, order.clarification_round) == (
        job_id, job_id, 0,
    )


@pytest.mark.parametrize("build", REPOSITORIES)
def test_an_order_nobody_created_is_absent_rather_than_an_error(build):
    repository, _ = build()

    assert repository.get(uuid4()) is None


def test_an_order_outlives_the_repository_that_wrote_it():
    """The whole point, and the one case the in-memory implementation cannot show.

    A second `SqlOrderRepository` over the same database is what a restarted API is,
    and what a second API process is. Against a dictionary this assertion is not
    merely false — it cannot be written.
    """
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    order_id, job_id = uuid4(), uuid4()

    SqlOrderRepository(sessions).create(
        order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER,
        latest_job_id=job_id, source_job_id=job_id,
    )

    after_restart = SqlOrderRepository(sessions).get(order_id)
    assert after_restart is not None
    assert after_restart.latest_job_id == job_id


@pytest.mark.parametrize("build", REPOSITORIES)
def test_a_transition_is_recorded_and_bumps_the_version(build):
    repository, _ = build()
    order_id = uuid4()
    repository.create(order_id, OrderStatus.DRAFT)

    updated, event = repository.transition(
        order_id, target=OrderStatus.UPLOADED, expected_version=0, reason="test"
    )

    assert (updated.status, updated.version) == (OrderStatus.UPLOADED, 1)
    assert (event.previous_status, event.current_status) == (OrderStatus.DRAFT, OrderStatus.UPLOADED)
    assert repository.get(order_id).status == OrderStatus.UPLOADED


@pytest.mark.parametrize("build", REPOSITORIES)
def test_the_second_writer_of_a_version_loses(build):
    """What `version` was for and, while orders lived in a dictionary, could not do.

    Two requests read version 0 and both decide. Without the check the second one
    silently overwrites the first, and the order ends in a state nobody asked for
    by a route the transition table never permitted.
    """
    repository, _ = build()
    order_id = uuid4()
    repository.create(order_id, OrderStatus.DRAFT)
    repository.transition(order_id, target=OrderStatus.UPLOADED, expected_version=0)

    with pytest.raises(OrderVersionConflict):
        repository.transition(order_id, target=OrderStatus.CANCELLED, expected_version=0)

    assert repository.get(order_id).status == OrderStatus.UPLOADED


@pytest.mark.parametrize("build", REPOSITORIES)
def test_a_transition_the_table_forbids_is_refused_and_changes_nothing(build):
    repository, _ = build()
    order_id = uuid4()
    repository.create(order_id, OrderStatus.DRAFT)

    with pytest.raises(InvalidStateTransition):
        repository.transition(order_id, target=OrderStatus.READY, expected_version=0)

    order = repository.get(order_id)
    assert (order.status, order.version) == (OrderStatus.DRAFT, 0)


@pytest.mark.parametrize("build", REPOSITORIES)
def test_a_round_moves_the_latest_job_and_leaves_the_source_alone(build):
    """A clarification round is a new job with a new directory. The drawing it works
    from comes from the *source* job, so a round that moved both would leave later
    rounds reading a page that is no longer there."""
    repository, _ = build()
    order_id, first, second = uuid4(), uuid4(), uuid4()
    repository.create(
        order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER,
        latest_job_id=first, source_job_id=first,
    )

    updated = repository.record_round(order_id, latest_job_id=second, clarification_round=1)

    assert (updated.latest_job_id, updated.source_job_id) == (second, first)
    assert updated.clarification_round == 1
    assert repository.get(order_id).latest_job_id == second


@pytest.mark.parametrize("build", REPOSITORIES)
def test_a_round_does_not_spend_a_version(build):
    """The version is the optimistic lock on somebody's *decision*. A round is the
    pipeline moving, and letting it bump the version would make an operator's
    in-flight transition fail for a reason that has nothing to do with them."""
    repository, _ = build()
    order_id = uuid4()
    repository.create(order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER, latest_job_id=uuid4())

    repository.record_round(order_id, latest_job_id=uuid4(), clarification_round=1)

    assert repository.get(order_id).version == 0


@pytest.mark.parametrize("build", REPOSITORIES)
def test_creating_the_same_order_twice_is_refused_by_both(build):
    """The two implementations answer a duplicate the same way.

    SQL has the primary key; the in-memory one raises the same error rather than
    overwriting, because the forgiving half of the pair must not be the one the
    tests run on. `_drawing_order` depends on this: two polls of the same pre-0008
    order arriving together must not produce two rows or a 500.
    """
    repository, _ = build()
    order_id = uuid4()
    repository.create(order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER, latest_job_id=uuid4())

    with pytest.raises(IntegrityError):
        repository.create(order_id, OrderStatus.DRAFT)
