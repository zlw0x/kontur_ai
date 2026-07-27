"""The capability gate decides scheduling, so its failure mode matters more
than its success: a worker that cannot build an operation must be passed over
quietly and left for a capable one, never handed the job."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.contracts import (
    CapabilityStatus,
    JobType,
    WorkerCapability,
    WorkerCapabilityManifest,
)
from app.database import Base, create_session_factory
from app.main import app
from app.workers.capabilities import (
    MVP_CAPABILITIES,
    SOLID_RECTANGULAR_PRISM,
    required_capability_keys,
    unmet_capabilities,
)
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService
from app.workers.sql_protocol import SqlWorkerProtocolService

ENROLLMENT = "local-development-enrollment-token-change-me"


def manifest(statuses: dict[str, CapabilityStatus] | None = None) -> WorkerCapabilityManifest:
    return WorkerCapabilityManifest(
        worker_version="0.4.0",
        kompas_version="22.0",
        cad_ir_versions=["0.1.0"],
        capabilities=statuses or {key: CapabilityStatus.STABLE for key in MVP_CAPABILITIES},
    )


def build_cad_job() -> Job:
    return Job(
        uuid4(),
        uuid4(),
        JobType.BUILD_CAD,
        f"sha256:{uuid4()}",
        {WorkerCapability.KOMPAS_BUILD},
        "0.1.0",
        required_capability_keys(JobType.BUILD_CAD),
    )


def memory_service() -> tuple[WorkerProtocolService, object]:
    service = WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT)
    worker, _ = service.register(enrollment_token=ENROLLMENT, worker_name="w", app_version="0.4.0")
    return service, worker


def test_mvp_jobs_require_the_confirmed_capability_vocabulary():
    assert required_capability_keys(JobType.BUILD_CAD) == list(MVP_CAPABILITIES)
    assert required_capability_keys(JobType.ANALYZE_DRAWING) == list(MVP_CAPABILITIES)
    assert required_capability_keys(JobType.COMPILE_CAD_IR) == []


def test_a_worker_without_a_manifest_is_not_offered_a_capability_gated_job():
    service, worker = memory_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
    service.enqueue(build_cad_job())

    assert service.claim(worker) is None


def test_a_partial_manifest_blocks_the_lease_and_names_what_is_missing():
    service, worker = memory_service()
    partial = {key: CapabilityStatus.STABLE for key in MVP_CAPABILITIES}
    partial.pop(SOLID_RECTANGULAR_PRISM)
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest(partial))
    service.enqueue(build_cad_job())

    assert service.claim(worker) is None
    assert unmet_capabilities(worker.capability_manifest, list(MVP_CAPABILITIES)) == [
        SOLID_RECTANGULAR_PRISM
    ]


def test_experimental_and_disabled_capabilities_do_not_qualify():
    for blocked in (CapabilityStatus.EXPERIMENTAL, CapabilityStatus.DISABLED, CapabilityStatus.UNSUPPORTED):
        service, worker = memory_service()
        statuses = {key: CapabilityStatus.STABLE for key in MVP_CAPABILITIES}
        statuses[SOLID_RECTANGULAR_PRISM] = blocked
        service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest(statuses))
        service.enqueue(build_cad_job())

        assert service.claim(worker) is None, f"{blocked} must not be leasable"


def test_a_fully_capable_worker_is_offered_the_job():
    service, worker = memory_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest())
    job = build_cad_job()
    service.enqueue(job)

    claimed = service.claim(worker)
    assert claimed is not None and claimed.id == job.id


def test_a_v1_job_without_capability_requirements_stays_leasable():
    """Jobs enqueued before the registry existed carry no requirements and
    must keep working exactly as they did."""
    service, worker = memory_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
    legacy = Job(
        uuid4(), uuid4(), JobType.BUILD_CAD, "sha256:legacy", {WorkerCapability.KOMPAS_BUILD}, "0.1.0"
    )
    service.enqueue(legacy)

    assert service.claim(worker) is not None


def sql_service():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    service = SqlWorkerProtocolService(sessions, ENROLLMENT)
    worker, credential = service.register(
        enrollment_token=ENROLLMENT, worker_name=f"sql-{uuid4()}", app_version="0.4.0"
    )
    return service, worker, credential


def test_sql_claim_applies_the_same_gate():
    service, worker, _ = sql_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
    service.enqueue(build_cad_job())
    assert service.claim(worker) is None

    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest())
    assert service.claim(worker) is not None


def test_sql_manifest_survives_a_reauthentication():
    """The gate must read the stored manifest, not an in-memory leftover: a
    worker reconnecting to a restarted API keeps its declared capabilities."""
    service, worker, credential = sql_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest())

    reloaded = service.authenticate(worker.id, credential)
    assert reloaded.capability_manifest is not None
    assert (
        reloaded.capability_manifest.capabilities[SOLID_RECTANGULAR_PRISM].status
        is CapabilityStatus.STABLE
    )


def test_sql_keeps_one_history_row_per_distinct_manifest():
    from app.ledger.models import WorkerCapabilitySnapshotRow
    from sqlalchemy import select

    service, worker, _ = sql_service()
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest())
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest())

    changed = {key: CapabilityStatus.STABLE for key in MVP_CAPABILITIES}
    changed["solid.revolve"] = CapabilityStatus.BETA
    service.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1, manifest(changed))

    with service.sessions() as session:
        rows = session.scalars(select(WorkerCapabilitySnapshotRow)).all()
    # Repeated heartbeats of an unchanged manifest must not grow the history.
    assert len(rows) == 2


def test_claim_endpoint_rejects_an_incapable_worker(monkeypatch):
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT)
    monkeypatch.setattr("app.main.worker_protocol", protocol)
    client = TestClient(app)
    registered = client.post(
        "/api/v1/workers/register",
        json={"enrollment_token": ENROLLMENT, "worker_name": "gated", "app_version": "0.4.0"},
    ).json()
    protocol.repo.jobs[uuid4()] = build_cad_job()

    body = {
        "protocol_version": "1.0",
        "worker_id": registered["worker_id"],
        "capabilities": ["KOMPAS_BUILD"],
        "supported_cad_ir": ["0.1.0"],
        "available_slots": 1,
    }
    headers = {"Authorization": f"Bearer {registered['credential']}"}

    without = client.post("/api/v1/workers/claim", headers=headers, json=body)
    assert without.json()["job"] is None

    partial = {key: CapabilityStatus.STABLE.value for key in MVP_CAPABILITIES}
    partial[SOLID_RECTANGULAR_PRISM] = CapabilityStatus.EXPERIMENTAL.value
    gated = client.post(
        "/api/v1/workers/claim",
        headers=headers,
        json={**body, "capability_manifest": manifest(partial).model_dump(mode="json")},
    )
    assert gated.json()["job"] is None

    capable = client.post(
        "/api/v1/workers/claim",
        headers=headers,
        json={**body, "capability_manifest": manifest().model_dump(mode="json")},
    )
    assert capable.json()["job"] is not None
