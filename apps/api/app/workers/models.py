from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkerRow(Base):
    __tablename__ = "local_workers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="READY")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    supported_cad_ir: Mapped[list[str]] = mapped_column(JSON, default=list)
    app_version: Mapped[str] = mapped_column(String(50))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Most recently published WorkerCapabilityManifest; history lives in
    # worker_capability_snapshots.
    capability_manifest: Mapped[dict | None] = mapped_column(JSON)
    # Capacity the worker last reported, so a busy worker is distinguishable
    # from an incapable one when explaining why a job is waiting.
    available_slots: Mapped[int] = mapped_column(Integer, default=0)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    required_capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Capability registry keys the worker must declare before this job is
    # leased. Empty means "v1 job", which any worker may take.
    required_capability_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_cad_ir: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(ForeignKey("local_workers.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_key: Mapped[str | None] = mapped_column(String(80))
    # Why the worker gave up. Nullable because most jobs never do, and because
    # every row written before FAILED existed has no answer to give.
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(400))


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("job_id", "sha256", name="uq_artifacts_job_sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(32))
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(71))
    size_bytes: Mapped[int] = mapped_column(Integer)
