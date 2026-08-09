from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.contracts import (
    CodexAvailability,
    CodexState,
    ErrorCode,
    JobStatus,
    JobType,
    WorkerCapability,
    WorkerCapabilityManifest,
    canonical_capabilities,
)
from app.workers.capabilities import unmet_capabilities


def needs_the_model(job) -> bool:
    """Whether this job cannot be done without the Codex CLI answering.

    Read off `AI_DRAWING`, which is already how a job says it needs the model, so
    there is no second list to keep in step. Deliberately narrow: a `BUILD_CAD` job
    is geometry and a container, and withholding those during a quota outage would
    turn one stopped stage into a stopped service.
    """
    return WorkerCapability.AI_DRAWING in canonical_capabilities(job.required_capabilities)


def codex_is_reachable(codex: CodexAvailability | None, now: datetime) -> bool:
    """Whether a worker's last word about Codex still means it can answer.

    Silence is availability. A worker built before this field existed cannot say,
    and being unable to say is not a reason to refuse its work — the same rule the
    engine declaration follows. It also means this gate can only ever withhold work
    from a worker that has stated it cannot do that work.

    A pause whose `retry_after` has passed is availability too, and the clock is on
    this side rather than the worker's. Otherwise a fleet that went quiet during an
    outage would stay blocked until every worker sent a second message saying it was
    over — and the party that has to notice is not always the party that is running,
    which is the reaper's argument exactly.
    """
    if codex is None or codex.state == CodexState.AVAILABLE:
        return True
    if codex.retry_after is not None:
        # Any state with a horizon, not only `PAUSED`. The two are different in what
        # they mean and identical in how they end: when the stated time passes, the
        # worker is allowed one more attempt, and what happens then is the next
        # observation. A state with no horizon blocks until somebody acts, which is
        # what `UNAVAILABLE` is for — a CLI that is not installed does not become
        # installed by waiting, and a date on it would be a promise nobody made.
        return _aware(codex.retry_after) <= now
    return False


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; PostgreSQL does not.

    Comparing a naive `retry_after` against an aware `now` raises `TypeError`, which
    here would be a 500 on every claim under the in-memory configuration and nothing
    at all under the real one — the worst possible split, since the tests run on the
    former.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def can_reach_the_model(worker, job, now: datetime) -> bool:
    return not needs_the_model(job) or codex_is_reachable(worker.codex, now)


class WorkerProtocolError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass
class Worker:
    id: UUID
    name: str
    token_hash: str
    app_version: str
    capabilities: set[WorkerCapability] = field(default_factory=set)
    supported_cad_ir: set[str] = field(default_factory=set)
    last_seen_at: datetime | None = None
    capability_manifest: WorkerCapabilityManifest | None = None
    available_slots: int = 0
    #: What this worker last said about its own Codex CLI, and until when.
    #:
    #: `None` means it has never said — an older build — and is treated as
    #: available. The gate can only ever withhold work from a worker that has
    #: stated it cannot do that work.
    codex: CodexAvailability | None = None


@dataclass
class Job:
    id: UUID
    order_id: UUID
    job_type: JobType
    idempotency_key: str
    required_capabilities: set[WorkerCapability]
    required_cad_ir: str
    required_capability_keys: list[str] = field(default_factory=list)
    max_attempts: int = 3
    attempt: int = 0
    status: JobStatus = JobStatus.PENDING
    lease_owner: UUID | None = None
    lease_expires_at: datetime | None = None
    completed_key: str | None = None
    #: Why the worker stopped, once it has. Both are set together or not at all.
    failure_code: str | None = None
    failure_message: str | None = None
    #: When a paused job may be tried again.
    retry_after: datetime | None = None
    #: When the reaper last moved this job, if it was the reaper that moved it.
    reaped_at: datetime | None = None


#: What a job is failed with when its last attempt went silent.
#:
#: A code of its own rather than the last one the worker reported, because the
#: worker reported nothing — that is the whole of what happened. Reusing a build
#: code here would put words in the mouth of a process that died.
LEASE_LOST_CODE = "LEASE_LOST"
LEASE_LOST_MESSAGE = (
    "The worker stopped responding on the last permitted attempt and never said why."
)


@dataclass
class ReapOutcome:
    """What one sweep moved, for the log line and for the tests.

    Three numbers because there are three things that get stuck, and they are stuck
    for different reasons:

    - **requeued**: a lease lapsed with attempts left. The claim loop already does
      this when a worker next asks, so the reaper only matters here when no worker
      is asking — which is exactly when a queue looks broken.
    - **failed**: a lease lapsed with **no** attempts left. Measured: `claim`
      selects `attempt < max_attempts`, so this row is unclaimable by anyone,
      un-failed, and reads as "waiting to start" on the customer's page for the
      rest of time. Nothing but the reaper can end it, because the only party that
      could report it is the process that died.
    - **resumed**: a pause whose time has come.

    A sweep that moved nothing returns zeroes, and the caller says nothing. A queue
    that is quiet should be quiet in the log too.
    """

    requeued: int = 0
    failed: int = 0
    resumed: int = 0

    @property
    def moved(self) -> int:
        return self.requeued + self.failed + self.resumed


class InMemoryWorkerRepository:
    """Deterministic fake repository selected explicitly by isolated API tests."""
    def __init__(self) -> None:
        self.workers: dict[UUID, Worker] = {}
        self.jobs: dict[UUID, Job] = {}
        self.artifacts: dict[UUID, list[dict]] = {}


class WorkerProtocolService:
    def __init__(self, repo: InMemoryWorkerRepository, enrollment_token: str, clock=None) -> None:
        self.repo, self.enrollment_token = repo, enrollment_token
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def register(self, *, enrollment_token: str, worker_name: str, app_version: str) -> tuple[Worker, str]:
        """Enrol a worker, or re-enrol a machine that is already known.

        Re-enrolling the same name rotates its credential and keeps its id, so a
        machine that was rebuilt or lost its credential can come back. The old
        credential stops working, which is the point.
        """
        if not secrets.compare_digest(_hash(enrollment_token), _hash(self.enrollment_token)):
            raise WorkerProtocolError(ErrorCode.ENROLLMENT_REJECTED, "worker enrollment was rejected")
        credential = secrets.token_urlsafe(48)
        existing = next(
            (item for item in self.repo.workers.values() if item.name == worker_name), None
        )
        worker = Worker(
            existing.id if existing is not None else uuid4(),
            worker_name,
            _hash(credential),
            app_version,
        )
        self.repo.workers[worker.id] = worker
        return worker, credential

    def authenticate(self, worker_id: UUID, credential: str) -> Worker:
        worker = self.repo.workers.get(worker_id)
        if worker is None or not secrets.compare_digest(worker.token_hash, _hash(credential)):
            raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker credential was rejected")
        return worker

    def authenticate_credential(self, credential: str) -> Worker:
        token_hash = _hash(credential)
        for worker in self.repo.workers.values():
            if secrets.compare_digest(worker.token_hash, token_hash):
                return worker
        raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker credential was rejected")

    def heartbeat(
        self,
        worker: Worker,
        capabilities: list[WorkerCapability],
        supported_cad_ir: list[str],
        available_slots: int,
        capability_manifest: WorkerCapabilityManifest | None = None,
        codex: CodexAvailability | None = None,
    ) -> None:
        if available_slots < 0:
            raise ValueError("available_slots must not be negative")
        worker.capabilities, worker.supported_cad_ir, worker.last_seen_at = set(capabilities), set(supported_cad_ir), self.clock()
        worker.available_slots = available_slots
        if capability_manifest is not None:
            worker.capability_manifest = capability_manifest
        if codex is not None:
            # Overwritten rather than merged: this is the worker's latest
            # observation, and an older one is not evidence about now.
            worker.codex = codex

    def claim(self, worker: Worker, lease_seconds: int = 60) -> Job | None:
        now = self.clock()
        for job in self.repo.jobs.values():
            expired = job.status == JobStatus.LEASED and job.lease_expires_at is not None and job.lease_expires_at <= now
            if expired:
                job.status, job.lease_owner, job.lease_expires_at = JobStatus.PENDING, None, None
            if job.status != JobStatus.PENDING or job.attempt >= job.max_attempts:
                continue
            if not canonical_capabilities(job.required_capabilities).issubset(
                canonical_capabilities(worker.capabilities)
            ) or job.required_cad_ir not in worker.supported_cad_ir:
                continue
            if unmet_capabilities(worker.capability_manifest, job.required_capability_keys):
                continue
            if not can_reach_the_model(worker, job, now):
                # Measured: the account's quota ran out until a stated date, and
                # orders went on being handed to workers that returned
                # `CODEX_CAPACITY_LIMIT` the moment they read the manifest. Three
                # leases and three failures per order, every one of them predictable
                # from the first. The pause landed later and made each of those a
                # pause rather than a failure, which is better and is still three.
                continue
            job.status, job.lease_owner, job.lease_expires_at = JobStatus.LEASED, worker.id, now + timedelta(seconds=lease_seconds)
            job.attempt += 1
            return job
        return None

    def enqueue(self, job: Job) -> None:
        if job.id in self.repo.jobs or any(
            existing.idempotency_key == job.idempotency_key for existing in self.repo.jobs.values()
        ):
            raise WorkerProtocolError(ErrorCode.IDEMPOTENCY_CONFLICT, "job already exists")
        self.repo.jobs[job.id] = job

    def get_owned_active_job(self, worker: Worker, job_id: UUID) -> Job:
        return self._owned_active_job(worker, job_id)

    def workers(self) -> list[Worker]:
        return list(self.repo.workers.values())

    def get_job(self, job_id: UUID) -> Job | None:
        return self.repo.jobs.get(job_id)

    def get_artifacts(self, job_id: UUID) -> list[dict]:
        return list(self.repo.artifacts.get(job_id, []))

    def renew_lease(self, worker: Worker, job_id: UUID, lease_seconds: int = 60) -> Job:
        job = self._owned_active_job(worker, job_id)
        job.lease_expires_at = self.clock() + timedelta(seconds=lease_seconds)
        return job

    def complete(self, worker: Worker, job_id: UUID, idempotency_key: str) -> bool:
        job = self.repo.jobs.get(job_id)
        if job is None or job.idempotency_key != idempotency_key:
            raise WorkerProtocolError(ErrorCode.IDEMPOTENCY_CONFLICT, "completion key does not match job")
        if job.status == JobStatus.COMPLETED:
            return job.completed_key == idempotency_key
        self._owned_active_job(worker, job_id)
        job.status, job.completed_key, job.lease_owner, job.lease_expires_at = JobStatus.COMPLETED, idempotency_key, None, None
        return False

    def complete_with_artifacts(self, worker: Worker, job_id: UUID, idempotency_key: str, artifacts: list[dict]) -> bool:
        replay = self.complete(worker, job_id, idempotency_key)
        if not replay:
            self.repo.artifacts[job_id] = list(artifacts)
        return replay

    def fail(
        self,
        worker: Worker,
        job_id: UUID,
        code: str,
        message: str,
        retry_after: datetime | None = None,
    ) -> Job:
        """The worker has stopped trying, and says why.

        Lease-scoped like completion, for the same reason: only the worker
        currently holding the job may speak for it. Without that, a worker whose
        lease expired mid-build could fail a job another worker has since picked
        up and is about to finish.

        A completed job is not re-opened. Completion is the stronger statement —
        the artifacts exist and were verified — and a late failure report from a
        worker that lost its lease must not take that away.
        """
        job = self.repo.jobs.get(job_id)
        if job is not None and job.status == JobStatus.COMPLETED:
            return job
        job = self._owned_active_job(worker, job_id)
        job.failure_code, job.failure_message = code, message
        job.retry_after = retry_after
        job.lease_owner, job.lease_expires_at = None, None
        if retry_after is None:
            job.status = JobStatus.FAILED
            return job
        # A pause hands the attempt back. Nothing was attempted: the worker never
        # reached the model, and the reason it gives is about the machine and carries
        # a date. Spending an attempt here means a four-day quota outage burns every
        # job's three tries in the first hour and the reaper then fails them all with
        # `LEASE_LOST` — a code that would be a lie twice over, because the worker did
        # say why, and because the drawing was never the problem.
        #
        # It does mean a job can be paused any number of times. That is the right way
        # round: each pause carries a date and the job sleeps until it passes, so an
        # unbounded pause is an unbounded outage, which is a thing to alert on rather
        # than to hide by failing a customer's order.
        job.status = JobStatus.PAUSED
        job.attempt = max(0, job.attempt - 1)
        return job

    def reap(self) -> ReapOutcome:
        """Move the jobs no worker will ever speak for again. See `ReapOutcome`."""
        now, outcome = self.clock(), ReapOutcome()
        for job in self.repo.jobs.values():
            if job.status == JobStatus.PAUSED and job.retry_after is not None and job.retry_after <= now:
                job.status, job.retry_after, job.reaped_at = JobStatus.PENDING, None, now
                job.failure_code, job.failure_message = None, None
                outcome.resumed += 1
                continue
            expired = (
                job.status == JobStatus.LEASED
                and job.lease_expires_at is not None
                and job.lease_expires_at <= now
            )
            # A job with no attempts left is stuck in **whichever** state it is in.
            # The two protocol implementations spell it differently — the in-memory
            # claim resets an expired lease to PENDING before testing the attempt
            # count, the SQL one tests both at once and leaves the row LEASED — and
            # the disease is the same either way: unclaimable, un-failed, forever.
            spent = job.status == JobStatus.PENDING and job.attempt >= job.max_attempts
            if not expired and not spent:
                continue
            job.lease_owner, job.lease_expires_at, job.reaped_at = None, None, now
            if job.attempt < job.max_attempts:
                job.status = JobStatus.PENDING
                outcome.requeued += 1
            else:
                job.status = JobStatus.FAILED
                job.failure_code = LEASE_LOST_CODE
                job.failure_message = LEASE_LOST_MESSAGE
                outcome.failed += 1
        return outcome

    def _owned_active_job(self, worker: Worker, job_id: UUID) -> Job:
        job = self.repo.jobs.get(job_id)
        if job is None or job.lease_owner != worker.id or job.status != JobStatus.LEASED:
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease is not owned by this worker")
        if job.lease_expires_at is None or job.lease_expires_at <= self.clock():
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease has expired")
        return job
