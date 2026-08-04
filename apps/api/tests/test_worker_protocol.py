from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.contracts import ErrorCode, JobStatus, JobType, WorkerCapability
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolError, WorkerProtocolService


class Clock:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    def __call__(self): return self.now


def ready_service():
    clock, repo = Clock(), InMemoryWorkerRepository()
    service = WorkerProtocolService(repo, "e" * 32, clock)
    worker, credential = service.register(enrollment_token="e" * 32, worker_name="test", app_version="0.1")
    service.heartbeat(worker, [WorkerCapability.CAD_BUILD], ["0.1.0"], 1)
    return service, repo, worker, credential, clock


def test_claim_lease_renew_and_idempotent_completion():
    service, repo, worker, _, _ = ready_service()
    job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:key", {WorkerCapability.CAD_BUILD}, "0.1.0")
    repo.jobs[job.id] = job
    assert service.claim(worker) is job and job.attempt == 1
    assert service.renew_lease(worker, job.id).status == JobStatus.LEASED
    assert service.complete(worker, job.id, "sha256:key") is False
    assert service.complete(worker, job.id, "sha256:key") is True


def test_invalid_credential_and_capability_mismatch_are_rejected():
    service, repo, worker, _, _ = ready_service()
    with pytest.raises(WorkerProtocolError): service.authenticate(worker.id, "wrong")
    repo.jobs[uuid4()] = Job(uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:key", {WorkerCapability.AI_DRAWING}, "0.1.0")
    assert service.claim(worker) is None


def test_expired_lease_can_be_reclaimed_but_old_worker_cannot_complete():
    service, repo, worker, _, clock = ready_service()
    job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:key", {WorkerCapability.CAD_BUILD}, "0.1.0")
    repo.jobs[job.id] = job
    service.claim(worker, lease_seconds=1)
    clock.now += timedelta(seconds=2)
    assert service.claim(worker) is job and job.attempt == 2
    with pytest.raises(WorkerProtocolError) as error: service.complete(worker, job.id, "wrong")
    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
