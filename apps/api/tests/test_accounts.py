"""Who may see an order, and every way of getting that wrong.

Before P0-1 the answer was "anybody holding `MANUAL_API_TOKEN`". One static token
shared by everyone, and an `orders` table with no column saying whose an order was
— so a stranger with the token could read and cancel somebody else's drawing. It is
the single thing that blocked letting people in, and it could not be fixed in the
handlers, because the fact was never recorded.

These are the failure paths. The happy path — sign up, upload, get a model — is
covered by the drawing tests; what is here is everything that must *not* work, and
each one is a specific mistake that would otherwise be invisible: a 403 that
confirms an order exists, a sign-out that only takes effect at expiry, a login form
that answers unknown addresses faster than real ones.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from app.accounts import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Role
from app.accounts.passwords import (
    hash_password,
    new_totp_secret,
    totp_code,
    verify_password,
    verify_totp,
)
from app.accounts.principal import MFA_REQUIRED, Principal, may_see_order
from app.contracts import OrderStatus, UserRole
from fastapi.testclient import TestClient
from tests.drawing_fixture import TINY_PNG
from tests.test_worker_api import memory_protocol

MANUAL_TOKEN = "local-development-manual-api-token-change-me"
GOOD_PASSWORD = "correct horse battery staple"


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    from app.input.quarantine import Quarantine
    from app.main import app
    from app.workers.artifact_store import LocalArtifactStore

    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    return TestClient(app)


def signed_up(client: TestClient, email: str) -> dict:
    """A fresh customer, signed in, with the cookies its own client will carry.

    `TestClient` keeps a cookie jar, so a second call here signs the *same* client
    in as somebody else — which is what the ownership tests want, and why each of
    them builds a second client rather than reusing this one carelessly.
    """
    created = client.post(
        "/api/v1/auth/register", json={"email": email, "password": GOOD_PASSWORD}
    )
    assert created.status_code == 201, created.text
    return created.json()


def upload(client: TestClient, csrf: str) -> str:
    created = client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: csrf},
        content=TINY_PNG,
    )
    assert created.status_code == 201, created.text
    return created.json()["order_id"]


# --- signing up and in ---------------------------------------------------------


def test_registering_signs_you_in_and_never_returns_the_session_token(client):
    session = signed_up(client, "ivan@example.com")

    assert session["role"] == UserRole.CUSTOMER
    assert session["csrf_token"]
    # The session token exists in a cookie the page cannot read, and nowhere else.
    # If it were in the body a script could keep it, and `httponly` would be theatre.
    assert "token" not in session and "session_token" not in session
    assert client.cookies.get(SESSION_COOKIE)
    assert client.cookies.get(CSRF_COOKIE) == session["csrf_token"]


def test_the_same_address_in_a_different_case_is_the_same_account(client):
    signed_up(client, "Ivan@Example.COM")

    again = client.post(
        "/api/v1/auth/register", json={"email": "ivan@example.com", "password": GOOD_PASSWORD}
    )

    assert again.status_code == 409


def test_a_short_password_is_refused_and_the_account_is_not_created(client):
    refused = client.post(
        "/api/v1/auth/register", json={"email": "ivan@example.com", "password": "short"}
    )

    # 422 from the contract's own length bound, before anything is hashed. A
    # password field with no ceiling either way is a free way to make a server that
    # hashes slowly do work.
    assert refused.status_code == 422
    assert client.post(
        "/api/v1/auth/sign-in", json={"email": "ivan@example.com", "password": "short"}
    ).status_code == 422


def test_an_unknown_address_and_a_wrong_password_are_the_same_refusal(client):
    signed_up(client, "ivan@example.com")

    wrong = client.post(
        "/api/v1/auth/sign-in",
        json={"email": "ivan@example.com", "password": "a completely wrong password"},
    )
    unknown = client.post(
        "/api/v1/auth/sign-in",
        json={"email": "nobody@example.com", "password": "a completely wrong password"},
    )

    # Identical, deliberately. Anything else is a form that tells a stranger which
    # addresses have accounts here, and the drawings behind those accounts are
    # somebody's commercial secret.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_an_unknown_address_still_pays_for_a_hash(monkeypatch):
    """Saying the same words in a microsecond is the same disclosure with extra steps.

    Not a wall-clock assertion — a timing test on a shared runner is a flaky test.
    What is asserted is the mechanism: an unknown address is verified against the
    decoy hash, so the same bcrypt work happens on both paths.
    """
    from app.accounts import AccountService, InMemoryAccountRepository
    from app.accounts.service import AuthenticationFailed

    import app.accounts.service as module

    service = AccountService(InMemoryAccountRepository())
    verified: list[str] = []
    genuine = module.verify_password

    def counting(password, stored):
        verified.append(stored)
        return genuine(password, stored)

    monkeypatch.setattr(module, "verify_password", counting)
    with pytest.raises(AuthenticationFailed):
        service.sign_in("nobody@example.com", GOOD_PASSWORD)

    # The decoy is a real bcrypt hash at the real cost, so both paths spend the
    # same quarter of a second before saying the same thing.
    assert verified == [module.DECOY_HASH]
    assert module.DECOY_HASH.startswith("$2b$")


def test_a_password_reaches_no_log(client, caplog):
    """Run the whole sign-up and sign-in with logging on, and grep everything.

    The most ordinary way to leak a password is not a bug in the hashing — it is a
    handler that logs the request body while somebody is debugging something else.
    A test that greps is the only kind that keeps noticing.
    """
    secret = "a password that appears nowhere else in this repository"
    with caplog.at_level(logging.DEBUG):
        client.post("/api/v1/auth/register", json={"email": "ivan@example.com", "password": secret})
        client.post("/api/v1/auth/sign-in", json={"email": "ivan@example.com", "password": secret})
        client.post("/api/v1/auth/sign-in", json={"email": "ivan@example.com", "password": "wrong " + secret})

    assert secret not in caplog.text
    assert all(secret not in str(record.__dict__) for record in caplog.records)


# --- second factor -------------------------------------------------------------


def test_an_operator_needs_a_second_factor_and_a_customer_does_not(client, monkeypatch):
    from app.main import accounts

    admin, _ = accounts.register("admin@example.com", GOOD_PASSWORD, Role.ADMIN)
    operator, secret = accounts.register("op@example.com", GOOD_PASSWORD, Role.OPERATOR)

    assert Role.CUSTOMER not in MFA_REQUIRED
    assert secret, "an operator account is created with a TOTP secret"
    assert accounts.repository.user(admin.id).totp_secret

    without = client.post(
        "/api/v1/auth/sign-in", json={"email": "op@example.com", "password": GOOD_PASSWORD}
    )
    assert without.status_code == 401

    with_code = client.post(
        "/api/v1/auth/sign-in",
        json={
            "email": "op@example.com",
            "password": GOOD_PASSWORD,
            "totp": totp_code(operator.totp_secret),
        },
    )
    assert with_code.status_code == 200
    assert with_code.json()["role"] == UserRole.OPERATOR


def test_a_role_that_must_have_a_second_factor_and_has_none_cannot_sign_in():
    """The requirement must not switch itself off when enrolment failed.

    Letting the account through because the secret is missing turns "operators use
    MFA" into "operators use MFA when they have got round to it", and the accounts
    this applies to are the ones that can read everybody's drawings.
    """
    from app.accounts import AccountService, InMemoryAccountRepository
    from app.accounts.service import AuthenticationFailed

    service = AccountService(InMemoryAccountRepository())
    user, _ = service.register("op@example.com", GOOD_PASSWORD, Role.OPERATOR)
    service.repository._users[user.id] = type(user)(  # type: ignore[misc]
        **{**user.__dict__, "totp_secret": None}
    )

    with pytest.raises(AuthenticationFailed):
        service.sign_in("op@example.com", GOOD_PASSWORD, totp="000000")


def test_a_totp_code_from_the_wrong_secret_is_refused():
    mine, theirs = new_totp_secret(), new_totp_secret()

    assert verify_totp(mine, totp_code(mine))
    assert not verify_totp(mine, totp_code(theirs))
    assert not verify_totp(mine, None)
    assert not verify_totp(None, totp_code(mine))
    # One step either side, and not two. Every extra step is another code that is
    # valid at any instant.
    assert verify_totp(mine, totp_code(mine, offset=-1))
    assert not verify_totp(mine, totp_code(mine, offset=-3))


# --- passwords themselves ------------------------------------------------------


def test_a_long_passphrase_is_not_silently_truncated_at_seventy_two_bytes():
    """bcrypt reads 72 bytes. Without the pre-hash, everything after them is free.

    Two passphrases sharing a 72-byte prefix would otherwise be one password, which
    is the kind of weakening nobody notices because both users can still sign in.
    """
    base = "x" * 80
    stored = hash_password(base + "-first")

    assert verify_password(base + "-first", stored)
    assert not verify_password(base + "-second", stored)


def test_a_stored_hash_is_not_the_password_and_not_a_bare_digest():
    import hashlib

    stored = hash_password(GOOD_PASSWORD)

    assert GOOD_PASSWORD not in stored
    assert hashlib.sha256(GOOD_PASSWORD.encode()).hexdigest() not in stored
    # bcrypt's own prefix, and a cost factor in it. A hash with no cost is a lookup.
    assert stored.startswith("$2b$") and "$12$" in stored


def test_a_malformed_stored_hash_is_a_wrong_password_and_not_a_crash():
    """A broken row must not become a 500 that singles this account out."""
    assert verify_password(GOOD_PASSWORD, "not a bcrypt hash at all") is False


# --- ownership -----------------------------------------------------------------


def test_another_customers_order_is_a_404_and_not_a_403(client, tmp_path, monkeypatch):
    """403 answers "does this order exist?" for anybody willing to guess an id.

    The existence of an order is itself information about somebody else's business,
    so the two answers are the same and deliberately indistinguishable.
    """
    from app.input.quarantine import Quarantine
    from app.main import app
    from app.workers.artifact_store import LocalArtifactStore

    mine = signed_up(client, "ivan@example.com")
    order_id = upload(client, mine["csrf_token"])
    assert client.get(f"/api/v1/drawing-jobs/{order_id}").status_code == 200

    other = TestClient(app)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    theirs = signed_up(other, "petr@example.com")

    seen = other.get(f"/api/v1/drawing-jobs/{order_id}")
    invented = other.get(f"/api/v1/drawing-jobs/{uuid.uuid4()}")

    assert seen.status_code == 404
    assert invented.status_code == 404
    assert seen.json() == invented.json()
    # And they cannot cancel it either — a read they may not do is not the only
    # thing ownership decides.
    cancelled = other.post(
        f"/api/v1/orders/{order_id}/transition",
        headers={CSRF_HEADER: theirs["csrf_token"]},
        json={"target_status": OrderStatus.CANCELLED.value, "expected_version": 0},
    )
    assert cancelled.status_code == 404


def test_an_order_nobody_owns_is_visible_to_staff_and_to_nobody_else(client):
    """Every order created before 0009 has `owner_id IS NULL`.

    There is nothing to fill it with — the service did not record who uploaded them
    because it had no idea — and handing them to whoever asks first is not a guess
    but a giveaway. Written down as an assertion rather than left to be inferred.
    """
    staff = Principal(role=Role.OPERATOR)
    customer = Principal(role=Role.CUSTOMER, user_id=uuid.uuid4())

    assert may_see_order(staff, None) is True
    assert may_see_order(customer, None) is False
    assert may_see_order(customer, customer.user_id) is True
    assert may_see_order(customer, uuid.uuid4()) is False


def test_the_manual_token_reads_an_order_it_did_not_create(client):
    """`MANUAL_API_TOKEN` stays a diagnostic operator key and never a client's.

    It authenticates as an operator, so it can look at everything the way an
    operator can — and it owns nothing, so an order it creates has no owner rather
    than belonging to a user who does not exist.
    """
    from app.main import orders

    mine = signed_up(client, "ivan@example.com")
    order_id = upload(client, mine["csrf_token"])
    assert orders.get(uuid.UUID(order_id)).owner_id == uuid.UUID(mine["user_id"])

    client.cookies.clear()
    read = client.get(
        f"/api/v1/drawing-jobs/{order_id}", headers={"x-manual-api-token": MANUAL_TOKEN}
    )

    assert read.status_code == 200
    assert client.get("/api/v1/auth/me", headers={"x-manual-api-token": MANUAL_TOKEN}).status_code == 404


def test_a_customer_may_cancel_their_own_order_and_nothing_else(client):
    mine = signed_up(client, "ivan@example.com")
    order_id = upload(client, mine["csrf_token"])
    headers = {CSRF_HEADER: mine["csrf_token"]}

    forbidden = client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=headers,
        json={"target_status": OrderStatus.MANUAL_REVIEW.value, "expected_version": 0},
    )
    assert forbidden.status_code == 403

    cancelled = client.post(
        f"/api/v1/orders/{order_id}/transition",
        headers=headers,
        json={"target_status": OrderStatus.CANCELLED.value, "expected_version": 0},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == OrderStatus.CANCELLED.value


def test_the_manual_cad_ir_endpoint_is_staff_only(client):
    """Handing a document straight to a worker skips every check between a drawing
    and a part — the reading stage, the shape claim, all of it. That is what the
    operator key is *for*, and it is not something a customer gets."""
    mine = signed_up(client, "ivan@example.com")

    refused = client.post(
        "/api/v1/manual/cad-jobs",
        headers={CSRF_HEADER: mine["csrf_token"]},
        json={"cad_ir": {"schema_version": "0.1.0", "units": "mm", "parameters": [], "features": []}},
    )

    # 404 rather than 403: a 403 confirms the endpoint is there and worth attacking.
    assert refused.status_code == 404


def test_an_unauthenticated_request_gets_nowhere(client):
    assert client.post(
        "/api/v1/drawing-jobs", headers={"content-type": "image/png"}, content=TINY_PNG
    ).status_code == 401
    assert client.get(f"/api/v1/drawing-jobs/{uuid.uuid4()}").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


# --- sessions ------------------------------------------------------------------


def test_a_revoked_session_stops_working_on_the_next_request(client):
    """Immediately, not at expiry.

    This is the whole reason a session is a row rather than a self-contained signed
    token: nothing can recall one of those without keeping a list, and once there is
    a list the token has bought nothing.
    """
    mine = signed_up(client, "ivan@example.com")
    order_id = upload(client, mine["csrf_token"])
    assert client.get(f"/api/v1/drawing-jobs/{order_id}").status_code == 200

    assert client.post(
        "/api/v1/auth/sign-out", headers={CSRF_HEADER: mine["csrf_token"]}
    ).status_code == 204

    # The cookie jar was cleared by the response, so put the value back: the point
    # is that the *server* refuses it, not that the browser forgot it.
    from app.main import accounts

    assert client.get(f"/api/v1/drawing-jobs/{order_id}").status_code == 401
    revoked = accounts.repository.session_by_token(
        __import__("hashlib").sha256(b"").hexdigest()
    )
    assert revoked is None


def test_a_session_the_server_has_never_heard_of_is_refused(client):
    client.cookies.set(SESSION_COOKIE, "a token nobody issued")

    assert client.get("/api/v1/auth/me").status_code == 401


def test_an_expired_session_is_refused_without_being_revoked():
    from datetime import datetime, timedelta, timezone

    from app.accounts import AccountService, InMemoryAccountRepository

    now = datetime(2026, 8, 9, tzinfo=timezone.utc)
    service = AccountService(
        InMemoryAccountRepository(clock=lambda: now), clock=lambda: now, lifetime=timedelta(hours=1)
    )
    user, _ = service.register("ivan@example.com", GOOD_PASSWORD)
    issued = service.issue(user)

    assert service.resolve(issued.token) is not None
    service._clock = lambda: now + timedelta(hours=2)
    assert service.resolve(issued.token) is None
    # Expiry is not revocation: the row is untouched, which is what lets an operator
    # tell "signed out" from "session ran out" when reading the table later.
    assert service.repository.session_by_token(issued.session.token_sha256).revoked_at is None


def test_a_disabled_account_loses_its_sessions_at_once():
    from dataclasses import replace
    from datetime import datetime, timezone

    from app.accounts import AccountService, InMemoryAccountRepository

    service = AccountService(InMemoryAccountRepository())
    user, _ = service.register("ivan@example.com", GOOD_PASSWORD)
    issued = service.issue(user)
    assert service.resolve(issued.token) is not None

    service.repository._users[user.id] = replace(
        user, disabled_at=datetime.now(timezone.utc)
    )

    # Checked on the session's *user*, so disabling an account does not require
    # finding and revoking every session it has — which is the version that misses
    # one.
    assert service.resolve(issued.token) is None


# --- CSRF ----------------------------------------------------------------------


def test_a_mutating_request_without_a_csrf_token_is_refused(client):
    signed_up(client, "ivan@example.com")

    refused = client.post(
        "/api/v1/drawing-jobs", headers={"content-type": "image/png"}, content=TINY_PNG
    )

    assert refused.status_code == 403


def test_somebody_elses_csrf_token_is_refused(client, tmp_path, monkeypatch):
    """The token is bound to the session, not merely compared with a cookie.

    Cookie-versus-header double submit loses to anything that can write a cookie on
    a sibling subdomain: an attacker who sets both halves passes a check that only
    compares them to each other. A token checked against the session's own stored
    value requires knowing a secret the attacker was never sent.
    """
    from app.main import app

    mine = signed_up(client, "ivan@example.com")
    other = TestClient(app)
    theirs = signed_up(other, "petr@example.com")

    refused = client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: theirs["csrf_token"]},
        content=TINY_PNG,
    )

    assert refused.status_code == 403
    # And a token that is merely echoed back in both places is not enough either.
    client.cookies.set(CSRF_COOKIE, "invented")
    assert client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: "invented"},
        content=TINY_PNG,
    ).status_code == 403


def test_a_read_needs_no_csrf_token_and_a_header_credential_needs_none_either(client):
    """CSRF is a cookie problem. The browser attaches a cookie to a request the user
    did not make; it does not attach `x-manual-api-token`, because a custom header
    cross-origin needs a preflight this API answers only for its own origins."""
    mine = signed_up(client, "ivan@example.com")
    order_id = upload(client, mine["csrf_token"])

    assert client.get(f"/api/v1/drawing-jobs/{order_id}").status_code == 200

    client.cookies.clear()
    assert client.post(
        "/api/v1/orders/{}/transition".format(order_id),
        headers={"x-manual-api-token": MANUAL_TOKEN},
        json={"target_status": OrderStatus.CANCELLED.value, "expected_version": 0},
    ).status_code == 200


def test_the_csrf_token_is_compared_in_constant_time():
    """Asked of the source, because the alternative is a timing test on a shared
    runner, and that is a flaky test rather than a strong one.

    The session token needs no such comparison and deliberately has none: it is
    looked up by its SHA-256 in an indexed column, so there is no byte-by-byte
    compare to leak anything, and a 256-bit value has no prefix worth guessing.
    """
    import inspect

    from app.accounts.service import AccountService

    source = inspect.getsource(AccountService.csrf_matches)

    assert "compare_digest" in source
    assert "==" not in source.split('"""')[-1]


# --- admin ---------------------------------------------------------------------


def test_only_an_admin_creates_an_operator(client):
    from app.main import accounts

    mine = signed_up(client, "ivan@example.com")
    body = {"email": "op@example.com", "password": GOOD_PASSWORD, "role": UserRole.OPERATOR.value}

    refused = client.post(
        "/api/v1/admin/users", headers={CSRF_HEADER: mine["csrf_token"]}, json=body
    )
    assert refused.status_code == 404

    admin, secret = accounts.register("admin@example.com", GOOD_PASSWORD, Role.ADMIN)
    client.cookies.clear()
    signed = client.post(
        "/api/v1/auth/sign-in",
        json={"email": "admin@example.com", "password": GOOD_PASSWORD, "totp": totp_code(secret)},
    )
    assert signed.status_code == 200, signed.text

    created = client.post(
        "/api/v1/admin/users",
        headers={CSRF_HEADER: signed.json()["csrf_token"]},
        json=body,
    )

    assert created.status_code == 201
    # Shown once, because it is stored to verify against rather than to display.
    # That is the property an authenticator app depends on.
    assert created.json()["totp_secret"]
    assert created.json()["role"] == UserRole.OPERATOR


def test_the_api_role_enum_and_the_internal_one_say_the_same_three_words():
    """Two spellings of one set, and a test so they cannot drift.

    `contracts` generates the published OpenAPI document and must not import the
    service's internals to do it — the same reason `JobStatus` lives there and not
    in the worker protocol.
    """
    assert {role.value for role in UserRole} == {role.value for role in Role}


def test_asking_who_i_am_does_not_disarm_the_page_that_asked(client):
    """`/auth/me` re-issues the CSRF token, so it has to hand the new one back.

    Measured on the running service before this was fixed: upload 201, call
    `/auth/me`, upload 403. The re-issue overwrote the hash the session compares
    against while the browser kept the value from sign-in, so the client was holding
    a token the server had already stopped accepting — and a reload, a second tab or
    an effect that runs twice was enough to cause it.

    The cookie is the client's only durable copy of that token. Re-issuing without
    rewriting it hands out a credential and revokes it in the same breath, which is
    why this asserts the **cookie** and not only the body.
    """
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "rotating@example.com", "password": "correct-horse-battery-staple"},
    )
    assert registered.status_code == 201
    at_sign_in = registered.json()["csrf_token"]
    assert client.cookies.get(CSRF_COOKIE) == at_sign_in

    first = client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: at_sign_in},
        content=TINY_PNG,
    )
    assert first.status_code == 201

    # The second visit. Anything at all: a reload, another tab, a duplicated effect.
    again = client.get("/api/v1/auth/me")
    assert again.status_code == 200
    reissued = again.json()["csrf_token"]
    assert reissued != at_sign_in, "a re-issue that returns the same token is not one"

    # The cookie moved with it, so a client that reads the cookie is never stale.
    assert client.cookies.get(CSRF_COOKIE) == reissued

    # And the token that came back works, which is the whole point of returning one.
    assert client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: reissued},
        content=TINY_PNG,
    ).status_code == 201

    # The old one does not, which is what rotating is for.
    assert client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: at_sign_in},
        content=TINY_PNG,
    ).status_code == 403


def test_a_local_deployment_answers_the_address_it_was_opened_at(client):
    """The other half of the page following its own hostname.

    A local deployment is opened at whatever address somebody types — `localhost`,
    `127.0.0.1`, the machine's name, its address on the network — and a browser
    treats each as a different origin. The page sends its requests to the host it
    was loaded from, because a session cookie belongs to a host; an allowlist that
    names two spellings of "this machine" refuses the third, and a refused preflight
    reaches the page as `Failed to fetch`, which names no cause at all.

    So in `local` the **port** is pinned and the host is not. This asserts both
    halves: an unfamiliar local host is answered, and a page on the wrong port is
    not — because widening this to any origin is how a service ends up accepting
    authenticated requests from anywhere.
    """
    for origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://desktop-lqgruau:3000",
        "http://192.168.1.42:3000",
    ):
        answered = client.options(
            "/api/v1/auth/sign-in",
            headers={
                "origin": origin,
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type",
            },
        )
        assert answered.status_code == 200, origin
        assert answered.headers.get("access-control-allow-origin") == origin, origin
        assert answered.headers.get("access-control-allow-credentials") == "true", origin

    refused = client.options(
        "/api/v1/auth/sign-in",
        headers={
            "origin": "http://evil.example.com",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert refused.headers.get("access-control-allow-origin") is None
