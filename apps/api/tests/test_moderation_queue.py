"""No part reaches a customer without somebody having looked at it.

`automatic_acceptance` was effectively always true: an order went to `READY` the
moment a build delivered a STEP and an STL, and no person was involved at any
point. For a pilot that is not acceptable, and the reason is specific rather than
nervous — the model can produce a document that is canonically valid, builds a
closed manifold, measures exactly what it declares, and is **not the part on the
drawing**. The shape claim catches a great deal of that. The difference between a
great deal and all of it is what an operator is for.

What is tested here is mostly what must *not* happen: a customer approving their
own order, an approval of a version the operator never saw, an operator's decision
resurrecting an order the customer cancelled, and — checked by enumeration rather
than by one example — any path at all that reaches `READY` without leaving a row
saying who released it.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import pytest
from app.accounts import CSRF_HEADER, Role
from app.contracts import OrderStatus
from app.main import app
from app.orders.review import DECISION_TARGET, ReviewDecision
from app.workers.artifact_store import LocalArtifactStore
from cad_ir.canonical import CAD_IR_VERSION
from fastapi.testclient import TestClient
from tests.drawing_fixture import TINY_PNG
from tests.test_worker_api import memory_protocol, mvp_manifest

MANUAL = {"x-manual-api-token": "local-development-manual-api-token-change-me"}
ENROLLMENT = "local-development-enrollment-token-change-me"
GOOD_PASSWORD = "correct horse battery staple"


@pytest.fixture()
def service(monkeypatch, tmp_path):
    """A held queue by default: `automatic_acceptance` is off, as it ships."""
    protocol = memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path, 5_000_000))
    monkeypatch.setattr("app.main.settings.automatic_acceptance", False, raising=False)
    return protocol, TestClient(app), tmp_path


def drawing_order(client: TestClient, headers=MANUAL) -> str:
    created = client.post(
        "/api/v1/drawing-jobs", headers={**headers, "content-type": "image/png"}, content=TINY_PNG
    )
    assert created.status_code == 201, created.text
    return created.json()["order_id"]


def build_and_deliver(client: TestClient, root, order_id: str) -> str:
    """Drive one order all the way to a delivered model, the way a worker does.

    Registers, claims, uploads the two files a finished build owes and reports the
    completion. Nothing here is a shortcut past the API: the completion endpoint is
    what decides whether the order is held, so a test that wrote the artifacts
    directly would be testing nothing.
    """
    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": ENROLLMENT, "worker_name": f"w-{uuid4()}", "app_version": "0.1.0",
    }).json()
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    claimed = client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": registered["worker_id"],
        "capabilities": ["AI_DRAWING", "CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION],
        "available_slots": 1, "capability_manifest": mvp_manifest(),
    }).json()["job"]
    assert claimed is not None
    job_id = claimed["job_id"]

    artifacts = []
    for kind, body in (("STEP", b"ISO-10303-21;\nENDSEC;\n"), ("STL", b"solid x\nendsolid x\n")):
        uploaded = client.put(
            f"/api/v1/workers/jobs/{job_id}/artifacts/{kind}",
            headers={**headers, "x-content-sha256": hashlib.sha256(body).hexdigest()},
            content=body,
        )
        assert uploaded.status_code in (200, 201), uploaded.text
        artifacts.append(uploaded.json())
    done = client.post(
        f"/api/v1/workers/jobs/{job_id}/complete",
        headers=headers,
        json={
            "job_id": job_id,
            "idempotency_key": claimed["idempotency_key"],
            "result": {"status": "COMPLETED"},
            "artifacts": [
                {"type": item["type"], "object_key": item["object_key"],
                 "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
                for item in artifacts
            ],
        },
    )
    assert done.status_code == 200, done.text
    return job_id


def status_of(client: TestClient, order_id: str) -> str:
    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL)
    assert answered.status_code == 200, answered.text
    return answered.json()["status"]


def queue(client: TestClient) -> list[dict]:
    page = client.get("/api/v1/operator/orders", headers=MANUAL)
    assert page.status_code == 200, page.text
    return page.json()["orders"]


# --- the hold -------------------------------------------------------------------


def test_a_finished_build_waits_for_a_person(service):
    _, client, root = service
    order_id = drawing_order(client)

    build_and_deliver(client, root, order_id)

    assert status_of(client, order_id) == OrderStatus.MANUAL_REVIEW.value
    assert [row["order_id"] for row in queue(client)] == [order_id]


def test_with_automatic_acceptance_the_order_goes_straight_through(service, monkeypatch):
    """The other branch, tested rather than assumed.

    A setting whose `True` case nobody exercises is a setting that stops working
    quietly — and this is the case that was the *only* behaviour until now.
    """
    _, client, root = service
    monkeypatch.setattr("app.main.settings.automatic_acceptance", True, raising=False)
    order_id = drawing_order(client)

    build_and_deliver(client, root, order_id)

    assert status_of(client, order_id) == OrderStatus.READY.value
    assert queue(client) == []


def test_a_build_that_delivered_nothing_is_not_held(service):
    """The hold is on a delivered model, not on any completion at all.

    An analysis that stopped to ask a question is finished work with no part in it,
    and putting that in front of an operator would fill the queue with orders where
    there is nothing to look at.
    """
    _, client, _ = service
    order_id = drawing_order(client)

    assert status_of(client, order_id) == OrderStatus.WAITING_FOR_LOCAL_WORKER.value
    assert queue(client) == []


# --- deciding -------------------------------------------------------------------


def test_an_operator_approves_and_the_customer_gets_the_model(service):
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    approved = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "approve", "expected_version": 1},
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == OrderStatus.READY.value
    assert status_of(client, order_id) == OrderStatus.READY.value
    assert queue(client) == []


def test_a_rejected_order_does_not_read_as_ready(service):
    """The files the operator rejected are still in the artifact store.

    Which is why `READY` and `FAILED` had to become *stored* decisions: without
    that, `pipeline_status` would look at the delivered STEP and STL, see a model,
    and tell the customer their part was ready — the one the operator had just
    said was wrong.
    """
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    rejected = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "reject", "expected_version": 1, "reason": "the bore is on the wrong face"},
    )

    assert rejected.status_code == 200, rejected.text
    assert status_of(client, order_id) == OrderStatus.FAILED.value


def test_a_rejection_without_a_reason_is_refused(service):
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    for decision in ("reject", "request_changes"):
        refused = client.post(
            f"/api/v1/operator/orders/{order_id}/review",
            headers=MANUAL,
            json={"decision": decision, "expected_version": 1},
        )
        assert refused.status_code == 422, decision
    # Approval needs none: "yes" is complete on its own.
    assert client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "approve", "expected_version": 1},
    ).status_code == 200


def test_requesting_changes_sends_the_drawing_back_with_the_note(service):
    """A round, with something new in it.

    Without the note this would re-run identical inputs through the same reading
    stage and get an identical document — a button that appears to do something.
    """
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    sent_back = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={
            "decision": "request_changes",
            "expected_version": 1,
            "reason": "the flange thickness was read as the overall height",
        },
    )

    assert sent_back.status_code == 200, sent_back.text
    answered = client.get(f"/api/v1/drawing-jobs/{order_id}", headers=MANUAL).json()
    assert answered["round"] == 1
    assert answered["status"] == OrderStatus.WAITING_FOR_LOCAL_WORKER.value
    # The note is a job input the worker downloads, beside the drawing and the
    # previous reading, and it is what makes the next attempt different.
    note = json.loads(
        (root / "jobs" / answered["job_id"] / "input" / "operator-note.json").read_text("utf-8")
    )
    assert "flange thickness" in note["note"]
    assert queue(client) == []


def test_the_note_reaches_the_worker_as_a_named_input(service):
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)
    client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "request_changes", "expected_version": 1, "reason": "read the bore again"},
    )

    registered = client.post("/api/v1/workers/register", json={
        "enrollment_token": ENROLLMENT, "worker_name": f"w-{uuid4()}", "app_version": "0.1.0",
    }).json()
    headers = {"Authorization": f"Bearer {registered['credential']}"}
    claimed = client.post("/api/v1/workers/claim", headers=headers, json={
        "protocol_version": "1.0", "worker_id": registered["worker_id"],
        "capabilities": ["AI_DRAWING", "CAD_BUILD"], "supported_cad_ir": [CAD_IR_VERSION],
        "available_slots": 1, "capability_manifest": mvp_manifest(),
    }).json()["job"]
    manifest = client.get(f"/api/v1/workers/jobs/{claimed['job_id']}/manifest", headers=headers).json()

    note = next(item for item in manifest["inputs"] if item["kind"] == "operator_note")
    assert note["local_name"] == "operator-note.json"
    fetched = client.get(
        f"/api/v1/workers/jobs/{claimed['job_id']}/input/operator-note", headers=headers
    )
    assert fetched.status_code == 200
    assert "read the bore again" in fetched.text


# --- and the ways it must not work ---------------------------------------------


def test_a_customer_cannot_approve_their_own_order(service):
    """404 rather than 403: a 403 confirms the endpoint is there and worth attacking."""
    _, client, root = service
    from app.main import accounts

    accounts.register("ivan@example.com", GOOD_PASSWORD, Role.CUSTOMER)
    signed = client.post(
        "/api/v1/auth/sign-in", json={"email": "ivan@example.com", "password": GOOD_PASSWORD}
    )
    assert signed.status_code == 200, signed.text
    csrf = signed.json()["csrf_token"]
    order_id = drawing_order(client, headers={CSRF_HEADER: csrf})
    build_and_deliver(client, root, order_id)

    assert client.get("/api/v1/operator/orders").status_code == 404
    approved = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers={CSRF_HEADER: csrf},
        json={"decision": "approve", "expected_version": 1},
    )

    assert approved.status_code == 404
    # And the order is still held, so a refused attempt has changed nothing.
    assert status_of(client, order_id) == OrderStatus.MANUAL_REVIEW.value


def test_approving_a_version_the_operator_did_not_see_is_a_conflict(service):
    """The mechanism already existed and had nothing using it.

    `expected_version` is not optional and is not defaulted: an approval that says
    "whatever version it is now" is an approval of something the operator has not
    looked at.
    """
    _, client, root = service
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    stale = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "approve", "expected_version": 0},
    )

    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "ORDER_VERSION_CONFLICT"
    assert status_of(client, order_id) == OrderStatus.MANUAL_REVIEW.value
    # A refused decision leaves no audit row: the queue's record must not fill up
    # with things that did not happen.
    assert client.get(
        f"/api/v1/operator/orders/{order_id}/reviews", headers=MANUAL
    ).json() == []


def test_an_order_cancelled_while_it_waited_is_not_resurrected(service):
    """A decision outranks an observation, and the customer decided first.

    The build finishes either way — cancelling does not reach into the worker — so
    the artifacts exist and the operator can see the order. What must not happen is
    an approval turning a cancelled order back into a live one.
    """
    _, client, root = service
    order_id = drawing_order(client)
    cancelled = client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=MANUAL,
        json={"expected_version": 0, "target_status": "CANCELLED"},
    )
    assert cancelled.status_code == 200, cancelled.text

    build_and_deliver(client, root, order_id)

    # Never entered the queue: the hold is refused by the state machine, which is
    # the same rule that stops it being reached from anywhere else.
    assert status_of(client, order_id) == OrderStatus.CANCELLED.value
    assert queue(client) == []
    approved = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers=MANUAL,
        json={"decision": "approve", "expected_version": 1},
    )
    assert approved.status_code == 409
    assert status_of(client, order_id) == OrderStatus.CANCELLED.value


# --- the property, not an example ----------------------------------------------


def test_no_decision_reaches_ready_without_an_audit_row(service):
    """Every decision, enumerated, rather than the one that happens to be approval.

    A log line would not do. A log rotates, is not queryable, and cannot be joined
    to the order it is about — and the question this has to answer months later is
    "who released this part, and what did they say", which is exactly what a rotated
    log cannot answer.
    """
    _, client, root = service

    for decision in ReviewDecision:
        order_id = drawing_order(client)
        build_and_deliver(client, root, order_id)
        answer = client.post(
            f"/api/v1/operator/orders/{order_id}/review",
            headers=MANUAL,
            json={"decision": decision.value, "expected_version": 1, "reason": "measured"},
        )
        assert answer.status_code == 200, (decision, answer.text)

        trail = client.get(
            f"/api/v1/operator/orders/{order_id}/reviews", headers=MANUAL
        ).json()
        assert len(trail) == 1, decision
        row = trail[0]
        assert row["decision"] == decision.value
        assert row["order_status_after"] == DECISION_TARGET[decision].value
        assert row["order_version_before"] == 1
        assert row["reason"] == "measured"
        # The manual operator key is not a person, and the trail says so rather
        # than naming a user who does not exist.
        assert row["reviewer_id"] is None


def test_the_decision_names_the_operator_who_made_it(service):
    _, client, root = service
    from app.main import accounts
    from app.accounts.passwords import totp_code

    operator, secret = accounts.register("op@example.com", GOOD_PASSWORD, Role.OPERATOR)
    order_id = drawing_order(client)
    build_and_deliver(client, root, order_id)

    signed = client.post("/api/v1/auth/sign-in", json={
        "email": "op@example.com", "password": GOOD_PASSWORD, "totp": totp_code(secret),
    })
    assert signed.status_code == 200, signed.text
    approved = client.post(
        f"/api/v1/operator/orders/{order_id}/review",
        headers={CSRF_HEADER: signed.json()["csrf_token"]},
        json={"decision": "approve", "expected_version": 1},
    )

    assert approved.status_code == 200, approved.text
    trail = client.get(f"/api/v1/operator/orders/{order_id}/reviews", headers=MANUAL).json()
    assert UUID(trail[0]["reviewer_id"]) == operator.id


def test_the_api_and_the_internal_decision_enums_say_the_same_three_words():
    from app.contracts import ReviewDecisionName

    assert {name.value for name in ReviewDecisionName} == {
        decision.value for decision in ReviewDecision
    }
    assert set(DECISION_TARGET) == set(ReviewDecision)
