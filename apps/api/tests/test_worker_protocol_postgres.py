import contextlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.contracts import JobType, OrderStatus, WorkerCapability
from app.database import Base
import app.orders.models  # noqa: F401  (registers `orders` before create_all)
from app.orders.repository import SqlOrderRepository
from app.orders.state_machine import OrderVersionConflict
from app.workers.protocol import Job
from app.workers.sql_protocol import SqlWorkerProtocolService


@contextlib.contextmanager
def disposable_schema():
    """A schema of its own per test, dropped afterwards.

    Everything else in the suite runs on SQLite, which is close enough for the ORM
    and not close enough for `SELECT … FOR UPDATE`: SQLite parses the clause and
    does nothing with it, so a lock these tests depend on is not exercised there.
    """
    database_url = os.environ["TEST_DATABASE_URL"]
    schema = f"test_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires opt-in PostgreSQL")
def test_postgres_claim_transaction_round_trip():
    with disposable_schema() as sessions:
        service = SqlWorkerProtocolService(sessions, "e" * 32)
        worker, _ = service.register(enrollment_token="e" * 32, worker_name=f"integration-{uuid4()}", app_version="test")
        service.heartbeat(worker, [WorkerCapability.CAD_BUILD], ["0.1.0"], 1)
        job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, f"sha256:{uuid4()}", {WorkerCapability.CAD_BUILD}, "0.1.0")
        service.enqueue(job)
        claimed = service.claim(worker)
        assert claimed and claimed.id == job.id


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires opt-in PostgreSQL")
def test_postgres_order_round_trip_and_version_conflict():
    """The orders table on the database it actually runs on.

    The rest of the order tests use SQLite, where `with_for_update` is accepted and
    ignored. Here the row is really locked, so the second writer of a version is
    refused by the check it was written for rather than by an accident of ordering.
    """
    with disposable_schema() as sessions:
        order_id, job_id = uuid4(), uuid4()
        repository = SqlOrderRepository(sessions)
        repository.create(
            order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER,
            latest_job_id=job_id, source_job_id=job_id,
        )

        # A second repository over the same database: a restarted API, or the other
        # process behind the same load balancer.
        elsewhere = SqlOrderRepository(sessions)
        assert elsewhere.get(order_id).latest_job_id == job_id

        elsewhere.transition(order_id, target=OrderStatus.CANCELLED, expected_version=0)
        with pytest.raises(OrderVersionConflict):
            repository.transition(order_id, target=OrderStatus.EXPIRED, expected_version=0)
        assert repository.get(order_id).status == OrderStatus.CANCELLED


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires opt-in PostgreSQL")
def test_postgres_a_decision_and_its_audit_row_are_one_transaction():
    """The property the queue rests on, on the database that can actually enforce it.

    An order that became `READY` with no row saying who approved it is
    indistinguishable from one the pipeline released by itself — which is the exact
    thing `automatic_acceptance = False` exists to prevent. SQLite would let a
    two-call version pass; here the row and the status change are one transaction,
    and a refused decision leaves neither.
    """
    import app.accounts.models  # noqa: F401
    import app.orders.review  # noqa: F401

    from app.accounts import Role, SqlAccountRepository
    from app.accounts.service import AccountService
    from app.orders.review import ReviewDecision
    from app.orders.state_machine import OrderVersionConflict

    with disposable_schema() as sessions:
        accounts = AccountService(SqlAccountRepository(sessions))
        operator, _ = accounts.register("op@example.com", "correct horse battery staple", Role.OPERATOR)
        orders = SqlOrderRepository(sessions)
        order_id = uuid4()
        orders.create(order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER)
        held, _ = orders.transition(
            order_id, target=OrderStatus.MANUAL_REVIEW, expected_version=0
        )

        # A decision against a version nobody is at leaves nothing behind.
        with pytest.raises(OrderVersionConflict):
            orders.review(
                order_id, decision=ReviewDecision.APPROVE, expected_version=0,
                reviewer_id=operator.id, reason=None,
            )
        assert orders.reviews_of(order_id) == []
        assert orders.get(order_id).status == OrderStatus.MANUAL_REVIEW

        updated, audit = orders.review(
            order_id,
            decision=ReviewDecision.APPROVE,
            expected_version=held.version,
            reviewer_id=operator.id,
            reason=None,
        )
        assert updated.status == OrderStatus.READY
        # Read back through a second repository, which is what a second API process
        # behind the same load balancer is.
        trail = SqlOrderRepository(sessions).reviews_of(order_id)
        assert [row.id for row in trail] == [audit.id]
        assert trail[0].reviewer_id == operator.id
        assert trail[0].order_version_before == held.version

        queued, total = orders.waiting_for_review(limit=10, offset=0)
        assert queued == [] and total == 0


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires opt-in PostgreSQL")
def test_postgres_accounts_sessions_and_ownership():
    """Accounts on the database that actually runs, including the two constraints.

    SQLite enforces UNIQUE, so the duplicate-address check would pass there too.
    What it does *not* enforce by default is the foreign key, and `orders.owner_id`
    references `users(id)` — so an order pointing at an account that does not exist
    is a thing only this test can catch.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.exc import IntegrityError

    import app.accounts.models  # noqa: F401  (registers users and sessions)
    from app.accounts import Role, SqlAccountRepository
    from app.accounts.service import AccountService
    from app.accounts.principal import Principal, may_see_order

    with disposable_schema() as sessions:
        accounts = AccountService(SqlAccountRepository(sessions))
        ivan, _ = accounts.register("Ivan@Example.com", "correct horse battery staple")
        assert ivan.role is Role.CUSTOMER

        # Case-folded uniqueness, on the real UNIQUE constraint.
        with pytest.raises(Exception) as clash:
            accounts.register("ivan@example.com", "another perfectly fine password")
        assert clash.type.__name__ in {"EmailAlreadyRegistered", "IntegrityError"}

        issued = accounts.issue(ivan)
        # A second service over the same database: a restarted API, or the other
        # process behind the same load balancer. Before 0009 there was no second
        # process that could resolve a session at all, because there were none.
        elsewhere = AccountService(SqlAccountRepository(sessions))
        resolved = elsewhere.resolve(issued.token)
        assert resolved is not None and resolved[0].user_id == ivan.id

        elsewhere.sign_out(issued.session.id)
        assert accounts.resolve(issued.token) is None

        orders = SqlOrderRepository(sessions)
        order_id = uuid4()
        orders.create(order_id, OrderStatus.WAITING_FOR_LOCAL_WORKER, owner_id=ivan.id)
        assert SqlOrderRepository(sessions).get(order_id).owner_id == ivan.id
        assert may_see_order(Principal(role=Role.CUSTOMER, user_id=ivan.id), ivan.id)
        assert not may_see_order(Principal(role=Role.CUSTOMER, user_id=uuid4()), ivan.id)

        # The foreign key, which is the half SQLite does not check.
        with pytest.raises(IntegrityError):
            orders.create(uuid4(), OrderStatus.WAITING_FOR_LOCAL_WORKER, owner_id=uuid4())

        # And an expiry stored as `timestamptz` comes back aware, so comparing it
        # against `now` is a comparison and not a `TypeError`.
        stale = accounts.repository.create_session(
            user_id=ivan.id,
            token_sha256="0" * 64,
            csrf_sha256="0" * 64,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert stale.expires_at.tzinfo is not None
        assert accounts.resolve("whatever that token was") is None
