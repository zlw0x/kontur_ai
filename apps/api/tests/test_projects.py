"""The editing boundary: ownership, immutable history, dispatch and geometry."""

import hashlib
import json
from uuid import UUID, uuid4

import pytest
from app import main
from app.accounts import CSRF_HEADER
from app.contracts import JobStatus, JobType
from app.database import Base, create_session_factory
from app.projects.repository import ProjectRepository
from app.workers.artifact_store import LocalArtifactStore
from cad_ir.canonical import CAD_IR_VERSION
from fastapi.testclient import TestClient
from tests.test_accounts import signed_up
from tests.test_worker_api import memory_protocol, mvp_manifest


@pytest.fixture
def project_client(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    engine, sessions = create_session_factory(
        f"sqlite:///{(tmp_path / 'projects.sqlite').as_posix()}"
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "projects", ProjectRepository(sessions))
    monkeypatch.setattr(
        main, "artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000)
    )
    monkeypatch.setattr(main.settings, "automatic_acceptance", True)
    client = TestClient(main.app)
    session = signed_up(client, "editor@example.com")
    client.headers[CSRF_HEADER] = session["csrf_token"]
    return client, protocol


def create(client):
    response = client.post("/api/v1/projects", json={"name": "Корпус", "enclosure": {}})
    assert response.status_code == 201, response.text
    return response.json()


def ready(project, protocol, *, valid=True):
    job_id = UUID(project["versions"][0]["order_id"])
    order = main.orders.get(job_id)
    job = protocol.get_job(order.latest_job_id)
    delivered = []
    for kind, payload in (
        ("STEP", b"step stub"),
        ("STL", b"stl stub"),
        ("VALIDATION_REPORT", json.dumps({"valid": valid}).encode()),
    ):
        stored = main.artifact_store.put_artifact(
            job.id, kind, payload, hashlib.sha256(payload).hexdigest()
        )
        delivered.append(
            {"type": kind, "size_bytes": stored.size_bytes, "sha256": stored.sha256}
        )
    protocol.repo.artifacts[job.id] = delivered
    job.status = JobStatus.COMPLETED
    return job


def edit(client, project, **operation):
    return client.post(
        f"/api/v1/projects/{project['id']}/edits",
        json={
            "expected_revision": project["revision"],
            "action_id": str(uuid4()),
            **operation,
        },
    )


def test_create_queues_only_cad_and_pending_version_cannot_be_edited(project_client):
    client, protocol = project_client
    project = create(client)
    assert project["revision"] == 1
    assert [j.job_type for j in protocol.repo.jobs.values()] == [JobType.BUILD_CAD]
    assert project["artifacts"] == []
    refused = edit(client, project, kind="parameters", changes={"p_width": 140})
    assert refused.status_code == 409
    assert len(main.projects.versions(project["id"])) == 1


def test_worker_cannot_complete_project_without_geometry_report(project_client):
    client, _ = project_client
    project = create(client)
    worker_client = TestClient(main.app)
    registered = worker_client.post(
        "/api/v1/workers/register",
        json={
            "enrollment_token": main.settings.worker_enrollment_token,
            "worker_name": "missing-report",
            "app_version": "1.0",
        },
    ).json()
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    claim = worker_client.post(
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
    artifacts = []
    for kind in ("STEP", "STL"):
        content = kind.encode()
        uploaded = worker_client.put(
            f"/api/v1/workers/jobs/{claim['job_id']}/artifacts/{kind}",
            headers={
                **headers,
                "x-content-sha256": hashlib.sha256(content).hexdigest(),
            },
            content=content,
        )
        assert uploaded.status_code == 200
        artifacts.append(uploaded.json())
    result = worker_client.post(
        f"/api/v1/workers/jobs/{claim['job_id']}/complete",
        headers=headers,
        json={
            "job_id": claim["job_id"],
            "idempotency_key": claim["idempotency_key"],
            "result": {"status": "success"},
            "artifacts": artifacts,
        },
    )
    assert result.status_code == 409
    assert client.get(f"/api/v1/projects/{project['id']}").json()["status"] != "READY"


def test_concurrent_edits_have_one_winner(project_client):
    from concurrent.futures import ThreadPoolExecutor

    client, protocol = project_client
    project = create(client)
    ready(project, protocol)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda size: edit(
                    client, project, kind="parameters", changes={"p_width": size}
                ),
                [140, 150],
            )
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert main.projects.get(project["id"]).head == 2
    assert len(protocol.repo.jobs) == 2


def test_idempotent_edit_stale_window_and_unchanged_original(project_client):
    client, protocol = project_client
    project = create(client)
    ready(project, protocol)
    body = {
        "expected_revision": 1,
        "action_id": str(uuid4()),
        "kind": "parameters",
        "changes": {"p_width": 140},
    }
    first = client.post(f"/api/v1/projects/{project['id']}/edits", json=body)
    assert first.status_code == 201, first.text
    replay = client.post(f"/api/v1/projects/{project['id']}/edits", json=body)
    assert replay.status_code == 201
    assert replay.json()["revision"] == 2
    assert len(protocol.repo.jobs) == 2
    wrong_replay = client.post(
        f"/api/v1/projects/{project['id']}/edits",
        json={**body, "changes": {"p_width": 150}},
    )
    assert wrong_replay.status_code == 409
    stale = edit(client, project, kind="parameters", changes={"p_height": 100})
    assert stale.status_code == 409
    original = main.projects.version(project["id"], 1).document
    assert original["parameters"][0]["value"] == 120
    assert original["expectations"][0]["size_mm"]["x"] == 120
    updated = first.json()["cad_ir"]
    assert updated["parameters"][0]["value"] == 140
    assert updated["expectations"][0]["size_mm"]["x"] == 140


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "parameters", "changes": {"p_width": -1}},
        {"kind": "parameters", "changes": {"missing": 10}},
        {"kind": "text", "text": "увеличь диаметр"},
        {"kind": "text", "text": "запусти произвольный код"},
        {"kind": "hole", "diameter": 0, "x": 0, "y": 0},
        {"kind": "parameters", "changes": {"p_width": 140}, "unknown": 5},
    ],
)
def test_bad_edit_leaves_no_version_or_job(project_client, operation):
    client, protocol = project_client
    project = create(client)
    ready(project, protocol)
    response = edit(client, project, **operation)
    assert response.status_code == 422, response.text
    assert len(protocol.repo.jobs) == 1
    assert main.projects.get(project["id"]).head == 1


def test_foreign_and_missing_projects_are_indistinguishable_and_csrf_required(
    project_client,
):
    client, _ = project_client
    project = create(client)
    other = TestClient(main.app)
    session = signed_up(other, "other@example.com")
    other.headers[CSRF_HEADER] = session["csrf_token"]
    for suffix in ("", "/cad-ir"):
        foreign = other.get(f"/api/v1/projects/{project['id']}{suffix}")
        absent = other.get(f"/api/v1/projects/{uuid4()}{suffix}")
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()
    assert other.get("/api/v1/projects").json() == []
    assert (
        edit(other, project, kind="parameters", changes={"p_width": 140}).status_code
        == 404
    )
    assert (
        other.post(f"/api/v1/projects/{project['id']}/retry-build").status_code == 404
    )
    client.headers.pop(CSRF_HEADER)
    assert (
        client.post("/api/v1/projects", json={"name": "x", "enclosure": {}}).status_code
        == 403
    )
    assert TestClient(main.app).get("/api/v1/projects").status_code == 401


def test_dispatch_outage_is_durable_retry_uses_same_job(project_client, monkeypatch):
    client, protocol = project_client
    enqueue = protocol.enqueue
    monkeypatch.setattr(
        protocol,
        "enqueue",
        lambda job: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )
    project = create(client)
    assert project["status"] == "DISPATCH_PENDING"
    version = main.projects.version(project["id"], 1)
    monkeypatch.setattr(protocol, "enqueue", enqueue)
    for _ in range(2):
        retried = client.post(f"/api/v1/projects/{project['id']}/retry-build")
        assert retried.status_code == 200
    assert list(protocol.repo.jobs) == [UUID(version.job_id)]
    assert len(main.projects.versions(project["id"])) == 1


def test_failed_geometry_is_not_ready_and_restore_preserves_history(project_client):
    client, protocol = project_client
    project = create(client)
    ready(project, protocol)
    response = edit(client, project, kind="text", text="увеличь ширину на 10")
    assert response.status_code == 201, response.text
    second = response.json()
    ready(second, protocol, valid=False)
    failed = client.get(f"/api/v1/projects/{project['id']}").json()
    assert failed["status"] == "FAILED" and failed["artifacts"] == []
    restored = edit(client, second, kind="restore", revision=1)
    assert restored.status_code == 201, restored.text
    assert restored.json()["revision"] == 3
    assert restored.json()["cad_ir"] == project["cad_ir"]
    assert len(restored.json()["versions"]) == 3


def test_sql_repository_reopens_and_customer_downloads_cad_ir(
    project_client, monkeypatch
):
    client, protocol = project_client
    project = create(client)
    ready(project, protocol)
    sessions = main.projects.sessions
    url = str(sessions.kw["bind"].url)
    engine, new_sessions = create_session_factory(url)
    monkeypatch.setattr(main, "projects", ProjectRepository(new_sessions))
    reopened = client.get(f"/api/v1/projects/{project['id']}")
    assert (
        reopened.status_code == 200 and reopened.json()["cad_ir"] == project["cad_ir"]
    )
    assert reopened.json()["versions"][0]["created_at"].endswith("+00:00")
    downloaded = client.get(f"/api/v1/projects/{project['id']}/cad-ir")
    assert downloaded.json() == project["cad_ir"]
    assert "attachment" in downloaded.headers["content-disposition"]
    engine.dispose()


def test_import_existing_order_and_refuse_foreign_source(project_client):
    client, protocol = project_client
    original = create(client)
    ready(original, protocol)
    source = original["versions"][0]["order_id"]
    imported = client.post(
        "/api/v1/projects", json={"name": "Копия", "source_order_id": source}
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["cad_ir"] == original["cad_ir"]
    assert len(protocol.repo.jobs) == 1
    other = TestClient(main.app)
    session = signed_up(other, "outsider@example.com")
    other.headers[CSRF_HEADER] = session["csrf_token"]
    assert (
        other.post(
            "/api/v1/projects", json={"name": "Копия", "source_order_id": source}
        ).status_code
        == 404
    )


def test_real_milestone_through_worker_uploads_and_downloads(project_client, tmp_path):
    pytest.importorskip("build123d")
    from cad_worker.__main__ import main as cad_worker

    client, protocol = project_client
    worker_client = TestClient(main.app)
    registration = worker_client.post(
        "/api/v1/workers/register",
        json={
            "enrollment_token": main.settings.worker_enrollment_token,
            "worker_name": "project-real-geometry",
            "app_version": "1.0",
        },
    ).json()
    headers = {"Authorization": f"Bearer {registration['credential']}"}

    def build_current(project):
        claim_response = worker_client.post(
            "/api/v1/workers/claim",
            headers=headers,
            json={
                "protocol_version": "1.0",
                "worker_id": registration["worker_id"],
                "capabilities": ["CAD_BUILD"],
                "supported_cad_ir": [CAD_IR_VERSION],
                "available_slots": 1,
                "capability_manifest": mvp_manifest(),
            },
        )
        assert claim_response.status_code == 200, claim_response.text
        claim = claim_response.json()["job"]
        assert claim is not None
        manifest = worker_client.get(claim["manifest_url"], headers=headers).json()
        source = worker_client.get(
            manifest["inputs"][0]["download_url"], headers=headers
        )
        job_dir = tmp_path / f"real-v{project['revision']}"
        job_dir.mkdir()
        (job_dir / "cad-ir.json").write_bytes(source.content)
        assert cad_worker(["build", "--job", str(job_dir)]) == 0
        delivered = []
        for kind, filename in (
            ("STEP", "model.step"),
            ("STL", "model.stl"),
            ("VALIDATION_REPORT", "validation-report.json"),
        ):
            content = (job_dir / "output" / filename).read_bytes()
            uploaded = worker_client.put(
                f"/api/v1/workers/jobs/{claim['job_id']}/artifacts/{kind}",
                headers={
                    **headers,
                    "x-content-sha256": hashlib.sha256(content).hexdigest(),
                },
                content=content,
            )
            assert uploaded.status_code == 200, uploaded.text
            delivered.append(uploaded.json())
        finished = worker_client.post(
            f"/api/v1/workers/jobs/{claim['job_id']}/complete",
            headers=headers,
            json={
                "job_id": claim["job_id"],
                "idempotency_key": claim["idempotency_key"],
                "result": {"status": "success"},
                "artifacts": delivered,
            },
        )
        assert finished.status_code == 200, finished.text
        state = client.get(f"/api/v1/projects/{project['id']}").json()
        assert state["status"] == "READY", state
        return state

    project = build_current(create(client))
    for operation in (
        {"kind": "parameters", "changes": {"p_width": 140}},
        {"kind": "text", "text": "длина 90"},
        {"kind": "text", "text": "увеличь глубину на 10"},
        {"kind": "text", "text": "добавь отверстие диаметром 6 x 0 y 0"},
    ):
        response = edit(client, project, **operation)
        assert response.status_code == 201, response.text
        project = build_current(response.json())
    # A fresh repository and fresh authenticated browser open the saved project.
    main.projects = ProjectRepository(main.projects.sessions)
    reopened = client.get(f"/api/v1/projects/{project['id']}").json()
    assert reopened["revision"] == 5 and reopened["cad_ir"] == project["cad_ir"]
    assert reopened["cad_ir"]["expectations"][0]["size_mm"] == {
        "x": 140,
        "y": 90,
        "z": 50,
    }
    assert all(job.job_type == JobType.BUILD_CAD for job in protocol.repo.jobs.values())
    for kind in ("STL", "STEP"):
        artifact = next(a for a in reopened["artifacts"] if a["type"] == kind)
        result = client.get(artifact["download_url"])
        assert result.status_code == 200 and len(result.content) > 1000
