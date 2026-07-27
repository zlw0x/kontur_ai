from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.contracts import ErrorCode, JobStatus, JobType, WorkerCapability, WorkerCapabilityManifest
from app.workers.capabilities import unmet_capabilities


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
        if not secrets.compare_digest(_hash(enrollment_token), _hash(self.enrollment_token)):
            raise WorkerProtocolError(ErrorCode.ENROLLMENT_REJECTED, "worker enrollment was rejected")
        credential = secrets.token_urlsafe(48)
        worker = Worker(uuid4(), worker_name, _hash(credential), app_version)
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
    ) -> None:
        if available_slots < 0:
            raise ValueError("available_slots must not be negative")
        worker.capabilities, worker.supported_cad_ir, worker.last_seen_at = set(capabilities), set(supported_cad_ir), self.clock()
        if capability_manifest is not None:
            worker.capability_manifest = capability_manifest

    def claim(self, worker: Worker, lease_seconds: int = 60) -> Job | None:
        now = self.clock()
        for job in self.repo.jobs.values():
            expired = job.status == JobStatus.LEASED and job.lease_expires_at is not None and job.lease_expires_at <= now
            if expired:
                job.status, job.lease_owner, job.lease_expires_at = JobStatus.PENDING, None, None
            if job.status != JobStatus.PENDING or job.attempt >= job.max_attempts:
                continue
            if not job.required_capabilities.issubset(worker.capabilities) or job.required_cad_ir not in worker.supported_cad_ir:
                continue
            if unmet_capabilities(worker.capability_manifest, job.required_capability_keys):
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

    def _owned_active_job(self, worker: Worker, job_id: UUID) -> Job:
        job = self.repo.jobs.get(job_id)
        if job is None or job.lease_owner != worker.id or job.status != JobStatus.LEASED:
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease is not owned by this worker")
        if job.lease_expires_at is None or job.lease_expires_at <= self.clock():
            raise WorkerProtocolError(ErrorCode.LEASE_EXPIRED, "job lease has expired")
        return job
