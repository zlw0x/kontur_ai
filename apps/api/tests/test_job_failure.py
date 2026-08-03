"""A job that failed says so, and only the worker holding it may say it.

Before this, `JobStatus` had PENDING, LEASED and COMPLETED. A build that failed
went back to PENDING, was re-leased up to `max_attempts`, and then stayed there —
and the drawing endpoint reports a PENDING job as "waiting to start". Forever,
and indistinguishable from a queue with no worker on it. The customer was never
told, because there was nothing to tell them with.

These are about who may end a job and what survives afterwards. That the worker
*decides* correctly when to send one is `BuildFeedbackTests`, on the other side.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.contracts import JobStatus
from app.main import app
from app.workers.artifact_store import LocalArtifactStore
from cad_ir.canonical import CAD_IR_VERSION
from tests.test_worker_api import memory_protocol, mvp_manifest

MANUAL = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
FIXTURE = Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json"


def _enrol(client: TestClient, name: str = "failing-worker") -> tuple[dict, str]:
    """Enrol a worker. The name matters: re-enrolling one rotates its credential
    and keeps its id, so two workers need two names or they are one worker."""
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": "local-development-enrollment-token-change-me",
        "worker_name": name, "app_version": "0.1.0",
    }).json()
    return {"Authorization": f"Bearer {registered['credential']}"}, registered["worker_id"]


def _claim(client: TestClient, headers: dict, worker_id: str) -> dict:
    return client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": worker_id,
        "capabilities": ["CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION],
        "available_slots": 1, "capability_manifest": mvp_manifest(),
    }).json()["job"]


@pytest.fixture()
def job(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    client = TestClient(app)
    created = client.post("/api/v1/manual/cad-jobs", headers=MANUAL, json={
        "cad_ir": json.loads(FIXTURE.read_text(encoding="utf-8")),
        "requested_formats": ["step", "stl"],
    })
    assert created.status_code == 201
    headers, worker_id = _enrol(client)
    claimed = _claim(client, headers, worker_id)
    return client, protocol, headers, claimed


def test_a_worker_that_gave_up_records_why(job):
    client, protocol, headers, claimed = job

    failed = client.post(
        f"/api/v1/workers/jobs/{claimed['job_id']}/fail",
        headers=headers,
        json={"job_id": claimed["job_id"], "code": "GEOMETRY_VALIDATION_FAILED",
              "message": "bounding_box: expected [60.0, 30.0, 8.0], measured [64.0, 30.0, 8.0]."},
    )

    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    row = protocol.repo.jobs[UUID(claimed["job_id"])]
    assert row.status is JobStatus.FAILED
    assert row.failure_code == "GEOMETRY_VALIDATION_FAILED"
    # The lease is released. A FAILED job holding a lease would keep a slot
    # occupied on a worker that has already moved on.
    assert row.lease_owner is None and row.lease_expires_at is None


def test_the_claim_tells_the_worker_how_many_attempts_it_gets(job):
    """Without it, "this is the last try" is a number written down twice."""
    _, _, _, claimed = job

    assert claimed["attempt"] == 1
    assert claimed["max_attempts"] >= 1


def test_only_the_worker_holding_the_lease_may_end_the_job(job):
    """Otherwise a worker whose lease lapsed mid-build can fail somebody else's job.

    The job it would be failing is the one another worker has since claimed and
    may be about to finish.
    """
    client, _, _, claimed = job
    other, other_id = _enrol(client, name="a-different-worker")

    refused = client.post(
        f"/api/v1/workers/jobs/{claimed['job_id']}/fail",
        headers=other,
        json={"job_id": claimed["job_id"], "code": "ENGINE_NOT_AVAILABLE", "message": "no engine"},
    )

    assert refused.status_code >= 400


def test_a_completed_job_cannot_be_failed_afterwards(job):
    """Completion is the stronger statement: the artifacts exist and were verified.

    A late report from a worker that lost its lease must not take that away.
    """
    client, protocol, headers, claimed = job
    job_id = claimed["job_id"]
    # Completed through the protocol rather than the upload endpoints: the
    # artifact object keys are server-generated, and rebuilding them here would
    # test the store instead of the rule this is about.
    worker = next(iter(protocol.repo.workers.values()))
    protocol.complete(worker, UUID(job_id), claimed["idempotency_key"])

    late = client.post(f"/api/v1/workers/jobs/{job_id}/fail", headers=headers, json={
        "job_id": job_id, "code": "ENGINE_NOT_AVAILABLE", "message": "too late"})

    assert late.json()["status"] == "COMPLETED"
    assert protocol.repo.jobs[UUID(job_id)].status is JobStatus.COMPLETED


def test_a_failure_message_that_could_carry_a_path_is_refused(job):
    """Everything sent here can reach a browser, so the shape is pinned.

    The worker already sends safe text; this is the API not taking its word for
    the *shape* of the code, which is what a rendered page keys off.
    """
    client, _, headers, claimed = job

    refused = client.post(f"/api/v1/workers/jobs/{claimed['job_id']}/fail", headers=headers, json={
        "job_id": claimed["job_id"], "code": "C:\\work\\build.exe", "message": "x"})

    assert refused.status_code == 422
