"""One machine, one person: no sign-in, no queue (`OPEN_LOCAL_ACCESS`).

Everything this switch turns off exists for a service strangers can reach. On a
laptop with nobody else on it they are four ways to fail before the drawing is even
read, and a person testing one thing should not have to pass all four.

What is asserted here is the shape of the promise: it works without a credential,
it still gives the order an owner, it does not hold the build for anybody — and it
**cannot be switched on outside `local`**, which is the only reason it is safe to
have at all.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from tests.drawing_fixture import TINY_PNG


@pytest.fixture()
def open_client(monkeypatch, tmp_path):
    """The API with  on, which is how a laptop runs it."""
    from fastapi.testclient import TestClient

    from app.input.quarantine import Quarantine
    from app.main import app
    from app.workers.artifact_store import LocalArtifactStore
    from tests.test_accounts import memory_protocol

    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    monkeypatch.setattr("app.main.settings.open_local_access", True)
    return TestClient(app)


def test_the_suite_pins_it_off_by_default():
    """`conftest.py` forces it off, whatever the developer's `.env` says.

    Turning it on to try a drawing in a browser made sixteen tests fail, and each was
    right to: they assert that an unauthenticated request is refused. The setting was
    not wrong and neither were they — what was missing was the line keeping them apart.
    """
    from app.config import settings

    assert settings.open_local_access is False


def test_it_cannot_be_switched_on_outside_local():
    """The whole of its safety. A deployment refuses to start rather than trust anybody."""
    with pytest.raises(ValueError, match="only allowed in the local environment"):
        Settings(
            environment="production",
            open_local_access=True,
            worker_enrollment_token="x" * 40,
            manual_api_token="y" * 40,
            database_url="postgresql+psycopg://user:pass@host/db",
        )


def test_a_hold_for_review_follows_from_it():
    """Holding a build for an operator who is the customer is a queue waiting for itself."""
    assert Settings(environment="local").hold_for_review is True
    assert Settings(environment="local", open_local_access=True).hold_for_review is False
    assert Settings(environment="local", automatic_acceptance=True).hold_for_review is False


def test_an_upload_needs_no_credential_and_the_order_still_has_an_owner(open_client):
    """No sign-in, no CSRF token — and an owner, because everything downstream reads one."""
    created = open_client.post(
        "/api/v1/drawing-jobs", headers={"content-type": "image/png"}, content=TINY_PNG
    )
    assert created.status_code == 201, created.text

    order_id = created.json()["order_id"]
    # And the same anonymous caller can read it back, which is the half that was
    # failing for a customer who had signed in and was told to sign in.
    read = open_client.get(f"/api/v1/drawing-jobs/{order_id}")
    assert read.status_code == 200

    me = open_client.get("/api/v1/auth/me")
    assert me.status_code == 200, "the page decides what to show from this"
    assert me.json()["email"] == "local@localhost"
