from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.contracts import ErrorCode, JobType, WorkerCapability, WorkerCapabilityManifest
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


def test_a_manifest_from_before_a_field_was_dropped_is_still_readable():
    """A stored row outlives the model that wrote it, and must not take a page down.

    Measured, and it was an outage. One worker row left from before the KOMPAS
    removal still carried `kompas_version: null`. `WorkerCapabilityManifest` forbids
    unknown keys — right **at the door**, where a field this build does not
    understand is a field it should not pretend to have understood — and wrong on the
    way **out of the database**, where the row is older than the model.

    Reading it raised `extra_forbidden` inside the scheduler diagnostics, which the
    customer's own status poll calls. Every order page 500'd the moment it asked how
    its build was going, and in a browser an unhandled 500 carries no CORS header and
    arrives as `Failed to fetch` — which is why it looked like a network problem.

    Migration 0006 rewrote the rows it knew about, and that ordering is the rule this
    repository already states: *deleting a name rows still hold turns a rename into an
    outage.* This is the other half — a reader that survives the row it missed.
    """
    from app.workers.sql_protocol import WorkerRow

    service, worker, _, _ = service_fixture()
    stored = {
        "schema_version": "1.0",
        "worker_version": "0.4.0",
        "cad_ir_versions": ["0.1.0"],
        "capabilities": {"export.step": {"status": "stable", "version": "1.0"}},
        "kompas_version": None,            # the field ENGINE-MIG-008 removed
        "something_from_the_future": 1,    # and one nobody has invented yet
    }
    with service.sessions() as session:
        row = session.get(WorkerRow, str(worker.id))
        row.capability_manifest = stored
        session.commit()

    # The read that used to raise, and the one the status page depends on.
    read = [item for item in service.workers() if item.id == worker.id]
    assert len(read) == 1
    manifest = read[0].capability_manifest
    assert manifest is not None
    assert manifest.capabilities, "the capability list is the part worth reading"
    assert not hasattr(manifest, "kompas_version")

    # And a *worker* sending it is still refused: tolerance belongs on the way out.
    with pytest.raises(Exception):
        WorkerCapabilityManifest(**stored)
