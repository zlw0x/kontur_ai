"""Pricing profile storage and job cost snapshots.

A draft may be recalculated as often as needed. A FINAL snapshot is the record
of what the customer was told they owe, so it is written once and never
changed: reruns return the stored snapshot rather than a fresh calculation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from app.contracts import (
    CostSnapshotStatus,
    ErrorCode,
    JobCostBreakdown,
    JobCostSnapshot,
    PricingProfile,
)
from app.ledger.models import JobCostSnapshotRow, PricingProfileRow


class CostServiceError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class PricingProfileStore:
    def __init__(self, session_factory, clock=None) -> None:
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(self, profile: PricingProfile) -> UUID:
        """Store a profile version. Versions are immutable once published."""
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(PricingProfileRow).where(
                    PricingProfileRow.code == profile.code,
                    PricingProfileRow.version == profile.version,
                )
            )
            if existing is not None:
                raise CostServiceError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    f"pricing profile {profile.code} v{profile.version} already exists",
                )
            profile_id = uuid4()
            session.add(
                PricingProfileRow(
                    id=str(profile_id),
                    code=profile.code,
                    version=profile.version,
                    currency=profile.currency,
                    valid_from=profile.valid_from,
                    valid_to=profile.valid_to,
                    config=profile.config.model_dump(mode="json"),
                    created_at=self.clock(),
                )
            )
            return profile_id

    def get(self, code: str, version: int) -> tuple[UUID, PricingProfile]:
        with self.sessions() as session:
            row = session.scalar(
                select(PricingProfileRow).where(
                    PricingProfileRow.code == code, PricingProfileRow.version == version
                )
            )
            if row is None:
                raise CostServiceError(
                    ErrorCode.PRICING_PROFILE_UNKNOWN, f"pricing profile {code} v{version} is unknown"
                )
            return UUID(row.id), PricingProfile(
                code=row.code,
                version=row.version,
                currency=row.currency,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                config=row.config,
            )


class CostSnapshotService:
    def __init__(self, session_factory, clock=None) -> None:
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def save_draft(
        self, job_id: UUID, pricing_profile_id: UUID, breakdown: JobCostBreakdown
    ) -> JobCostSnapshot:
        """Replace the job's draft. Refused once the job has been finalised."""
        with self.sessions.begin() as session:
            if self._final_row(session, job_id) is not None:
                raise CostServiceError(
                    ErrorCode.COST_SNAPSHOT_IMMUTABLE,
                    "job already has a final cost snapshot",
                )
            for row in session.scalars(
                select(JobCostSnapshotRow).where(
                    JobCostSnapshotRow.job_id == str(job_id),
                    JobCostSnapshotRow.status == CostSnapshotStatus.DRAFT.value,
                )
            ).all():
                session.delete(row)
            session.flush()
            row = self._row(job_id, pricing_profile_id, breakdown, CostSnapshotStatus.DRAFT)
            session.add(row)
            session.flush()
            return self._snapshot(row)

    def finalize(
        self, job_id: UUID, pricing_profile_id: UUID, breakdown: JobCostBreakdown
    ) -> JobCostSnapshot:
        """Write the job's final snapshot, or return the one already written.

        Finalising twice is a replay, not an error: a retried completion must
        not change a price the customer has already been shown.
        """
        with self.sessions.begin() as session:
            existing = self._final_row(session, job_id)
            if existing is not None:
                return self._snapshot(existing)
            for row in session.scalars(
                select(JobCostSnapshotRow).where(
                    JobCostSnapshotRow.job_id == str(job_id),
                    JobCostSnapshotRow.status == CostSnapshotStatus.DRAFT.value,
                )
            ).all():
                session.delete(row)
            session.flush()
            row = self._row(job_id, pricing_profile_id, breakdown, CostSnapshotStatus.FINAL)
            session.add(row)
            session.flush()
            return self._snapshot(row)

    def get(self, job_id: UUID) -> JobCostSnapshot | None:
        with self.sessions() as session:
            row = self._final_row(session, job_id) or session.scalar(
                select(JobCostSnapshotRow).where(JobCostSnapshotRow.job_id == str(job_id))
            )
            return self._snapshot(row) if row is not None else None

    @staticmethod
    def _final_row(session, job_id: UUID) -> JobCostSnapshotRow | None:
        return session.scalar(
            select(JobCostSnapshotRow).where(
                JobCostSnapshotRow.job_id == str(job_id),
                JobCostSnapshotRow.status == CostSnapshotStatus.FINAL.value,
            )
        )

    def _row(
        self,
        job_id: UUID,
        pricing_profile_id: UUID,
        breakdown: JobCostBreakdown,
        status: CostSnapshotStatus,
    ) -> JobCostSnapshotRow:
        return JobCostSnapshotRow(
            id=str(uuid4()),
            job_id=str(job_id),
            status=status.value,
            pricing_profile_id=str(pricing_profile_id),
            ai_allocated_cost=breakdown.ai_allocated_cost,
            ai_shadow_cost=breakdown.ai_shadow_cost,
            worker_cost=breakdown.worker_cost,
            cad_license_cost=breakdown.cad_license_cost,
            vps_cost=breakdown.vps_cost,
            storage_cost=breakdown.storage_cost,
            human_cost=breakdown.human_cost,
            payment_cost=breakdown.payment_cost,
            resource_cost=breakdown.resource_cost,
            complexity_surcharge=breakdown.complexity_surcharge,
            risk_reserve=breakdown.risk_reserve,
            margin_amount=breakdown.margin_amount,
            final_price=breakdown.final_price,
            formula_version=breakdown.formula_version,
            breakdown=breakdown.model_dump(mode="json"),
            calculated_at=self.clock(),
        )

    @staticmethod
    def _snapshot(row: JobCostSnapshotRow) -> JobCostSnapshot:
        return JobCostSnapshot(
            id=UUID(row.id),
            job_id=UUID(row.job_id),
            status=CostSnapshotStatus(row.status),
            pricing_profile_code=row.breakdown["pricing_profile_code"],
            pricing_profile_version=row.breakdown["pricing_profile_version"],
            breakdown=row.breakdown,
            calculated_at=row.calculated_at,
        )
