from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.contracts import ErrorCode, JobType, WorkerCapability
from app.database import Base, create_session_factory
from app.workers.protocol import Job, WorkerProtocolError
from app.workers.sql_protocol import SqlWorkerProtocolService


class Clock:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    def __call__(self): return self.now


def service_fixture():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    clock = Clock()
    service = SqlWorkerProtocolService(sessions, "e" * 32, clock)
    worker, credential = service.register(enrollment_token="e" * 32, worker_name=f"worker-{uuid4()}", app_version="0.1")
    service.heartbeat(worker, [WorkerCapability.CAD_BUILD], ["0.1.0"], 1)
    return service, worker, credential, clock


def test_sql_claim_renew_and_duplicate_completion():
    service, worker, credential, _ = service_fixture()
    assert service.authenticate(worker.id, credential).id == worker.id
    job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:sql", {WorkerCapability.CAD_BUILD}, "0.1.0")
    service.enqueue(job)
    claimed = service.claim(worker)
    assert claimed and claimed.attempt == 1
    service.renew_lease(worker, job.id)
    artifacts = [{"type": "STL", "object_key": "result.stl", "sha256": "sha256:file", "size_bytes": 42}]
    assert service.complete_with_artifacts(worker, job.id, job.idempotency_key, artifacts) is False
    assert service.complete_with_artifacts(worker, job.id, job.idempotency_key, artifacts) is True


def test_sql_expired_lease_is_reclaimed_and_wrong_key_rejected():
    service, worker, _, clock = service_fixture()
    job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:retry", {WorkerCapability.CAD_BUILD}, "0.1.0")
    service.enqueue(job)
    service.claim(worker, lease_seconds=1)
    clock.now += timedelta(seconds=2)
    assert service.claim(worker).attempt == 2
    with pytest.raises(WorkerProtocolError) as caught:
        service.complete(worker, job.id, "sha256:wrong")
    assert caught.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
