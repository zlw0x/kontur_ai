"""Nothing is left leased forever, and a pause is not a failure.

Two states a job could reach and never leave, both measured before either was fixed.

**Leased forever.** `claim` selects jobs with `attempt < max_attempts`, so a worker
that dies on its *last* attempt without reporting leaves the row `LEASED` with an
expired lease and no failure code. No worker can claim it — the predicate excludes it
— and no worker will report it, because the only party that could is the process that
died. It reads as "waiting to start" on the customer's page for the rest of time,
which is the silence `JobStatus.FAILED` was added to end and did not.

**Paused with nowhere to go.** An exhausted Codex quota returns on a stated date. Such
a job is not failed — the drawing is fine and it will build — and it is not waiting for
a worker either, because every worker would be told the same thing today. With only
`FAILED` and `PENDING` to choose from, both answers are lies to the customer.

The reaper is the only party that can move either, and it runs on a timer rather than
on a claim: the case it exists for is the one where **nothing is claiming**.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.contracts import JobStatus, JobType, WorkerCapability
from app.database import Base, create_session_factory
from app.workers.protocol import (
    LEASE_LOST_CODE,
    InMemoryWorkerRepository,
    Job,
    WorkerProtocolService,
)
from app.workers.sql_protocol import SqlWorkerProtocolService


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def memory_service():
    clock = Clock()
    service = WorkerProtocolService(InMemoryWorkerRepository(), "e" * 32, clock)
    worker, _ = service.register(enrollment_token="e" * 32, worker_name="w", app_version="0.1")
    service.heartbeat(worker, [WorkerCapability.CAD_BUILD], ["0.1.0"], 1)
    return service, worker, clock


def sql_service():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    clock = Clock()
    service = SqlWorkerProtocolService(sessions, "e" * 32, clock)
    worker, _ = service.register(enrollment_token="e" * 32, worker_name=f"w-{uuid4()}",
                                 app_version="0.1")
    service.heartbeat(worker, [WorkerCapability.CAD_BUILD], ["0.1.0"], 1)
    return service, worker, clock


#: Both implementations, because they are two answers to one protocol and the SQL one
#: is what runs. A reaper that worked only in memory would be a reaper nobody has.
SERVICES = [pytest.param(memory_service, id="memory"), pytest.param(sql_service, id="sql")]


def enqueued(service) -> Job:
    job = Job(uuid4(), uuid4(), JobType.BUILD_CAD, f"sha256:{uuid4()}",
              {WorkerCapability.CAD_BUILD}, "0.1.0")
    service.enqueue(job)
    return job


def die_holding_the_lease(service, worker, clock, times: int) -> None:
    """Claim and let the lease lapse, `times` over — a worker that keeps crashing."""
    for _ in range(times):
        assert service.claim(worker, lease_seconds=1) is not None
        clock.now += timedelta(seconds=2)


# --- the job that could never be spoken for again -----------------------------


@pytest.mark.parametrize("build", SERVICES)
def test_a_worker_that_dies_on_its_last_attempt_leaves_a_job_nobody_can_move(build):
    """The defect, stated before the fix that ends it.

    Three attempts, three deaths. `attempt == max_attempts`, which `claim` excludes —
    so the row is not merely unassigned, it is unassignable, and nothing in the
    protocol will ever look at it again.

    The two implementations spell the stuck state differently and that is worth
    knowing: the in-memory claim resets an expired lease to PENDING before it tests
    the attempt count, the SQL one tests both at once and leaves the row LEASED. Same
    disease, and the reaper has to sweep both.
    """
    service, worker, clock = build()
    job = enqueued(service)

    die_holding_the_lease(service, worker, clock, times=3)
    clock.now += timedelta(days=7)

    assert service.claim(worker) is None
    stuck = service.get_job(job.id)
    assert stuck.status in (JobStatus.LEASED, JobStatus.PENDING)
    assert (stuck.attempt, stuck.failure_code) == (3, None)


@pytest.mark.parametrize("build", SERVICES)
@pytest.mark.parametrize("polled", [False, True],
                         ids=["nobody-asked", "a-worker-asked-and-was-refused"])
def test_the_reaper_fails_it_and_says_the_worker_never_said_why(build, polled):
    """Both spellings of stuck, because which one a job lands in is an accident of
    whether a worker happened to poll after it died."""
    service, worker, clock = build()
    job = enqueued(service)
    die_holding_the_lease(service, worker, clock, times=3)
    if polled:
        assert service.claim(worker) is None

    outcome = service.reap()

    assert (outcome.failed, outcome.requeued, outcome.resumed) == (1, 0, 0)
    reaped = service.get_job(job.id)
    assert reaped.status == JobStatus.FAILED
    # A code of its own: the worker reported nothing, and that is what happened.
    # Reusing a build code would put words in the mouth of a process that died.
    assert reaped.failure_code == LEASE_LOST_CODE
    assert reaped.reaped_at is not None
    assert (reaped.lease_owner, reaped.lease_expires_at) == (None, None)


@pytest.mark.parametrize("build", SERVICES)
def test_a_lease_that_lapses_with_attempts_left_goes_back_to_the_queue(build):
    """What the claim loop already does when a worker next asks — and the reaper is
    for when none does. A queue nobody is polling is exactly when it looks broken."""
    service, worker, clock = build()
    job = enqueued(service)
    die_holding_the_lease(service, worker, clock, times=1)

    outcome = service.reap()

    assert (outcome.requeued, outcome.failed) == (1, 0)
    assert service.get_job(job.id).status == JobStatus.PENDING
    assert service.claim(worker).attempt == 2


@pytest.mark.parametrize("build", SERVICES)
def test_a_live_lease_is_left_alone(build):
    """A worker building right now is not a worker that has stopped."""
    service, worker, clock = build()
    job = enqueued(service)
    service.claim(worker, lease_seconds=600)

    assert service.reap().moved == 0
    assert service.get_job(job.id).status == JobStatus.LEASED


@pytest.mark.parametrize("build", SERVICES)
def test_a_finished_job_is_never_reaped(build):
    service, worker, clock = build()
    job = enqueued(service)
    service.claim(worker, lease_seconds=1)
    service.complete(worker, job.id, job.idempotency_key)
    clock.now += timedelta(days=7)

    assert service.reap().moved == 0
    assert service.get_job(job.id).status == JobStatus.COMPLETED


# --- the pause ----------------------------------------------------------------


@pytest.mark.parametrize("build", SERVICES)
def test_a_failure_that_states_a_date_pauses_rather_than_fails(build):
    """The Codex quota, as the run met it: back on the 8th, and nothing to fix."""
    service, worker, clock = build()
    job = enqueued(service)
    service.claim(worker, lease_seconds=600)
    back = clock.now + timedelta(days=4)

    paused = service.fail(worker, job.id, "CODEX_CAPACITY_LIMIT",
                          "The Codex quota is exhausted.", retry_after=back)

    assert paused.status == JobStatus.PAUSED
    assert paused.retry_after == back
    # Not claimable while paused: every worker would be told the same thing today.
    assert service.claim(worker) is None
    assert service.reap().moved == 0


@pytest.mark.parametrize("build", SERVICES)
def test_the_reaper_returns_a_paused_job_when_its_time_comes(build):
    service, worker, clock = build()
    job = enqueued(service)
    service.claim(worker, lease_seconds=600)
    service.fail(worker, job.id, "CODEX_CAPACITY_LIMIT", "quota",
                 retry_after=clock.now + timedelta(days=4))

    clock.now += timedelta(days=4, seconds=1)
    outcome = service.reap()

    assert (outcome.resumed, outcome.failed) == (1, 0)
    resumed = service.get_job(job.id)
    assert resumed.status == JobStatus.PENDING
    # The reason goes with the pause. A job back in the queue carrying the code that
    # paused it would show a customer a failure that is no longer true.
    assert (resumed.failure_code, resumed.retry_after) == (None, None)
    assert service.claim(worker) is not None


@pytest.mark.parametrize("build", SERVICES)
def test_a_pause_hands_the_attempt_back(build):
    """Nothing was attempted, so nothing is spent.

    The test that found this asserted the opposite and was wrong. A four-day quota
    outage would otherwise burn every job's three attempts in the first hour, and the
    reaper would then fail them all with `LEASE_LOST` — a code that lies twice: the
    worker *did* say why, and the drawing was never the problem.
    """
    service, worker, clock = build()
    job = enqueued(service)

    for _ in range(5):
        assert service.claim(worker, lease_seconds=600) is not None
        service.fail(worker, job.id, "CODEX_CAPACITY_LIMIT", "quota",
                     retry_after=clock.now + timedelta(hours=1))
        assert service.get_job(job.id).attempt == 0
        clock.now += timedelta(hours=2)
        assert service.reap().resumed == 1

    # Five pauses later the job still has all three attempts, and the build it has
    # been waiting for is the one it gets.
    survived = service.claim(worker, lease_seconds=600)
    assert survived is not None and survived.attempt == 1
    service.complete(worker, job.id, job.idempotency_key)
    assert service.get_job(job.id).status == JobStatus.COMPLETED


@pytest.mark.parametrize("build", SERVICES)
def test_a_failure_with_no_date_still_fails(build):
    service, worker, clock = build()
    job = enqueued(service)
    service.claim(worker, lease_seconds=600)

    failed = service.fail(worker, job.id, "SHAPE_CLAIM_CONTRADICTED", "not the part")

    assert (failed.status, failed.retry_after) == (JobStatus.FAILED, None)
