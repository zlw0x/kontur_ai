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
