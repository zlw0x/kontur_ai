"""What the customer's page is told, in one vocabulary, and who gets the last word.

Until the orders table landed, `get_drawing_job` computed its answer like this:

    status = ("READY" if has_model
              else "WAITING_FOR_USER_ANSWERS" if questions
              else job.status.value)

The first two branches answer in `OrderStatus`; the third answers in `JobStatus`.
So a customer waiting in the queue was told `PENDING` and one being built was told
`LEASED` — words from the job's vocabulary, about a thing that is not a job — and
the web page's status map had to carry both sets because either could arrive.

Nothing here is about durability; that is `test_order_repository.py`. These are
about the answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.contracts import JobStatus, JobType, OrderStatus, WorkerCapability
from app.main import app
from app.orders.progress import order_status, pipeline_status
from app.workers.artifact_store import LocalArtifactStore
from app.workers.protocol import Job
from cad_ir.canonical import CAD_IR_VERSION
from tests.drawing_fixture import TINY_PNG
from tests.test_worker_api import memory_protocol, mvp_manifest

MANUAL = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
ENROLLMENT = "local-development-enrollment-token-change-me"


@pytest.fixture()
def service(monkeypatch, tmp_path):
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 1_000_000))
    return protocol, TestClient(app), tmp_path


def drawing_order(client: TestClient) -> str:
    created = client.post(
        "/api/v1/drawing-jobs",
        headers={**MANUAL, "content-type": "image/png"},
        content=TINY_PNG,
    )
    assert created.status_code == 201, created.text
    return created.json()["order_id"]


def claim_it(client: TestClient) -> None:
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": ENROLLMENT, "worker_name": f"w-{uuid4()}", "app_version": "0.1.0",
    }).json()
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    claimed = client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": registered["worker_id"],
        "capabilities": ["AI_DRAWING", "CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION],
        "available_slots": 1, "capability_manifest": mvp_manifest(),
    })
    assert claimed.json()["job"] is not None


def status_of(client: TestClient, order_id: str) -> str:
    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL)
    assert answered.status_code == 200, answered.text
    return answered.json()["status"]


# --- one vocabulary -----------------------------------------------------------


def test_a_queued_order_is_waiting_for_a_worker_and_not_pending(service):
    _, client, _ = service
    order_id = drawing_order(client)

    # `PENDING` is a fact about a row in `jobs`. What the customer has is an order,
    # and the order is waiting for a worker.
    assert status_of(client, order_id) == "WAITING_FOR_LOCAL_WORKER"


def test_a_claimed_drawing_order_names_the_stage_rather_than_the_lease(service):
    _, client, _ = service
    order_id = drawing_order(client)

    claim_it(client)

    # `LEASED` says a worker holds it and says nothing about what it is doing. The
    # job's type does, and it is the only thing that does.
    assert status_of(client, order_id) == "DRAWING_ANALYSIS"


def test_a_leased_build_is_cad_building(service):
    """The same lease, a different job type, a different answer — which is why the
    stage cannot be read off `JobStatus` alone.

    A manual CAD-IR submission is the shortest way to an order whose only job is a
    `BUILD_CAD`; the drawing cycle reaches the same state a round later.
    """
    _, client, _ = service
    fixture = json.loads(
        (Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir" / "plate.json")
        .read_text(encoding="utf-8")
    )
    created = client.post("/api/v1/manual/cad-jobs", headers=MANUAL, json={
        "cad_ir": fixture, "requested_formats": ["step", "stl"],
    })
    assert created.status_code == 201, created.text
    order_id = created.json()["order_id"]
    assert status_of(client, order_id) == "WAITING_FOR_LOCAL_WORKER"

    claim_it(client)

    assert status_of(client, order_id) == "CAD_BUILDING"


@pytest.mark.parametrize("job_status", list(JobStatus))
@pytest.mark.parametrize("job_type", list(JobType))
@pytest.mark.parametrize("has_model,has_questions", [(False, False), (False, True), (True, False)])
def test_no_combination_answers_in_the_job_s_vocabulary(
    job_status, job_type, has_model, has_questions
):
    """The mixture refused as a class rather than case by case.

    Every state a job can be in, for every kind of job, with and without the
    artifacts that outrank it. `OrderStatus` and `JobStatus` share four names —
    READY is not among them but FAILED and PAUSED are — so it is not enough that the
    string looks familiar: what must not happen is a branch returning `PENDING`,
    `LEASED` or `COMPLETED`, none of which the page has copy for.
    """
    answered = pipeline_status(
        SimpleNamespace(status=job_status, job_type=job_type),
        has_model=has_model,
        has_questions=has_questions,
    )

    assert isinstance(answered, OrderStatus)
    assert answered.value not in {"PENDING", "LEASED", "COMPLETED"}


def test_a_decided_order_outranks_every_state_a_job_can_be_in():
    """Paired with the case above, and the reason `order_status` exists at all."""
    for status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.MANUAL_REVIEW):
        for job_status in JobStatus:
            answered = order_status(
                SimpleNamespace(status=status),
                SimpleNamespace(status=job_status, job_type=JobType.BUILD_CAD),
                has_model=True,
                has_questions=True,
            )
            assert answered == status


# --- who gets the last word ---------------------------------------------------


def test_a_cancelled_order_stays_cancelled_while_its_job_runs_on(service):
    """A decision outranks an observation.

    Cancelling does not reach into the worker and stop the build — the worker holds
    a lease and will finish, and its artifacts will be stored. What must not happen
    is the page reporting progress on an order the customer cancelled.
    """
    _, client, _ = service
    order_id = drawing_order(client)
    cancelled = client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=MANUAL,
        json={"expected_version": 0, "target_status": "CANCELLED"},
    )
    assert cancelled.status_code == 200, cancelled.text

    claim_it(client)

    assert status_of(client, order_id) == "CANCELLED"


def test_an_order_held_for_review_says_so_rather_than_reporting_the_queue(service):
    _, client, _ = service
    order_id = drawing_order(client)
    client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=MANUAL,
        json={"expected_version": 0, "target_status": "DRAWING_ANALYSIS"},
    )
    held = client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=MANUAL,
        json={"expected_version": 1, "target_status": "MANUAL_REVIEW"},
    )
    assert held.status_code == 200, held.text

    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()

    assert answered["status"] == "MANUAL_REVIEW"
    # And no scheduler summary, because the order is not waiting on the scheduler.
    assert answered["waiting_reason"] is None


# --- an order written before the table existed ---------------------------------


def test_an_order_that_predates_the_table_is_adopted_rather_than_lost(service):
    """Until 0008 the drawing cycle's tracking was a JSON file in the artifact store.

    Orders created then have only that file. Dropping the read would strand every
    one of them behind a 404, so it is read once, a row is written from it, and
    every later request takes the row. Written through the store's own writer, so
    the test cannot drift from the format the reader parses.
    """
    protocol, client, tmp_path = service
    order_id, job_id = uuid4(), uuid4()
    store = LocalArtifactStore(tmp_path, 1_000_000)
    store.put_drawing(job_id, TINY_PNG, ".png")
    store.put_drawing_tracking(order_id, job_id, job_id, 2)
    protocol.enqueue(Job(job_id, order_id, JobType.ANALYZE_DRAWING, f"sha256:{uuid4()}",
                         {WorkerCapability.AI_DRAWING}, CAD_IR_VERSION))

    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL)

    assert answered.status_code == 200, answered.text
    assert answered.json()["round"] == 2
    assert answered.json()["status"] == "WAITING_FOR_LOCAL_WORKER"
    # Adopted, not merely read: the next request is served from the row.
    from app.main import orders

    adopted = orders.get(order_id)
    assert (adopted.latest_job_id, adopted.source_job_id) == (job_id, job_id)
    assert adopted.clarification_round == 2


def test_an_order_with_neither_a_row_nor_a_file_is_a_404(service):
    _, client, _ = service

    assert client.get(f"/api/v1/drawing-jobs/{uuid4()}", headers=MANUAL).status_code == 404


def test_the_round_the_page_shows_comes_from_the_order(service):
    """It came from a dictionary keyed by order id, refilled from a JSON file on a
    miss. A restart between two rounds reset it to whatever the file last held."""
    _, client, _ = service
    order_id = drawing_order(client)
    from app.main import orders

    orders.record_round(UUID(order_id), latest_job_id=orders.get(UUID(order_id)).latest_job_id,
                        clarification_round=3)

    assert client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()["round"] == 3


def test_two_polls_adopting_one_pre_table_order_do_not_collide(service, monkeypatch):
    """The page polls every three seconds, so this is not hypothetical.

    Both requests find no row, both read the tracking file, and both try to insert.
    One loses to the primary key. Without the branch that catches it the customer
    gets a 500 on a request that had already succeeded elsewhere.

    Simulated by making the lookup miss once *after* the row exists, which is what
    the losing request sees.
    """
    protocol, client, tmp_path = service
    order_id, job_id = uuid4(), uuid4()
    store = LocalArtifactStore(tmp_path, 1_000_000)
    store.put_drawing(job_id, TINY_PNG, ".png")
    store.put_drawing_tracking(order_id, job_id, job_id, 1)
    protocol.enqueue(Job(job_id, order_id, JobType.ANALYZE_DRAWING, f"sha256:{uuid4()}",
                         {WorkerCapability.AI_DRAWING}, CAD_IR_VERSION))
    assert client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).status_code == 200

    from app.main import orders

    real_get, missed = orders.get, []

    def miss_once(wanted):
        if not missed:
            missed.append(wanted)
            return None
        return real_get(wanted)

    monkeypatch.setattr(orders, "get", miss_once)

    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL)

    assert answered.status_code == 200
    assert answered.json()["round"] == 1
