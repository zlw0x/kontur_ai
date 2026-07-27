from fastapi.testclient import TestClient
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from app.main import app
from app.contracts import JobType, WorkerCapability
from app.workers.artifact_store import LocalArtifactStore
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService


app.dependency_overrides = {}


def memory_protocol(monkeypatch):
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), "local-development-enrollment-token-change-me")
    monkeypatch.setattr("app.main.worker_protocol", protocol)
    return protocol


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
        "worker_id": body["worker_id"], "capabilities": ["KOMPAS_BUILD"], "supported_cad_ir": ["0.1.0"], "available_slots": 1
    })
    assert heartbeat.status_code == 204
    claim = client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": body["worker_id"], "capabilities": ["KOMPAS_BUILD"], "supported_cad_ir": ["0.1.0"], "available_slots": 1
    })
    assert claim.status_code == 200 and claim.json() == {"protocol_version": "1.0", "job": None, "retry_after_seconds": 5}


def test_worker_api_rejects_bad_enrollment_and_missing_credential(monkeypatch):
    memory_protocol(monkeypatch)
    client = TestClient(app)
    assert client.post("/api/v1/workers/register", json={"enrollment_token": "x" * 32, "worker_name": "bad", "app_version": "0.1"}).status_code == 401
    assert client.post("/api/v1/workers/claim", json={"protocol_version": "1.0", "worker_id": "123e4567-e89b-12d3-a456-426614174000", "capabilities": ["KOMPAS_BUILD"], "supported_cad_ir": ["0.1.0"], "available_slots": 1}).status_code == 401


def test_job_heartbeat_and_completion_are_authenticated_and_idempotent(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    client = TestClient(app)
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": "local-development-enrollment-token-change-me", "worker_name": "completion-worker", "app_version": "0.1.0"
    }).json()
    worker_id, job_id = UUID(registered["worker_id"]), uuid4()
    worker = protocol.repo.workers[worker_id]
    protocol.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
    protocol.repo.jobs[job_id] = Job(job_id, uuid4(), JobType.BUILD_CAD, "sha256:complete", {WorkerCapability.KOMPAS_BUILD}, "0.1.0")
    assert protocol.claim(worker) is not None
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    heartbeat = client.post(f"/api/v1/workers/jobs/{job_id}/heartbeat", headers=headers, json={
        "job_id": str(job_id), "stage": "CAD_BUILDING", "progress": 0.5,
        "message_code": "FEATURE_BUILDING", "safe_details": {"feature_index": 1}
    })
    assert heartbeat.status_code == 204
    artifact_bytes = b"fake-m3d"
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest().upper()
    uploaded = client.put(
        f"/api/v1/workers/jobs/{job_id}/artifacts/M3D",
        headers={**headers, "x-content-sha256": artifact_sha},
        content=artifact_bytes,
    )
    assert uploaded.status_code == 200
    payload = {
        "job_id": str(job_id), "idempotency_key": "sha256:complete",
        "result": {"status": "success"},
        "artifacts": [uploaded.json()],
    }
    first = client.post(f"/api/v1/workers/jobs/{job_id}/complete", headers=headers, json=payload)
    replay = client.post(f"/api/v1/workers/jobs/{job_id}/complete", headers=headers, json=payload)
    assert first.json()["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert len(protocol.repo.artifacts[job_id]) == 1


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
        json={"cad_ir": fixture, "requested_formats": ["m3d"]},
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
            "capabilities": ["KOMPAS_BUILD"],
            "supported_cad_ir": ["0.1.0"],
            "available_slots": 1,
        },
    ).json()["job"]
    assert claim["job_id"] == job_id

    manifest = client.get(claim["manifest_url"], headers=headers)
    assert manifest.status_code == 200
    source = manifest.json()["inputs"][0]
    downloaded = client.get(source["download_url"], headers=headers)
    assert len(downloaded.content) == source["size_bytes"]
    assert hashlib.sha256(downloaded.content).hexdigest().upper() == source["sha256"]

    artifact = b"m3d-result"
    digest = hashlib.sha256(artifact).hexdigest().upper()
    bad = client.put(
        f"/api/v1/workers/jobs/{job_id}/artifacts/M3D",
        headers={**headers, "x-content-sha256": "0" * 64},
        content=artifact,
    )
    assert bad.status_code == 409
    uploaded = client.put(
        f"/api/v1/workers/jobs/{job_id}/artifacts/M3D",
        headers={**headers, "x-content-sha256": digest},
        content=artifact,
    )
    assert uploaded.status_code == 200
    completed = client.post(
        f"/api/v1/workers/jobs/{job_id}/complete",
        headers=headers,
        json={
            "job_id": job_id,
            "idempotency_key": claim["idempotency_key"],
            "result": {"status": "success"},
            "artifacts": [uploaded.json()],
        },
    )
    assert completed.status_code == 200
    status = client.get(f"/api/v1/manual/cad-jobs/{job_id}", headers=manual_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "COMPLETED"
    result = client.get(
        f"/api/v1/manual/cad-jobs/{job_id}/artifacts/M3D",
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
    png = b"\x89PNG\r\n\x1a\n" + b"fixture"
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
            "capabilities": ["AI_DRAWING", "KOMPAS_BUILD"],
            "supported_cad_ir": ["0.1.0"],
            "available_slots": 1,
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
