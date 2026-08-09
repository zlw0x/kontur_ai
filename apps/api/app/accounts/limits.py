"""How much one account may ask of a service with one worker behind it.

ADR-037 shipped authentication that is correct and not yet hard to grind against,
and said so. This is the other half.

Two limits and one lockout, and what they are *not* is as decided as what they
are.

**No new table.** A sliding window of rate events would be a row written on every
request, swept by something, and consulted by everything — and both limits here can
be read off rows that already exist. An order records who owns it and when it was
created; that is the upload rate limit, because an upload *is* an order. Counting
what is in flight is the same query with a different clause.

**No per-IP request limiting.** That belongs to the reverse proxy (P1-6), and an
application-level version of it would be theatre: it sits behind the proxy, sees
whatever `X-Forwarded-For` the proxy chose to pass, and an attacker with a second
address is past it either way. What the application can do exactly — because it
owns the rows — is bound what a *known account* consumes, and that is what is here.

**Two different refusals, on purpose.** A quota answers `429` with `Retry-After`,
because the caller is authenticated and there is nothing left to hide. A sign-in
refuses with the same `401` it always did — a `429` on sign-in would announce that
the address has an account, which is the one thing the whole careful wording of
that endpoint exists to avoid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class OrderQuota:
    """What one customer may have and how fast they may ask for it."""

    #: Orders started in a rolling day. High enough that a real customer with a
    #: folder of drawings is not stopped, low enough that one account cannot spend
    #: a day of the single worker's time by itself.
    per_day: int = 20
    #: Orders being worked on at once. This is the one that actually protects the
    #: fleet: the pilot has one worker, so a customer who queues ten drawings has
    #: put everybody else behind ten drawings.
    in_flight: int = 3
    window: timedelta = timedelta(days=1)


@dataclass(frozen=True)
class SignInPolicy:
    """What a run of wrong passwords costs.

    Per **account** rather than per address or per connection. That is the thing
    being protected: an attacker guessing one password gets ten tries and then
    fifteen minutes, whichever machine they guess from.

    The cost of this is real and is worth naming: somebody who knows a customer's
    address can lock them out for fifteen minutes at a time. For a pilot that is the
    better trade — the alternative is an account whose password can be guessed at
    the rate bcrypt allows, forever — and it is the reason the count resets on the
    first success rather than on a timer.
    """

    max_failures: int = 10
    lockout: timedelta = timedelta(minutes=15)


class QuotaExceeded(Exception):
    """A limit the caller may see, with when it lifts.

    Carries `retry_after_seconds` because a refusal that does not say when to come
    back is one a client can only answer by polling — and the polling is the thing
    being limited.
    """

    def __init__(self, code: str, message: str, retry_after_seconds: int) -> None:
        self.code = code
        self.message = message
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(message)


def check_order_quota(
    *,
    started_in_window: list[datetime],
    in_flight: int,
    quota: OrderQuota,
    now: datetime,
) -> None:
    """Refuse a new order that would put this customer over either limit.

    Both counts are handed in rather than queried here, so the rule is a pure
    function of numbers and can be argued about without a database. The queries that
    produce them are `SqlOrderRepository.quota_counts`.

    In-flight is checked first. It is the limit a customer hits by working normally
    — three drawings uploaded in a minute — and telling them "you have three being
    built" is more useful than telling them about a daily total they are nowhere
    near.
    """
    if in_flight >= quota.in_flight:
        raise QuotaExceeded(
            "ORDER_LIMIT_IN_FLIGHT",
            f"{quota.in_flight} orders are already being worked on. "
            "The next one can be started when one of them finishes.",
            # No date to give: it lifts when a build finishes, and how long that
            # takes is what the job's own progress says. A minute is a poll
            # interval, not a promise.
            retry_after_seconds=60,
        )
    recent = [when for when in started_in_window if _aware(when) > now - quota.window]
    if len(recent) >= quota.per_day:
        oldest = min(_aware(when) for when in recent)
        raise QuotaExceeded(
            "ORDER_LIMIT_PER_DAY",
            f"{quota.per_day} orders have been started in the last day.",
            # Exact, because it is knowable: the window slides off the oldest one.
            retry_after_seconds=math.ceil((oldest + quota.window - now).total_seconds()),
        )


def locked_out(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and _aware(locked_until) > now


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; PostgreSQL does not.

    Comparing one against an aware `now` raises `TypeError`, which under the
    in-memory configuration would be a 500 on every upload and under the real one
    nothing at all — the worst possible split, since the tests run on the former.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


__all__ = [
    "OrderQuota",
    "QuotaExceeded",
    "SignInPolicy",
    "check_order_quota",
    "locked_out",
]
