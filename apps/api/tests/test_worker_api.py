from fastapi.testclient import TestClient
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from tests.drawing_fixture import TINY_PNG
from app.main import app
from app.contracts import CapabilityStatus, JobType, WorkerCapability
from app.database import Base, create_session_factory
from app.ledger.service import ResourceLedgerService
from app.workers.artifact_store import LocalArtifactStore
from app.workers.capabilities import MVP_CAPABILITIES
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService
from cad_ir.canonical import CAD_IR_VERSION


app.dependency_overrides = {}


def memory_protocol(monkeypatch):
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), "local-development-enrollment-token-change-me")
    monkeypatch.setattr("app.main.worker_protocol", protocol)
    monkeypatch.setattr("app.main.resource_ledger", disposable_ledger())
    return protocol


def disposable_ledger() -> ResourceLedgerService:
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return ResourceLedgerService(sessions)


def mvp_manifest(**overrides) -> dict:
    """What a current worker publishes: the whole confirmed MVP vocabulary."""
    return {
        "schema_version": "1.0",
        "worker_version": "0.4.0",
        "cad_ir_versions": [CAD_IR_VERSION],
        "capabilities": {key: CapabilityStatus.STABLE.value for key in MVP_CAPABILITIES},
        **overrides,
    }


def test_worker_register_heartbeat_and_empty_claim(monkeypatch):
    memory_protocol(monkeypatch)
    client = TestClient(app)
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": "local-development-enrollment-token-change-me", "worker_name": "test-worker", "app_version": "0.1.0"
    })
    assert registered.status_code == 201
    body = registered.json()
    headers = {"Authorization": f"Bearer {body['credential']}"}
    heartbeat = client.post("/api/v1/workers/heartbeat", headers=headers, json={
        "worker_id": body["worker_id"], "capabilities": ["CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION], "available_slots": 1
    })
    assert heartbeat.status_code == 204
    claim = client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": body["worker_id"], "capabilities": ["CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION], "available_slots": 1
    })
    assert claim.status_code == 200 and claim.json() == {"protocol_version": "1.0", "job": None, "retry_after_seconds": 5}


def test_worker_api_rejects_bad_enrollment_and_missing_credential(monkeypatch):
    memory_protocol(monkeypatch)
    client = TestClient(app)
    assert client.post("/api/v1/workers/register", json={"enrollment_token": "x" * 32, "worker_name": "bad", "app_version": "0.1"}).status_code == 401
    assert client.post("/api/v1/workers/claim", json={"protocol_version": "1.0", "worker_id": "123e4567-e89b-12d3-a456-426614174000", "capabilities": ["CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION], "available_slots": 1}).status_code == 401


def test_job_heartbeat_and_completion_are_authenticated_and_idempotent(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    client = TestClient(app)
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": "local-development-enrollment-token-change-me", "worker_name": "completion-worker", "app_version": "0.1.0"
    }).json()
    worker_id, job_id = UUID(registered["worker_id"]), uuid4()
    worker = protocol.repo.workers[worker_id]
    protocol.heartbeat(worker, [WorkerCapability.CAD_BUILD], [CAD_IR_VERSION], 1)
    protocol.repo.jobs[job_id] = Job(job_id, uuid4(), JobType.BUILD_CAD, "sha256:complete", {WorkerCapability.CAD_BUILD}, CAD_IR_VERSION)
    assert protocol.claim(worker) is not None
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    heartbeat = client.post(f"/api/v1/workers/jobs/{job_id}/heartbeat", headers=headers, json={
        "job_id": str(job_id), "stage": "CAD_BUILDING", "progress": 0.5,
        "message_code": "FEATURE_BUILDING", "safe_details": {"feature_index": 1}
    })
    assert heartbeat.status_code == 204
    delivered = []
    for kind, content in (("STEP", b"ISO-10303-21;"), ("STL", b"solid fake")):
        uploaded = client.put(
            f"/api/v1/workers/jobs/{job_id}/artifacts/{kind}",
            headers={**headers, "x-content-sha256": hashlib.sha256(content).hexdigest().upper()},
            content=content,
        )
        assert uploaded.status_code == 200
        delivered.append(uploaded.json())
    payload = {
        "job_id": str(job_id), "idempotency_key": "sha256:complete",
        "result": {"status": "success"},
        "artifacts": delivered,
    }
    first = client.post(f"/api/v1/workers/jobs/{job_id}/complete", headers=headers, json=payload)
    replay = client.post(f"/api/v1/workers/jobs/{job_id}/complete", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert len(protocol.repo.artifacts[job_id]) == 2


def test_manual_cad_job_manifest_download_upload_and_complete(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    client = TestClient(app)
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json").read_text(
            encoding="utf-8"
        )
    )
    manual_headers = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
    created = client.post(
        "/api/v1/manual/cad-jobs",
        headers=manual_headers,
        json={"cad_ir": fixture, "requested_formats": ["step", "stl"]},
    )
    assert created.status_code == 201
    job_id = created.json()["job_id"]

    registered = client.post(
        "/api/v1/workers/register",
        json={
            "enrollment_token": "local-development-enrollment-token-change-me",
            "worker_name": "e2e-worker",
            "app_version": "0.1.0",
        },
    ).json()
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    claim = client.post(
        "/api/v1/workers/claim",
        headers=headers,
        json={
            "protocol_version": "1.0",
            "worker_id": registered["worker_id"],
            "capabilities": ["CAD_BUILD"],
            "supported_cad_ir": [CAD_IR_VERSION],
            "available_slots": 1,
            "capability_manifest": mvp_manifest(),
        },
    ).json()["job"]
    assert claim["job_id"] == job_id

    manifest = client.get(claim["manifest_url"], headers=headers)
    assert manifest.status_code == 200
    source = manifest.json()["inputs"][0]
    downloaded = client.get(source["download_url"], headers=headers)
    assert len(downloaded.content) == source["size_bytes"]
    assert hashlib.sha256(downloaded.content).hexdigest().upper() == source["sha256"]

    artifact = b"ISO-10303-21;"
    digest = hashlib.sha256(artifact).hexdigest().upper()
    bad = client.put(
        f"/api/v1/workers/jobs/{job_id}/artifacts/STEP",
        headers={**headers, "x-content-sha256": "0" * 64},
        content=artifact,
    )
    assert bad.status_code == 409
    delivered = []
    for kind, content in (("STEP", artifact), ("STL", b"solid manual")):
        uploaded = client.put(
            f"/api/v1/workers/jobs/{job_id}/artifacts/{kind}",
            headers={**headers, "x-content-sha256": hashlib.sha256(content).hexdigest().upper()},
            content=content,
        )
        assert uploaded.status_code == 200
        delivered.append(uploaded.json())

    # A build that produced only half of what it owes is refused, and says which
    # half is missing.
    partial = client.post(
        f"/api/v1/workers/jobs/{job_id}/complete",
        headers=headers,
        json={
            "job_id": job_id,
            "idempotency_key": claim["idempotency_key"],
            "result": {"status": "success"},
            "artifacts": [delivered[0]],
        },
    )
    assert partial.status_code == 409
    assert "STL" in partial.json()["detail"]

    completed = client.post(
        f"/api/v1/workers/jobs/{job_id}/complete",
        headers=headers,
        json={
            "job_id": job_id,
            "idempotency_key": claim["idempotency_key"],
            "result": {"status": "success"},
            "artifacts": delivered,
        },
    )
    assert completed.status_code == 200
    status = client.get(f"/api/v1/manual/cad-jobs/{job_id}", headers=manual_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "COMPLETED"
    result = client.get(
        f"/api/v1/manual/cad-jobs/{job_id}/artifacts/STEP",
        headers=manual_headers,
    )
    assert result.status_code == 200
    assert result.content == artifact


def test_drawing_job_clarification_roundtrip(monkeypatch, tmp_path):
    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    monkeypatch.setattr("app.main.drawing_orders", {})
    client = TestClient(app)
    manual_headers = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
    png = TINY_PNG
    created = client.post(
        "/api/v1/drawing-jobs",
        headers={**manual_headers, "content-type": "image/png"},
        content=png,
    )
    assert created.status_code == 201
    order_id, job_id = created.json()["order_id"], created.json()["job_id"]

    registered = client.post(
        "/api/v1/workers/register",
        json={
            "enrollment_token": "local-development-enrollment-token-change-me",
            "worker_name": "drawing-worker",
            "app_version": "0.1.0",
        },
    ).json()
    worker_headers = {"Authorization": f"Bearer {registered['credential']}"}
    claim = client.post(
        "/api/v1/workers/claim",
        headers=worker_headers,
        json={
            "protocol_version": "1.0",
            "worker_id": registered["worker_id"],
            "capabilities": ["AI_DRAWING", "CAD_BUILD"],
            "supported_cad_ir": [CAD_IR_VERSION],
            "available_slots": 1,
            "capability_manifest": mvp_manifest(),
        },
    ).json()["job"]
    manifest = client.get(claim["manifest_url"], headers=worker_headers).json()
    assert manifest["inputs"][0]["kind"] == "drawing"
    downloaded = client.get(manifest["inputs"][0]["download_url"], headers=worker_headers)
    assert downloaded.content == png

    questions = json.dumps({
        "schema_version": "0.1.0",
        "questions": [{"id": "q_depth", "parameter_id": "depth", "text": "Depth in mm?"}],
    }).encode()
    analysis = b'{"schema_version":"0.1.0","result":{"ready_for_cad":false}}'
    uploaded = []
    for artifact_type, payload in (
        ("DRAWING_ANALYSIS", analysis),
        ("CLARIFICATION_QUESTIONS", questions),
    ):
        digest = hashlib.sha256(payload).hexdigest().upper()
        response = client.put(
            f"/api/v1/workers/jobs/{job_id}/artifacts/{artifact_type}",
            headers={**worker_headers, "x-content-sha256": digest},
            content=payload,
        )
        assert response.status_code == 200
        uploaded.append(response.json())
    completed = client.post(
        f"/api/v1/workers/jobs/{job_id}/complete",
        headers=worker_headers,
        json={
            "job_id": job_id,
            "idempotency_key": claim["idempotency_key"],
            "result": {"status": "need_user_input"},
            "artifacts": uploaded,
        },
    )
    assert completed.status_code == 200
    # The API can reconstruct order lineage after a process restart.
    monkeypatch.setattr("app.main.drawing_orders", {})
    status = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=manual_headers)
    assert status.json()["status"] == "WAITING_FOR_USER_ANSWERS"
    assert status.json()["questions"][0]["id"] == "q_depth"

    wrong = client.post(
        f"/api/v1/drawing-jobs/{order_id}/answers",
        headers=manual_headers,
        json={"answers": [{"question_id": "q_other", "value": 10, "unit": "mm"}]},
    )
    assert wrong.status_code == 422
    answered = client.post(
        f"/api/v1/drawing-jobs/{order_id}/answers",
        headers=manual_headers,
        json={"answers": [{"question_id": "q_depth", "value": 10, "unit": "mm"}]},
    )
    assert answered.status_code == 201
    assert answered.json()["job_id"] != job_id


def test_a_manual_submission_is_normalised_and_its_lineage_returned(monkeypatch, tmp_path):
    """A caller may still submit 0.1.0. It is lifted into the canonical form so
    the worker only ever sees one shape, and the response says exactly what
    happened to it."""
    memory_protocol(monkeypatch)
    store = LocalArtifactStore(tmp_path, 1_000_000)
    monkeypatch.setattr("app.main.artifact_store", store)
    client = TestClient(app)
    legacy = json.loads(
        (Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json").read_text(
            encoding="utf-8"
        )
    )

    created = client.post(
        "/api/v1/manual/cad-jobs",
        headers={"x-manual-api-token": "local-development-manual-api-token-change-me"},
        json={"cad_ir": legacy, "requested_formats": ["step", "stl"]},
    )

    assert created.status_code == 201
    lineage = created.json()["lineage"]
    assert lineage["original_schema_version"] == "0.1.0"
    assert lineage["canonical_schema_version"] == CAD_IR_VERSION
    assert lineage["original_sha256"] != lineage["canonical_sha256"]
    assert lineage["normalizer_version"]

    stored = json.loads(
        store.cad_ir(UUID(created.json()["job_id"])).path.read_text(encoding="utf-8")
    )
    assert stored["schema_version"] == CAD_IR_VERSION
    assert stored["features"][0]["type"] == "solid.extrude"


def test_a_submission_that_cannot_be_migrated_is_refused_with_its_reasons(monkeypatch, tmp_path):
    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    client = TestClient(app)
    legacy = json.loads(
        (Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json").read_text(
            encoding="utf-8"
        )
    )
    legacy["features"][0]["inputs"]["distance"] = {"expr": "p_depth * 2"}

    refused = client.post(
        "/api/v1/manual/cad-jobs",
        headers={"x-manual-api-token": "local-development-manual-api-token-change-me"},
        json={"cad_ir": legacy, "requested_formats": ["step", "stl"]},
    )

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "CAD_IR_INVALID"
    assert detail["issues"][0]["code"] == "CAD_IR_MIGRATION_FAILED"
