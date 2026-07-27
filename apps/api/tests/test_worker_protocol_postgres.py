import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.contracts import JobType, WorkerCapability
from app.database import Base
from app.workers.protocol import Job
from app.workers.sql_protocol import SqlWorkerProtocolService


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires opt-in PostgreSQL")
def test_postgres_claim_transaction_round_trip():
    database_url = os.environ["TEST_DATABASE_URL"]
    schema = f"test_{uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        service = SqlWorkerProtocolService(sessions, "e" * 32)
        worker, _ = service.register(enrollment_token="e" * 32, worker_name=f"integration-{uuid4()}", app_version="test")
        service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
        job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, f"sha256:{uuid4()}", {WorkerCapability.KOMPAS_BUILD}, "0.1.0")
        service.enqueue(job)
        claimed = service.claim(worker)
        assert claimed and claimed.id == job.id
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
