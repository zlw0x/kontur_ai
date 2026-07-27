from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from app.contracts import ErrorCode, JobStatus, JobType, WorkerCapability
from app.workers.models import ArtifactRow, JobRow, WorkerRow
from app.workers.protocol import Job, Worker, WorkerProtocolError, _hash


class SqlWorkerProtocolService:
    """Transactional worker protocol used by PostgreSQL and SQLite tests."""

    def __init__(self, session_factory, enrollment_token: str, clock=None) -> None:
        self.sessions, self.enrollment_token = session_factory, enrollment_token
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def register(self, *, enrollment_token: str, worker_name: str, app_version: str) -> tuple[Worker, str]:
        if not secrets.compare_digest(_hash(enrollment_token), _hash(self.enrollment_token)):
            raise WorkerProtocolError(ErrorCode.ENROLLMENT_REJECTED, "worker enrollment was rejected")
        credential, worker_id = secrets.token_urlsafe(48), uuid4()
        with self.sessions.begin() as session:
            session.add(WorkerRow(id=str(worker_id), name=worker_name, token_hash=_hash(credential), app_version=app_version))
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

    def heartbeat(self, worker: Worker, capabilities: list[WorkerCapability], supported_cad_ir: list[str], available_slots: int) -> None:
        if available_slots < 0:
            raise ValueError("available_slots must not be negative")
        with self.sessions.begin() as session:
            row = session.get(WorkerRow, str(worker.id), with_for_update=True)
            if row is None:
                raise WorkerProtocolError(ErrorCode.WORKER_AUTH_FAILED, "worker no longer exists")
            row.capabilities = [item.value for item in capabilities]
            row.supported_cad_ir = supported_cad_ir
            row.last_seen_at = self.clock()
        worker.capabilities, worker.supported_cad_ir, worker.last_seen_at = set(capabilities), set(supported_cad_ir), self.clock()

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
                if not required.issubset(worker.capabilities) or row.required_cad_ir not in worker.supported_cad_ir:
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

    def enqueue(self, job: Job) -> None:
        with self.sessions.begin() as session:
            session.add(JobRow(
                id=str(job.id), order_id=str(job.order_id), job_type=job.job_type.value,
                idempotency_key=job.idempotency_key,
                required_capabilities=[item.value for item in job.required_capabilities],
                required_cad_ir=job.required_cad_ir, max_attempts=job.max_attempts,
            ))

    def get_owned_active_job(self, worker: Worker, job_id: UUID) -> Job:
        with self.sessions() as session:
            row = self._owned_row(session, worker, job_id)
            return self._job(row)

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
                      {WorkerCapability(item) for item in row.capabilities}, set(row.supported_cad_ir), row.last_seen_at)

    @staticmethod
    def _job(row: JobRow) -> Job:
        return Job(UUID(row.id), UUID(row.order_id), JobType(row.job_type), row.idempotency_key,
                   {WorkerCapability(item) for item in row.required_capabilities}, row.required_cad_ir,
                   row.max_attempts, row.attempt, JobStatus(row.status),
                   UUID(row.lease_owner) if row.lease_owner else None, row.lease_expires_at, row.completed_key)
