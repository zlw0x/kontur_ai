"""Why is this job not being picked up?

Without an answer, an order that no enrolled worker can serve is
indistinguishable from a hung one: the API is healthy, the worker is
authenticated and heartbeating, and nothing happens.

Claimability is computed on demand from the current state of the workers. It
is deliberately not a stored order status — it changes when a worker
heartbeats, enrols, republishes a manifest or frees capacity, none of which are
events on the order, so a persisted field would be stale the moment it was
written. Nothing here participates in the claim transaction; diagnosing a job
must not be able to affect whether it is leased.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.contracts import (
    CapabilityRequirement,
    ClaimBlocker,
    ClaimBlockerCode,
    ClaimabilityStatus,
    JobClaimabilityReport,
    JobStatus,
)
from app.workers.capabilities import (
    MINIMUM_WORKER_VERSION,
    WORKER_ONLINE_WINDOW,
    capability_blockers,
    is_online,
    requirements_for,
    unknown_capabilities,
    worker_version_accepted,
)
from app.workers.protocol import Job, Worker


class SchedulerDiagnostics:
    def __init__(self, protocol, clock=None, online_window: timedelta = WORKER_ONLINE_WINDOW) -> None:
        self.protocol = protocol
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.online_window = online_window

    def report(self, job: Job) -> JobClaimabilityReport:
        now = self.clock()
        required = list(job.required_capability_keys)
        requirements = requirements_for(required)
        unknown = unknown_capabilities(required)

        if job.status is JobStatus.COMPLETED:
            return self._report(job, ClaimabilityStatus.SETTLED, requirements, 0, 0, [], now)
        if job.status is JobStatus.LEASED and _lease_active(job, now):
            return self._report(job, ClaimabilityStatus.IN_PROGRESS, requirements, 0, 0, [], now)

        if unknown:
            # A job asking for vocabulary the API does not know can never be
            # satisfied by any worker. Report that before blaming the fleet.
            blockers = [
                ClaimBlocker(
                    code=ClaimBlockerCode.JOB_REQUIREMENTS_INVALID,
                    capability=name,
                    detail="capability is not in the registry vocabulary",
                )
                for name in unknown
            ]
            return self._report(job, ClaimabilityStatus.BLOCKED, requirements, 0, 0, blockers, now)

        workers = list(self.protocol.workers())
        online = [worker for worker in workers if is_online(worker.last_seen_at, now, self.online_window)]

        if not online:
            blockers = [
                ClaimBlocker(
                    code=ClaimBlockerCode.WORKER_HEARTBEAT_STALE,
                    worker_id=worker.id,
                    worker_name=worker.name,
                    detail=_last_seen_detail(worker, now),
                )
                for worker in workers
            ] or [
                ClaimBlocker(
                    code=ClaimBlockerCode.NO_ONLINE_WORKERS,
                    detail="no worker is enrolled",
                )
            ]
            if workers:
                blockers.insert(
                    0, ClaimBlocker(code=ClaimBlockerCode.NO_ONLINE_WORKERS, detail="every enrolled worker is stale")
                )
            return self._report(job, ClaimabilityStatus.BLOCKED, requirements, 0, 0, blockers, now)

        compatible = 0
        blockers: list[ClaimBlocker] = []
        for worker in online:
            worker_blockers = self._worker_blockers(worker, job, required)
            if worker_blockers:
                blockers.extend(worker_blockers)
            else:
                compatible += 1

        status = ClaimabilityStatus.CLAIMABLE if compatible else ClaimabilityStatus.BLOCKED
        return self._report(
            job,
            status,
            requirements,
            len(online),
            compatible,
            [] if compatible else blockers,
            now,
        )

    def _worker_blockers(self, worker: Worker, job: Job, required: list[str]) -> list[ClaimBlocker]:
        def blocker(code: ClaimBlockerCode, detail: str | None = None) -> ClaimBlocker:
            return ClaimBlocker(code=code, worker_id=worker.id, worker_name=worker.name, detail=detail)

        if not worker_version_accepted(worker.app_version):
            return [
                blocker(
                    ClaimBlockerCode.WORKER_VERSION_INCOMPATIBLE,
                    f"worker {worker.app_version}, requires at least {MINIMUM_WORKER_VERSION}",
                )
            ]
        if not job.required_capabilities.issubset(worker.capabilities):
            missing = sorted(item.value for item in job.required_capabilities - worker.capabilities)
            return [
                blocker(
                    ClaimBlockerCode.CAPABILITY_NOT_SUPPORTED,
                    f"worker does not offer {', '.join(missing)}",
                )
            ]
        if job.required_cad_ir not in worker.supported_cad_ir:
            return [
                blocker(
                    ClaimBlockerCode.CAPABILITY_VERSION_TOO_OLD,
                    f"worker does not support CAD-IR {job.required_cad_ir}",
                )
            ]
        if required and worker.capability_manifest is None:
            return [
                blocker(
                    ClaimBlockerCode.WORKER_MANIFEST_MISSING,
                    "worker has not published a capability manifest",
                )
            ]
        if worker.capability_manifest is not None:
            found = [
                item.model_copy(update={"worker_id": worker.id, "worker_name": worker.name})
                for item in capability_blockers(worker.capability_manifest, required)
            ]
            if found:
                return found
        if worker.available_slots <= 0:
            # Checked last: being busy is only worth reporting once the worker
            # is otherwise able to take the job.
            return [
                blocker(
                    ClaimBlockerCode.WORKER_LEASE_CAPACITY_EXHAUSTED,
                    "worker reported no free slots",
                )
            ]
        return []

    def _report(
        self,
        job: Job,
        status: ClaimabilityStatus,
        requirements: list[CapabilityRequirement],
        online: int,
        compatible: int,
        blockers: list[ClaimBlocker],
        now: datetime,
    ) -> JobClaimabilityReport:
        return JobClaimabilityReport(
            job_id=job.id,
            claimability=status,
            required_capabilities=requirements,
            online_workers=online,
            compatible_workers=compatible,
            blockers=blockers,
            evaluated_at=now,
            summary=_summary(status, blockers),
        )


def _lease_active(job: Job, now: datetime) -> bool:
    expires = job.lease_expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def _last_seen_detail(worker: Worker, now: datetime) -> str:
    if worker.last_seen_at is None:
        return "worker has never sent a heartbeat"
    last_seen = worker.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return f"last heartbeat {int((now - last_seen).total_seconds())} seconds ago"


#: Wording shown to the customer. It says what is happening and avoids naming
#: internals: a capability key or a worker version means nothing to them, and a
#: waiting order is not their fault to fix.
_SUMMARY = {
    ClaimabilityStatus.CLAIMABLE: "The order is queued and a modelling module is available.",
    ClaimabilityStatus.IN_PROGRESS: "The order is being modelled.",
    ClaimabilityStatus.SETTLED: "The order has finished.",
}


def _summary(status: ClaimabilityStatus, blockers: list[ClaimBlocker]) -> str:
    if status is not ClaimabilityStatus.BLOCKED:
        return _SUMMARY[status]
    if any(item.code is ClaimBlockerCode.WORKER_LEASE_CAPACITY_EXHAUSTED for item in blockers):
        return "The order is waiting for the modelling module to finish another job."
    if any(item.code is ClaimBlockerCode.JOB_REQUIREMENTS_INVALID for item in blockers):
        return "This order needs an operation the service does not offer yet."
    return "The order is waiting for an available modelling module."
