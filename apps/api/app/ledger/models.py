"""Append-only storage for measured job resources, prices and capabilities.

Rows here are never updated in place.  A cost snapshot may be recalculated
while it is a draft, but a FINAL snapshot is the record of what a customer was
charged and must stay byte-identical to what was shown.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResourceEventRow(Base):
    __tablename__ = "resource_events"
    __table_args__ = (
        UniqueConstraint("job_id", "event_key", name="uq_resource_events_job_event_key"),
        Index("ix_resource_events_event_type", "event_type"),
        Index("ix_resource_events_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    event_key: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)

    agent_role: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    service_tier: Mapped[str | None] = mapped_column(String(16))
    cli_version: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    thread_id: Mapped[str | None] = mapped_column(String(100))
    token_source: Mapped[str | None] = mapped_column(String(16))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wall_ms: Mapped[int | None] = mapped_column(Integer)
    cpu_user_ms: Mapped[int | None] = mapped_column(Integer)
    cpu_system_ms: Mapped[int | None] = mapped_column(Integer)
    peak_memory_bytes: Mapped[int | None] = mapped_column(Integer)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)

    bytes_read: Mapped[int | None] = mapped_column(Integer)
    bytes_written: Mapped[int | None] = mapped_column(Integer)
    storage_byte_seconds: Mapped[Decimal | None] = mapped_column(Numeric)
    human_minutes: Mapped[Decimal | None] = mapped_column(Numeric)

    operation_code: Mapped[str | None] = mapped_column(String(64))
    operation_count: Mapped[int | None] = mapped_column(Integer)
    failed_feature_count: Mapped[int | None] = mapped_column(Integer)
    session_reuse_count: Mapped[int | None] = mapped_column(Integer)
    forced_termination: Mapped[bool] = mapped_column(Boolean, default=False)
    result_bytes: Mapped[int | None] = mapped_column(Integer)

    exit_code: Mapped[int | None] = mapped_column(Integer)
    termination_reason: Mapped[str | None] = mapped_column(String(50))
    retry_number: Mapped[int] = mapped_column(Integer, default=0)

    success: Mapped[bool] = mapped_column(Boolean)
    failure_code: Mapped[str | None] = mapped_column(String(64))

    # `metadata` is reserved on the declarative base, so the attribute is
    # renamed while the column keeps the name the migration creates.
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PricingProfileRow(Base):
    __tablename__ = "pricing_profiles"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_pricing_profiles_code_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobCostSnapshotRow(Base):
    __tablename__ = "job_cost_snapshots"
    # A job may accumulate any number of drafts but only one FINAL snapshot.
    # Enforcing that in the database means a concurrent finalisation cannot
    # produce two different prices for the same job.
    __table_args__ = (
        Index(
            "uq_job_cost_snapshots_final",
            "job_id",
            unique=True,
            sqlite_where=text("status = 'FINAL'"),
            postgresql_where=text("status = 'FINAL'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    pricing_profile_id: Mapped[str] = mapped_column(ForeignKey("pricing_profiles.id"))

    ai_allocated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    ai_shadow_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    worker_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    cad_license_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    vps_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    storage_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    human_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    payment_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    resource_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    complexity_surcharge: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    risk_reserve: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    margin_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    final_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    formula_version: Mapped[str] = mapped_column(String(20))
    breakdown: Mapped[dict] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerCapabilitySnapshotRow(Base):
    __tablename__ = "worker_capability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "worker_id", "manifest_sha256", name="uq_worker_capability_snapshots_worker_manifest"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    worker_id: Mapped[str] = mapped_column(ForeignKey("local_workers.id"), index=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    worker_version: Mapped[str] = mapped_column(String(50))
    kompas_version: Mapped[str | None] = mapped_column(String(50))
    codex_cli_version: Mapped[str | None] = mapped_column(String(50))
    cad_ir_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
