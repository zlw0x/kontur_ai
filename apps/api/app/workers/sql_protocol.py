from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import or_, select

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
from app.ledger.models import WorkerCapabilitySnapshotRow
from app.workers.capabilities import unmet_capabilities
from app.workers.models import ArtifactRow, JobRow, WorkerRow
from app.workers.protocol import (
    LEASE_LOST_CODE,
    codex_is_reachable,
    LEASE_LOST_MESSAGE,
    Job,
    ReapOutcome,
    Worker,
    WorkerProtocolError,
    _hash,
)


class SqlWorkerProtocolService:
    """Transactional worker protocol used by PostgreSQL and SQLite tests."""

    def __init__(self, session_factory, enrollment_token: str, clock=None) -> None:
        self.sessions, self.enrollment_token = session_factory, enrollment_token
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def register(self, *, enrollment_token: str, worker_name: str, app_version: str) -> tuple[Worker, str]:
        """Enrol a worker, or re-enrol a machine that is already known.

        Re-enrolling the same name rotates its credential rather than failing.
        A machine that was rebuilt, or whose credential was lost, has to be able
        to come back — and the previous behaviour was a unique-constraint
        violation surfacing as a bare "enrollment was rejected", which sends an
        operator looking at their token instead of at their worker list.

        It grants nothing new: the enrollment token already authorises
        registering a worker, so anyone holding it could occupy the name anyway.
        """
        if not secrets.compare_digest(_hash(enrollment_token), _hash(self.enrollment_token)):
            raise WorkerProtocolError(ErrorCode.ENROLLMENT_REJECTED, "worker enrollment was rejected")
        credential = secrets.token_urlsafe(48)
        with self.sessions.begin() as session:
            existing = session.scalar(select(WorkerRow).where(WorkerRow.name == worker_name))
            if existing is not None:
                # The old credential stops working, which is the point: a
                # rotation that left the previous one valid would be a way to
                # keep a stale worker alive unnoticed.
                existing.token_hash = _hash(credential)
                existing.app_version = app_version
                existing.status = "READY"
                existing.available_slots = 0
                existing.capabilities = []
                existing.supported_cad_ir = []
                existing.capability_manifest = None
                existing.last_seen_at = None
                worker_id = UUID(existing.id)
            else:
                worker_id = uuid4()
                session.add(WorkerRow(
                    id=str(worker_id),
                    name=worker_name,
                    token_hash=_hash(credential),
                    app_version=app_version,
                ))
        return Worker(worker_id, worker_name, _hash(credential), app_version), credential

    def authenticate(self, worker_id: UUID, credential: str) -> Worker:
        with self.sessions() as session:
            row = session.get(WorkerRow, str(worker_id))
            if row is None or not secrets.compare_digest(row.token_hash, _hash(credential)):
                raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker credential was rejected")
            return self._worker(row)

    def authenticate_credential(self, credential: str) -> Worker:
        token_hash = _hash(credential)
        with self.sessions() as session:
            row = session.scalar(select(WorkerRow).where(WorkerRow.token_hash == token_hash))
            if row is None or not secrets.compare_digest(row.token_hash, token_hash):
                raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker credential was rejected")
            return self._worker(row)

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
        with self.sessions.begin() as session:
            row = session.get(WorkerRow, str(worker.id), with_for_update=True)
            if row is None:
                raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker no longer exists")
            row.capabilities = [item.value for item in capabilities]
            row.supported_cad_ir = supported_cad_ir
            row.available_slots = available_slots
            row.last_seen_at = self.clock()
            if capability_manifest is not None:
                self._publish_manifest(session, row, capability_manifest)
            if codex is not None:
                # Overwritten rather than merged: this is the worker's latest
                # observation, and an older one is not evidence about now.
                row.codex_state = codex.state.value
                row.codex_retry_after = codex.retry_after
                row.codex_detail = codex.detail
        worker.capabilities, worker.supported_cad_ir, worker.last_seen_at = set(capabilities), set(supported_cad_ir), self.clock()
        worker.available_slots = available_slots
        if capability_manifest is not None:
            worker.capability_manifest = capability_manifest
        if codex is not None:
            worker.codex = codex

    def _publish_manifest(
        self, session, row: WorkerRow, manifest: WorkerCapabilityManifest
    ) -> None:
        """Record the current manifest and keep the change history.

        Every distinct manifest a worker has published is retained, so a cost
        or incident review can tell which capabilities were in effect when a
        job ran rather than only what the worker claims today.
        """
        document = manifest.model_dump(mode="json")
        row.capability_manifest = document
        fingerprint = hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        known = session.scalar(
            select(WorkerCapabilitySnapshotRow).where(
                WorkerCapabilitySnapshotRow.worker_id == row.id,
                WorkerCapabilitySnapshotRow.manifest_sha256 == fingerprint,
            )
        )
        if known is not None:
            return
        session.add(
            WorkerCapabilitySnapshotRow(
                id=str(uuid4()),
                worker_id=row.id,
                manifest_sha256=fingerprint,
                worker_version=manifest.worker_version,
                codex_cli_version=manifest.codex_cli_version,
                cad_ir_versions=list(manifest.cad_ir_versions),
                capabilities=document["capabilities"],
                observed_at=self.clock(),
            )
        )

    def claim(self, worker: Worker, lease_seconds: int = 60) -> Job | None:
        now = self.clock()
        with self.sessions.begin() as session:
            candidates = session.scalars(
                select(JobRow)
                .where(
                    or_(JobRow.status == JobStatus.PENDING.value,
                        (JobRow.status == JobStatus.LEASED.value) & (JobRow.lease_expires_at <= now)),
                    JobRow.attempt < JobRow.max_attempts,
                )
                .order_by(JobRow.attempt, JobRow.id)
                .with_for_update(skip_locked=True)
            ).all()
            for row in candidates:
                required = {WorkerCapability(item) for item in row.required_capabilities}
                if not canonical_capabilities(required).issubset(
                    canonical_capabilities(worker.capabilities)
                ) or row.required_cad_ir not in worker.supported_cad_ir:
                    continue
                if unmet_capabilities(worker.capability_manifest, list(row.required_capability_keys or [])):
                    continue
                if WorkerCapability.AI_DRAWING in canonical_capabilities(required)                         and not codex_is_reachable(worker.codex, now):
                    # The same gate the in-memory protocol applies, and it has to be
                    # here too: two implementations of one protocol, and a rule in
                    # only one of them is a rule that holds in tests and not in
                    # production.
                    continue
                row.status, row.lease_owner = JobStatus.LEASED.value, str(worker.id)
                row.lease_expires_at, row.attempt = now + timedelta(seconds=lease_seconds), row.attempt + 1
                session.flush()
                return self._job(row)
        return None

    def renew_lease(self, worker: Worker, job_id: UUID, lease_seconds: int = 60) -> Job:
        with self.sessions.begin() as session:
            row = self._owned_row(session, worker, job_id)
            row.lease_expires_at = self.clock() + timedelta(seconds=lease_seconds)
            session.flush()
            return self._job(row)

    def complete(self, worker: Worker, job_id: UUID, idempotency_key: str) -> bool:
        return self.complete_with_artifacts(worker, job_id, idempotency_key, [])

    def complete_with_artifacts(self, worker: Worker, job_id: UUID, idempotency_key: str, artifacts: list[dict]) -> bool:
        with self.sessions.begin() as session:
            row = session.get(JobRow, str(job_id), with_for_update=True)
            if row is None or row.idempotency_key != idempotency_key:
                raise WorkerProtocolError(ErrorCode.IDEMPOTENCY_CONFLICT, "completion key does not match job")
            if row.status == JobStatus.COMPLETED.value:
                return row.completed_key == idempotency_key
            self._validate_owned(row, worker)
            for artifact in artifacts:
                session.add(ArtifactRow(
                    job_id=row.id, artifact_type=artifact["type"], object_key=artifact["object_key"],
                    sha256=artifact["sha256"], size_bytes=artifact["size_bytes"],
                ))
            row.status, row.completed_key = JobStatus.COMPLETED.value, idempotency_key
            row.lease_owner, row.lease_expires_at = None, None
            return False

    def fail(
        self,
        worker: Worker,
        job_id: UUID,
        code: str,
        message: str,
        retry_after: datetime | None = None,
    ) -> Job:
        """See `WorkerProtocolService.fail` — same rules, one row lock."""
        with self.sessions.begin() as session:
            row = session.get(JobRow, str(job_id), with_for_update=True)
            if row is not None and row.status == JobStatus.COMPLETED.value:
                return self._job(row)
            row = self._owned_row(session, worker, job_id)
            row.failure_code, row.failure_message = code, message
            row.retry_after = retry_after
            row.lease_owner, row.lease_expires_at = None, None
            if retry_after is None:
                row.status = JobStatus.FAILED.value
            else:
                # See `WorkerProtocolService.fail`: a pause hands the attempt back,
                # because nothing was attempted.
                row.status = JobStatus.PAUSED.value
                row.attempt = max(0, row.attempt - 1)
            session.flush()
            return self._job(row)

    def reap(self) -> ReapOutcome:
        """See `WorkerProtocolService.reap`. One statement per kind, all locked.

        `skip_locked` on purpose: a row a worker is completing right now is a row
        the reaper has no business touching, and coming back in a second costs
        nothing. The alternative — waiting on the lock — turns a sweep into a queue.
        """
        now, outcome = self.clock(), ReapOutcome()
        with self.sessions.begin() as session:
            due = session.scalars(
                select(JobRow)
                .where(JobRow.status == JobStatus.PAUSED.value,
                       JobRow.retry_after.is_not(None), JobRow.retry_after <= now)
                .with_for_update(skip_locked=True)
            ).all()
            for row in due:
                row.status, row.retry_after, row.reaped_at = JobStatus.PENDING.value, None, now
                row.failure_code, row.failure_message = None, None
                outcome.resumed += 1

            # Leased-and-lapsed, or pending with no attempts left. Both are stuck,
            # and which one a job lands in depends on whether a `claim` happened to
            # reset its lease first — a difference between the two protocol
            # implementations rather than between two situations.
            lapsed = session.scalars(
                select(JobRow)
                .where(or_(
                    (JobRow.status == JobStatus.LEASED.value)
                    & JobRow.lease_expires_at.is_not(None)
                    & (JobRow.lease_expires_at <= now),
                    (JobRow.status == JobStatus.PENDING.value)
                    & (JobRow.attempt >= JobRow.max_attempts),
                ))
                .with_for_update(skip_locked=True)
            ).all()
            for row in lapsed:
                row.lease_owner, row.lease_expires_at, row.reaped_at = None, None, now
                if row.attempt < row.max_attempts:
                    row.status = JobStatus.PENDING.value
                    outcome.requeued += 1
                else:
                    row.status = JobStatus.FAILED.value
                    row.failure_code, row.failure_message = LEASE_LOST_CODE, LEASE_LOST_MESSAGE
                    outcome.failed += 1
            session.flush()
        return outcome

    def enqueue(self, job: Job) -> None:
        with self.sessions.begin() as session:
            session.add(JobRow(
                id=str(job.id), order_id=str(job.order_id), job_type=job.job_type.value,
                idempotency_key=job.idempotency_key,
                required_capabilities=[item.value for item in job.required_capabilities],
                required_capability_keys=list(job.required_capability_keys),
                required_cad_ir=job.required_cad_ir, max_attempts=job.max_attempts,
            ))

    def get_owned_active_job(self, worker: Worker, job_id: UUID) -> Job:
        with self.sessions() as session:
            row = self._owned_row(session, worker, job_id)
            return self._job(row)

    def workers(self) -> list[Worker]:
        with self.sessions() as session:
            return [self._worker(row) for row in session.scalars(select(WorkerRow)).all()]

    def get_job(self, job_id: UUID) -> Job | None:
        with self.sessions() as session:
            row = session.get(JobRow, str(job_id))
            return self._job(row) if row is not None else None

    def get_artifacts(self, job_id: UUID) -> list[dict]:
        with self.sessions() as session:
            rows = session.scalars(select(ArtifactRow).where(ArtifactRow.job_id == str(job_id))).all()
            return [
                {
                    "type": row.artifact_type,
                    "object_key": row.object_key,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                }
                for row in rows
            ]

    def _owned_row(self, session, worker: Worker, job_id: UUID) -> JobRow:
        row = session.get(JobRow, str(job_id), with_for_update=True)
        if row is None:
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease is not owned by this worker")
        self._validate_owned(row, worker)
        return row

    def _validate_owned(self, row: JobRow, worker: Worker) -> None:
        expires = row.lease_expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if row.status != JobStatus.LEASED.value or row.lease_owner != str(worker.id) or expires is None or expires <= self.clock():
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease has expired or changed owner")

    @staticmethod
    def _worker(row: WorkerRow) -> Worker:
        return Worker(UUID(row.id), row.name, row.token_hash, row.app_version,
                      {WorkerCapability(item) for item in row.capabilities}, set(row.supported_cad_ir), row.last_seen_at,
                      WorkerCapabilityManifest(**row.capability_manifest) if row.capability_manifest else None,
                      row.available_slots or 0,
                      CodexAvailability(
                          state=CodexState(row.codex_state),
                          retry_after=row.codex_retry_after,
                          detail=row.codex_detail,
                      ) if row.codex_state else None)

    @staticmethod
    def _job(row: JobRow) -> Job:
        return Job(UUID(row.id), UUID(row.order_id), JobType(row.job_type), row.idempotency_key,
                   {WorkerCapability(item) for item in row.required_capabilities}, row.required_cad_ir,
                   list(row.required_capability_keys or []),
                   row.max_attempts, row.attempt, JobStatus(row.status),
                   UUID(row.lease_owner) if row.lease_owner else None, row.lease_expires_at, row.completed_key,
                   row.failure_code, row.failure_message, row.retry_after, row.reaped_at)
