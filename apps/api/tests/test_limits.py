"""What one account may ask of a service with one worker behind it.

ADR-037 shipped authentication that is correct and not yet hard to grind against,
and said so in as many words. This is the other half: bcrypt at cost 12 makes each
guess expensive and nothing made the *number* of guesses expensive, so a patient
attacker had unlimited tries at a quarter of a second each.

Three things are checked here more carefully than the rest, because each is a way
this could be worse than what it replaces:

**A quota refuses before the work, not after.** The point is not to spend the
decode and the model call and then decline.

**A lockout does not answer differently from a wrong password.** A `429` on a
sign-in form announces that the address has an account, which is exactly what the
careful wording of that endpoint exists to avoid. Quotas *do* answer `429`, because
by then the caller is authenticated and there is nothing left to disclose.

**A limit counts the right rows.** An order that is finished is not occupying
anything, and counting it would lock a working customer out of their own service
after three drawings, forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.accounts import CSRF_HEADER, AccountService, InMemoryAccountRepository, Role
from app.accounts.limits import (
    OrderQuota,
    QuotaExceeded,
    SignInPolicy,
    check_order_quota,
    locked_out,
)
from app.accounts.service import AuthenticationFailed
from app.contracts import OrderStatus
from app.main import app
from app.orders.repository import InMemoryOrderRepository
from app.workers.artifact_store import LocalArtifactStore
from fastapi.testclient import TestClient
from tests.drawing_fixture import TINY_PNG
from tests.test_worker_api import memory_protocol

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
GOOD_PASSWORD = "correct horse battery staple"
MANUAL = {"x-manual-api-token": "local-development-manual-api-token-change-me"}


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    from app.input.quarantine import Quarantine

    memory_protocol(monkeypatch)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "store", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "quarantine"))
    return TestClient(app)


def signed_up(client: TestClient, email: str = "ivan@example.com") -> str:
    created = client.post(
        "/api/v1/auth/register", json={"email": email, "password": GOOD_PASSWORD}
    )
    assert created.status_code == 201, created.text
    return created.json()["csrf_token"]


def upload(client: TestClient, csrf: str):
    return client.post(
        "/api/v1/drawing-jobs",
        headers={"content-type": "image/png", CSRF_HEADER: csrf},
        content=TINY_PNG,
    )


# --- the rule, without a database ------------------------------------------------


def test_being_at_the_in_flight_limit_refuses_with_a_retry_after():
    with pytest.raises(QuotaExceeded) as over:
        check_order_quota(started_in_window=[], in_flight=3, quota=OrderQuota(), now=NOW)

    assert over.value.code == "ORDER_LIMIT_IN_FLIGHT"
    assert over.value.retry_after_seconds >= 1


def test_the_daily_limit_says_exactly_when_it_lifts():
    """Knowable, so it is stated: the window slides off the oldest one."""
    quota = OrderQuota(per_day=3, in_flight=99)
    started = [NOW - timedelta(hours=20), NOW - timedelta(hours=2), NOW - timedelta(minutes=1)]

    with pytest.raises(QuotaExceeded) as over:
        check_order_quota(started_in_window=started, in_flight=0, quota=quota, now=NOW)

    assert over.value.code == "ORDER_LIMIT_PER_DAY"
    # Four hours until the oldest of the three leaves a one-day window.
    assert 4 * 3600 - 5 <= over.value.retry_after_seconds <= 4 * 3600 + 5


def test_orders_older_than_the_window_do_not_count():
    quota = OrderQuota(per_day=2, in_flight=99)
    started = [NOW - timedelta(days=3), NOW - timedelta(days=2), NOW - timedelta(minutes=1)]

    check_order_quota(started_in_window=started, in_flight=0, quota=quota, now=NOW)


def test_in_flight_is_checked_before_the_daily_total():
    """The limit a customer hits by working normally is the one worth naming.

    Three drawings uploaded in a minute is in-flight, not a daily total they are
    nowhere near, and "three are being built" is more useful than "you have started
    twenty today" when they have started three.
    """
    with pytest.raises(QuotaExceeded) as over:
        check_order_quota(
            started_in_window=[NOW] * 99, in_flight=99, quota=OrderQuota(), now=NOW
        )

    assert over.value.code == "ORDER_LIMIT_IN_FLIGHT"


def test_a_naive_timestamp_does_not_become_a_type_error():
    """SQLite hands back naive datetimes and PostgreSQL does not.

    Comparing one against an aware `now` raises `TypeError` — which would be a 500 on
    every upload under the configuration the tests run on and nothing at all under
    the real one. The worst possible split.
    """
    check_order_quota(
        started_in_window=[datetime(2026, 8, 1, 12, 0)],
        in_flight=0,
        quota=OrderQuota(),
        now=NOW,
    )


# --- through the endpoint ---------------------------------------------------------


def test_a_fourth_order_in_flight_is_refused_with_429_and_retry_after(client, monkeypatch):
    csrf = signed_up(client)
    monkeypatch.setattr("app.main.order_quota", OrderQuota(per_day=99, in_flight=3))

    for _ in range(3):
        assert upload(client, csrf).status_code == 201

    refused = upload(client, csrf)

    assert refused.status_code == 429
    # Not silence: a refusal that does not say when to come back is one a client can
    # only answer by polling, and the polling is what is being limited.
    assert int(refused.headers["retry-after"]) >= 1


def test_a_finished_order_stops_occupying_the_fleet(client, monkeypatch):
    """Counting finished orders would lock a working customer out after three, forever."""
    from app.main import orders

    csrf = signed_up(client)
    monkeypatch.setattr("app.main.order_quota", OrderQuota(per_day=99, in_flight=1))
    first = upload(client, csrf)
    assert first.status_code == 201
    assert upload(client, csrf).status_code == 429

    order_id = first.json()["order_id"]
    orders.transition(
        __import__("uuid").UUID(order_id),
        target=OrderStatus.CANCELLED,
        expected_version=0,
    )

    assert upload(client, csrf).status_code == 201


def test_the_quota_refuses_before_the_upload_is_read(client, monkeypatch):
    """Before the decode and the model call, not after. That is the whole point."""
    from app.input.quarantine import Quarantine

    csrf = signed_up(client)
    monkeypatch.setattr("app.main.order_quota", OrderQuota(per_day=99, in_flight=0))

    class Loud(Quarantine):
        def __init__(self) -> None:
            raise AssertionError("quarantine must not be reached when the quota refuses")

    monkeypatch.setattr("app.main.quarantine", property(lambda _: Loud()), raising=False)

    assert upload(client, csrf).status_code == 429


def test_staff_and_the_manual_key_are_not_quota_limited(client, monkeypatch):
    """An operator diagnosing the engine is not the load this protects against.

    And the manual key owns no orders at all, so there is nothing to count — the
    exemption is not a favour, it is the only answer that makes sense.
    """
    monkeypatch.setattr("app.main.order_quota", OrderQuota(per_day=99, in_flight=0))

    for _ in range(3):
        created = client.post(
            "/api/v1/drawing-jobs",
            headers={**MANUAL, "content-type": "image/png"},
            content=TINY_PNG,
        )
        assert created.status_code == 201, created.text


def test_one_customers_orders_do_not_count_against_another(client, monkeypatch, tmp_path):
    from app.input.quarantine import Quarantine

    mine = signed_up(client, "ivan@example.com")
    monkeypatch.setattr("app.main.order_quota", OrderQuota(per_day=99, in_flight=1))
    assert upload(client, mine).status_code == 201
    assert upload(client, mine).status_code == 429

    other = TestClient(app)
    monkeypatch.setattr("app.main.artifact_store", LocalArtifactStore(tmp_path / "s2", 10_000_000))
    monkeypatch.setattr("app.main.quarantine", Quarantine(tmp_path / "q2"))
    theirs = signed_up(other, "petr@example.com")

    assert upload(other, theirs).status_code == 201


# --- signing in -------------------------------------------------------------------


def service(now: datetime = NOW, policy: SignInPolicy | None = None) -> AccountService:
    return AccountService(
        InMemoryAccountRepository(clock=lambda: now),
        clock=lambda: now,
        sign_in_policy=policy or SignInPolicy(max_failures=3, lockout=timedelta(minutes=15)),
    )


def test_a_run_of_wrong_passwords_shuts_the_account():
    accounts = service()
    accounts.register("ivan@example.com", GOOD_PASSWORD)

    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("ivan@example.com", "not the password")

    # The right password, and still refused: the lock is the point.
    with pytest.raises(AuthenticationFailed):
        accounts.sign_in("ivan@example.com", GOOD_PASSWORD)


def test_the_lockout_says_the_same_words_as_a_wrong_password():
    """A `429` here would announce that the address has an account.

    It is the one endpoint where saying "slow down" is a disclosure, which is why
    the lockout is inside the service and not in a middleware that answers by status
    code.
    """
    accounts = service()
    accounts.register("ivan@example.com", GOOD_PASSWORD)
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("ivan@example.com", "wrong")

    with pytest.raises(AuthenticationFailed) as locked:
        accounts.sign_in("ivan@example.com", GOOD_PASSWORD)
    with pytest.raises(AuthenticationFailed) as unknown:
        accounts.sign_in("nobody@example.com", GOOD_PASSWORD)

    assert str(locked.value) == str(unknown.value)


def test_the_lock_lifts_by_itself():
    accounts = service()
    user, _ = accounts.register("ivan@example.com", GOOD_PASSWORD)
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("ivan@example.com", "wrong")

    accounts._clock = lambda: NOW + timedelta(minutes=16)

    assert accounts.sign_in("ivan@example.com", GOOD_PASSWORD).user.id == user.id


def test_one_success_clears_the_run():
    """A customer who mistypes twice and then gets it right starts from zero.

    Resetting on success rather than on a timer is what keeps the lockout aimed at a
    run of guesses rather than at somebody having a bad morning.
    """
    accounts = service()
    accounts.register("ivan@example.com", GOOD_PASSWORD)
    for _ in range(2):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("ivan@example.com", "wrong")

    accounts.sign_in("ivan@example.com", GOOD_PASSWORD)
    assert accounts.repository.user_by_email("ivan@example.com").failed_sign_ins == 0

    # And the next two failures do not trip a lock that a stale count would have.
    for _ in range(2):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("ivan@example.com", "wrong")
    assert accounts.sign_in("ivan@example.com", GOOD_PASSWORD)


def test_a_wrong_second_factor_counts_as_a_failure():
    """Otherwise the code is guessable at whatever rate the network allows.

    Six digits is a million, and a run of tries against it with the password already
    known is the attack the second factor exists to stop.
    """
    from app.accounts.passwords import totp_code

    accounts = service()
    _, secret = accounts.register("op@example.com", GOOD_PASSWORD, Role.OPERATOR)

    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            accounts.sign_in("op@example.com", GOOD_PASSWORD, totp="000000")

    with pytest.raises(AuthenticationFailed):
        accounts.sign_in("op@example.com", GOOD_PASSWORD, totp=totp_code(secret))


def test_an_unknown_address_leaves_nothing_to_count():
    """Nothing is written for an address with no account.

    Recording failures for one would make the table itself a record of which
    addresses somebody has been guessing at, and would be a place for an attacker to
    write rows without an account.
    """
    accounts = service()

    with pytest.raises(AuthenticationFailed):
        accounts.sign_in("nobody@example.com", "wrong")

    assert accounts.repository.user_by_email("nobody@example.com") is None


def test_locked_out_reads_a_naive_timestamp():
    assert locked_out(datetime(2026, 8, 9, 13, 0), NOW) is True
    assert locked_out(datetime(2026, 8, 9, 11, 0), NOW) is False
    assert locked_out(None, NOW) is False
