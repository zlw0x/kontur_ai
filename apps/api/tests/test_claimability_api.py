import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.contracts import CapabilityStatus, WorkerCapability
from app.main import app
from app.database import Base, create_session_factory
from app.ledger.service import ResourceLedgerService
from app.workers.artifact_store import LocalArtifactStore
from app.workers.capabilities import MVP_CAPABILITIES, SOLID_RECTANGULAR_PRISM
from app.workers.protocol import InMemoryWorkerRepository, WorkerProtocolService
from cad_ir.canonical import CAD_IR_VERSION

def disposable_ledger() -> ResourceLedgerService:
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return ResourceLedgerService(sessions)


MANUAL = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
ENROLLMENT = "local-development-enrollment-token-change-me"


def manifest(**overrides) -> dict:
    return {
        "schema_version": "1.0",
        "worker_version": "0.4.0",
        "kompas_version": "22.0",
        "cad_ir_versions": [CAD_IR_VERSION],
        "capabilities": {
            key: {"status": CapabilityStatus.STABLE.value, "version": "1.0"}
            for key in MVP_CAPABILITIES
        },
        **overrides,
    }


def environment(monkeypatch, tmp_path):
    protocol = WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT)
    monkeypatch.setattr("app.main.worker_protocol", protocol)
    monkeypatch.setattr("app.main.resource_ledger", disposable_ledger())
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    monkeypatch.setattr("app.main.drawing_orders", {})
    return protocol, TestClient(app)


def enrol(client, protocol, name="local-pc", app_version="0.4.0"):
    registered = client.post(
        "/api/v1/workers/register",
        json={"enrollment_token": ENROLLMENT, "worker_name": name, "app_version": app_version},
    ).json()
    return registered, {"Authorization": f"Bearer {registered['credential']}"}


def heartbeat(client, headers, worker_id, capability_manifest=None, slots=1):
    body = {
        "worker_id": worker_id,
        "capabilities": ["AI_DRAWING", "KOMPAS_BUILD"],
        "supported_cad_ir": [CAD_IR_VERSION],
        "available_slots": slots,
    }
    if capability_manifest is not None:
        body["capability_manifest"] = capability_manifest
    return client.post("/api/v1/workers/heartbeat", headers=headers, json=body)


def manual_job(client, tmp_path) -> str:
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json").read_text(
            encoding="utf-8"
        )
    )
    created = client.post(
        "/api/v1/manual/cad-jobs", headers=MANUAL, json={"cad_ir": fixture, "requested_formats": ["step", "stl"]}
    )
    assert created.status_code == 201
    return created.json()["job_id"]


def test_claimability_endpoint_requires_the_manual_token(monkeypatch, tmp_path):
    _, client = environment(monkeypatch, tmp_path)
    job_id = manual_job(client, tmp_path)

    assert client.get(f"/api/v1/manual/cad-jobs/{job_id}/claimability").status_code == 401
    assert client.get(
        f"/api/v1/manual/cad-jobs/{uuid4()}/claimability", headers=MANUAL
    ).status_code == 404


def test_claimability_names_the_worker_and_the_missing_manifest(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    job_id = manual_job(client, tmp_path)
    registered, headers = enrol(client, protocol)
    assert heartbeat(client, headers, registered["worker_id"]).status_code == 204

    report = client.get(f"/api/v1/manual/cad-jobs/{job_id}/claimability", headers=MANUAL).json()

    assert report["claimability"] == "blocked"
    assert report["online_workers"] == 1
    assert report["compatible_workers"] == 0
    assert [item["code"] for item in report["blockers"]] == ["WORKER_MANIFEST_MISSING"]
    assert report["blockers"][0]["worker_name"] == "local-pc"
    assert {item["name"] for item in report["required_capabilities"]} == set(MVP_CAPABILITIES)


def test_claimability_reports_an_experimental_capability_distinctly(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    job_id = manual_job(client, tmp_path)
    registered, headers = enrol(client, protocol)
    partial = manifest()
    partial["capabilities"][SOLID_RECTANGULAR_PRISM] = {
        "status": CapabilityStatus.EXPERIMENTAL.value,
        "version": "1.0",
    }
    heartbeat(client, headers, registered["worker_id"], partial)

    report = client.get(f"/api/v1/manual/cad-jobs/{job_id}/claimability", headers=MANUAL).json()

    blocker = next(item for item in report["blockers"] if item["capability"] == SOLID_RECTANGULAR_PRISM)
    assert blocker["code"] == "CAPABILITY_EXPERIMENTAL_ONLY"


def test_a_capable_worker_makes_the_job_claimable(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    job_id = manual_job(client, tmp_path)
    registered, headers = enrol(client, protocol)
    heartbeat(client, headers, registered["worker_id"], manifest())

    report = client.get(f"/api/v1/manual/cad-jobs/{job_id}/claimability", headers=MANUAL).json()

    assert report["claimability"] == "claimable"
    assert report["compatible_workers"] == 1
    assert report["blockers"] == []
    assert report["summary"] == "The order is queued and a modelling module is available."


def test_diagnosis_does_not_consume_the_job(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    job_id = manual_job(client, tmp_path)
    registered, headers = enrol(client, protocol)
    heartbeat(client, headers, registered["worker_id"], manifest())

    for _ in range(3):
        client.get(f"/api/v1/manual/cad-jobs/{job_id}/claimability", headers=MANUAL)

    claim = client.post(
        "/api/v1/workers/claim",
        headers=headers,
        json={
            "protocol_version": "1.0",
            "worker_id": registered["worker_id"],
            "capabilities": ["KOMPAS_BUILD"],
            "supported_cad_ir": [CAD_IR_VERSION],
            "available_slots": 1,
            "capability_manifest": manifest(),
        },
    ).json()
    assert claim["job"]["job_id"] == job_id
    assert claim["job"]["attempt"] == 1


def test_drawing_order_status_explains_why_it_is_waiting(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    created = client.post(
        "/api/v1/drawing-jobs",
        headers={**MANUAL, "content-type": "image/png"},
        content=b"\x89PNG\r\n\x1a\n" + b"fixture",
    )
    order_id = created.json()["order_id"]
    registered, headers = enrol(client, protocol)
    heartbeat(client, headers, registered["worker_id"])

    blocked = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()

    # The customer is told the order is waiting, without a capability key or a
    # worker version, neither of which means anything to them.
    assert blocked["waiting_reason"] == "The order is waiting for an available modelling module."
    assert "manifest" not in blocked["waiting_reason"]

    heartbeat(client, headers, registered["worker_id"], manifest())
    unblocked = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()
    assert unblocked["waiting_reason"] == "The order is queued and a modelling module is available."


def test_a_busy_worker_produces_a_different_customer_message(monkeypatch, tmp_path):
    protocol, client = environment(monkeypatch, tmp_path)
    created = client.post(
        "/api/v1/drawing-jobs",
        headers={**MANUAL, "content-type": "image/png"},
        content=b"\x89PNG\r\n\x1a\n" + b"fixture",
    )
    order_id = created.json()["order_id"]
    registered, headers = enrol(client, protocol)
    heartbeat(client, headers, registered["worker_id"], manifest(), slots=0)

    status = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()

    assert status["waiting_reason"] == (
        "The order is waiting for the modelling module to finish another job."
    )
