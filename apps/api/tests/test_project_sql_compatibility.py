from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.contracts import OrderStatus
from app.database import Base, create_session_factory
from app.orders.repository import SqlOrderRepository
from app.workers.capabilities import is_online


def test_sqlite_worker_time_is_treated_as_utc():
    now = datetime.now(UTC)
    assert is_online(now.replace(tzinfo=None), now, timedelta(seconds=60))
    assert not is_online(
        (now - timedelta(minutes=2)).replace(tzinfo=None), now, timedelta(seconds=60)
    )


def test_sql_quota_excludes_completed_jobs_without_forgetting_daily_total():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlOrderRepository(sessions)
    owner_id, completed_job, pending_job = uuid4(), uuid4(), uuid4()
    for job_id in (completed_job, pending_job):
        repository.create(
            uuid4(),
            OrderStatus.WAITING_FOR_LOCAL_WORKER,
            owner_id=owner_id,
            latest_job_id=job_id,
        )
    started, in_flight = repository.quota_counts(
        owner_id, active_job=lambda job_id: job_id != completed_job
    )
    assert len(started) == 2
    assert in_flight == 1
