"""A job that needs the model is not handed to a worker that cannot reach it.

The measured failure, from a real run: the Codex account's quota ran out until a
stated date. Orders went on being handed to workers, each of which returned
`CODEX_CAPACITY_LIMIT` the moment it tried — three leases and three failures per
order, every one of them predictable from the first. The pause landed later and made
each of those a pause rather than a failure, which is better and is still three.

And the customer's page said "no worker has capacity". True — every worker had just
failed and gone back to polling — and not the reason. A status page that names the
wrong cause sends somebody to check the wrong thing.

`codex_cli_version` was already in the capability manifest and could not have
helped: it says which version is *installed*, which is a different question from
whether it answers.

Two things are tested here more carefully than the rest, because both are ways this
could be worse than what it replaces: the gate must be **narrow** (a build needs no
model, and withholding those during a quota outage turns one stopped stage into a
stopped service), and it must not be able to **lock itself** (a state only a
successful run can clear, guarded by a rule that prevents runs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.contracts import (
    ClaimBlockerCode,
    CodexAvailability,
    CodexState,
    JobType,
    WorkerCapability,
)
from app.workers.diagnostics import SchedulerDiagnostics
from app.workers.protocol import (
    InMemoryWorkerRepository,
    Job,
    WorkerProtocolService,
    codex_is_reachable,
    needs_the_model,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
ENROLLMENT = "e" * 32


@pytest.fixture()
def service() -> WorkerProtocolService:
    return WorkerProtocolService(InMemoryWorkerRepository(), ENROLLMENT, clock=lambda: NOW)


def enrolled(service: WorkerProtocolService, codex: CodexAvailability | None):
    worker, _ = service.register(
        enrollment_token=ENROLLMENT, worker_name=f"w-{uuid4()}", app_version="0.4.0"
    )
    service.heartbeat(
        worker,
        [WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD],
        ["1.12"],
        1,
        codex=codex,
    )
    return worker


def drawing_job() -> Job:
    return Job(
        uuid4(), uuid4(), JobType.ANALYZE_DRAWING, f"sha256:{uuid4()}",
        {WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD}, "1.12",
    )


def build_job() -> Job:
    return Job(
        uuid4(), uuid4(), JobType.BUILD_CAD, f"sha256:{uuid4()}",
        {WorkerCapability.CAD_BUILD}, "1.12",
    )


PAUSED = CodexAvailability(
    state=CodexState.PAUSED,
    retry_after=NOW + timedelta(hours=1),
    detail="CODEX_CAPACITY_LIMIT: the account's quota is exhausted",
)
UNAVAILABLE = CodexAvailability(
    state=CodexState.UNAVAILABLE, detail="CODEX_AUTH_REQUIRED: not signed in"
)


# --- the gate ------------------------------------------------------------------


def test_a_paused_fleet_is_not_offered_a_drawing_job(service):
    worker = enrolled(service, PAUSED)
    service.enqueue(drawing_job())

    assert service.claim(worker) is None


def test_the_same_fleet_still_takes_a_build(service):
    """The ban is narrow, and this is the assertion that keeps it narrow.

    `BUILD_CAD` is geometry and a container and does not touch the model at all.
    Withholding those during a quota outage would turn one stopped stage into a
    stopped service, and would do it for a reason that does not apply.
    """
    worker = enrolled(service, PAUSED)
    job = build_job()
    service.enqueue(job)

    claimed = service.claim(worker)

    assert claimed is not None and claimed.id == job.id


def test_a_worker_that_has_never_said_is_treated_as_able(service):
    """Silence is availability, and it has to be.

    A worker built before this field existed cannot say, and being unable to say is
    not a reason to refuse its work — the rule `engine` already follows. It is also
    what keeps this gate incapable of withholding work from anybody who has not
    stated they cannot do it.
    """
    worker = enrolled(service, None)
    job = drawing_job()
    service.enqueue(job)

    claimed = service.claim(worker)

    assert claimed is not None and claimed.id == job.id


def test_a_pause_that_has_run_out_lets_the_next_job_through(service):
    """The clock is on this side, so nobody has to send a second message.

    A fleet that went quiet during an outage would otherwise stay blocked until every
    worker said it was over — and the party that has to notice is not always the party
    that is running, which is the reaper's argument exactly.
    """
    worker = enrolled(
        service,
        CodexAvailability(state=CodexState.PAUSED, retry_after=NOW - timedelta(seconds=1)),
    )
    job = drawing_job()
    service.enqueue(job)

    claimed = service.claim(worker)

    assert claimed is not None and claimed.id == job.id


def test_a_state_with_no_horizon_blocks_until_somebody_acts(service):
    """A CLI that is not signed in does not sign itself in.

    So `UNAVAILABLE` carries no date and blocks, and the page says why — which is what
    sends an operator to the machine instead of watching a queue.
    """
    worker = enrolled(service, UNAVAILABLE)
    service.enqueue(drawing_job())

    assert service.claim(worker) is None


def test_one_worker_reporting_a_pause_does_not_stop_another(service):
    """Per worker, and the fleet-wide answer follows from it.

    Fleet-wide is what the *diagnostic* reports; the gate is per worker, because that
    is the decision actually being made — whether to hand this job to this worker.
    """
    unwell = enrolled(service, PAUSED)
    healthy = enrolled(service, CodexAvailability(state=CodexState.AVAILABLE))
    job = drawing_job()
    service.enqueue(job)

    assert service.claim(unwell) is None
    claimed = service.claim(healthy)
    assert claimed is not None and claimed.id == job.id


def test_a_later_heartbeat_replaces_an_earlier_observation(service):
    """The worker's latest word, not a merge. An older one is not evidence about now."""
    worker = enrolled(service, PAUSED)
    job = drawing_job()
    service.enqueue(job)
    assert service.claim(worker) is None

    service.heartbeat(
        worker,
        [WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD],
        ["1.12"],
        1,
        codex=CodexAvailability(state=CodexState.AVAILABLE),
    )

    assert service.claim(worker) is not None


# --- the two predicates, on their own -------------------------------------------


def test_only_a_job_that_needs_the_model_is_gated():
    assert needs_the_model(drawing_job()) is True
    assert needs_the_model(build_job()) is False


@pytest.mark.parametrize(
    ("codex", "reachable"),
    [
        (None, True),
        (CodexAvailability(state=CodexState.AVAILABLE), True),
        (CodexAvailability(state=CodexState.PAUSED, retry_after=NOW + timedelta(minutes=1)), False),
        (CodexAvailability(state=CodexState.PAUSED, retry_after=NOW - timedelta(minutes=1)), True),
        # A pause somebody sent without a date. It blocks, and that is the safe half
        # of an unlikely case: the worker always states one.
        (CodexAvailability(state=CodexState.PAUSED), False),
        (CodexAvailability(state=CodexState.UNAVAILABLE), False),
        # A naive datetime, which is what SQLite hands back. Comparing it against an
        # aware `now` used to be a `TypeError` waiting in the configuration the tests
        # run on and nowhere else.
        (CodexAvailability(state=CodexState.PAUSED, retry_after=datetime(2026, 8, 9, 11, 0)), True),
    ],
)
def test_what_each_state_means_for_reachability(codex, reachable):
    assert codex_is_reachable(codex, NOW) is reachable


# --- and what the page is told ---------------------------------------------------


def test_the_page_says_reading_is_paused_rather_than_blaming_capacity(service):
    """The half of this that is about somebody being told the truth.

    Before it, an exhausted quota produced "The order is waiting for an available
    modelling module", which is what the page says when there is no worker. There
    were workers. They were idle. Every one of them would have failed.
    """
    enrolled(service, PAUSED)
    job = drawing_job()
    service.enqueue(job)

    report = SchedulerDiagnostics(service, clock=lambda: NOW).report(job)

    assert report.claimability.value == "blocked"
    assert [item.code for item in report.blockers] == [ClaimBlockerCode.WORKER_CODEX_UNAVAILABLE]
    assert "CODEX_CAPACITY_LIMIT" in (report.blockers[0].detail or "")
    assert "Reading drawings is paused" in report.summary


def test_a_build_waiting_on_the_same_fleet_is_not_blamed_on_codex(service):
    enrolled(service, PAUSED)
    job = build_job()
    service.enqueue(job)

    report = SchedulerDiagnostics(service, clock=lambda: NOW).report(job)

    assert report.claimability.value == "claimable"
    assert report.blockers == []


def test_a_mixed_fleet_does_not_report_a_codex_summary(service):
    """`all` rather than `any`: one worker's outage is not why the order is waiting.

    Here the healthy worker is busy, so the order really is waiting for capacity —
    and saying "reading is paused" would be the same wrong-cause mistake in a new
    direction.
    """
    enrolled(service, PAUSED)
    busy, _ = service.register(
        enrollment_token=ENROLLMENT, worker_name=f"w-{uuid4()}", app_version="0.4.0"
    )
    service.heartbeat(
        busy, [WorkerCapability.AI_DRAWING, WorkerCapability.CAD_BUILD], ["1.12"], 0,
        codex=CodexAvailability(state=CodexState.AVAILABLE),
    )
    job = drawing_job()
    service.enqueue(job)

    report = SchedulerDiagnostics(service, clock=lambda: NOW).report(job)

    codes = {item.code for item in report.blockers}
    assert codes == {
        ClaimBlockerCode.WORKER_CODEX_UNAVAILABLE,
        ClaimBlockerCode.WORKER_LEASE_CAPACITY_EXHAUSTED,
    }
    assert "another job" in report.summary
