"""Idempotent ingestion of measured job resources.

The worker is the only component that can measure a local run, and it reports
over a network that drops connections mid-batch.  Ingestion therefore has to
survive an arbitrary number of resends without ever counting a measurement
twice, because a double-counted event becomes a double-charged customer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.contracts import (
    AgentRole,
    ErrorCode,
    JobIterationCounters,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
)
from app.ledger.models import ResourceEventRow

logger = logging.getLogger("cad-ai-api")


class LedgerError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def content_fingerprint(event: ResourceEvent) -> str:
    """Stable hash of a submitted measurement, used to detect key collisions."""
    payload = event.model_dump(mode="json", exclude={"event_key"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ResourceLedgerService:
    def __init__(self, session_factory, clock=None) -> None:
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def record(self, job_id: UUID, events: list[ResourceEvent]) -> tuple[int, int]:
        """Append `events` to the ledger. Returns (accepted, duplicates).

        A resent event with identical content is a replay and is counted as a
        duplicate.  The same key carrying different content is a worker defect:
        overwriting would break append-only, and keeping the first silently
        would hide the defect, so the batch is rejected.
        """
        fingerprints = {event.event_key: content_fingerprint(event) for event in events}
        accepted = 0
        duplicates = 0
        with self.sessions.begin() as session:
            existing = {
                row.event_key: row.content_sha256
                for row in session.scalars(
                    select(ResourceEventRow).where(
                        ResourceEventRow.job_id == str(job_id),
                        ResourceEventRow.event_key.in_(list(fingerprints)),
                    )
                )
            }
            for event in events:
                stored = existing.get(event.event_key)
                if stored is not None:
                    if stored != fingerprints[event.event_key]:
                        raise LedgerError(
                            ErrorCode.LEDGER_EVENT_CONFLICT,
                            "event_key was already recorded with different content",
                        )
                    duplicates += 1
                    continue
                session.add(self._row(job_id, event, fingerprints[event.event_key]))
                accepted += 1
            try:
                session.flush()
            except IntegrityError as error:
                # Another delivery of the same batch won the race. The caller
                # retries; the replay path above then reports duplicates.
                raise LedgerError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "concurrent ingestion of the same events; retry",
                ) from error

        logger.info(
            json.dumps(
                {
                    "event": "resource_events_recorded",
                    "job_id": str(job_id),
                    "accepted": accepted,
                    "duplicates": duplicates,
                }
            )
        )
        return accepted, duplicates

    def events(self, job_id: UUID) -> list[ResourceEvent]:
        with self.sessions() as session:
            rows = session.scalars(
                select(ResourceEventRow)
                .where(ResourceEventRow.job_id == str(job_id))
                .order_by(ResourceEventRow.started_at, ResourceEventRow.event_key)
            ).all()
            return [self._event(row) for row in rows]

    def _row(self, job_id: UUID, event: ResourceEvent, fingerprint: str) -> ResourceEventRow:
        ai = event.ai
        process = event.process
        cad = event.cad
        return ResourceEventRow(
            id=str(uuid4()),
            job_id=str(job_id),
            event_key=event.event_key,
            event_type=event.event_type.value,
            stage=event.stage.value,
            attempt_no=event.attempt_no,
            agent_role=event.agent_role.value if event.agent_role else None,
            model=ai.model if ai else None,
            reasoning_effort=ai.reasoning_effort.value if ai and ai.reasoning_effort else None,
            service_tier=ai.service_tier.value if ai else None,
            cli_version=ai.cli_version if ai else None,
            prompt_version=ai.prompt_version if ai else None,
            thread_id=ai.thread_id if ai else None,
            token_source=ai.token_source.value if ai else None,
            started_at=event.started_at,
            finished_at=event.finished_at,
            wall_ms=event.wall_ms,
            cpu_user_ms=process.cpu_user_ms if process else None,
            cpu_system_ms=process.cpu_system_ms if process else None,
            peak_memory_bytes=process.peak_memory_bytes if process else None,
            input_tokens=ai.input_tokens if ai else None,
            cached_input_tokens=ai.cached_input_tokens if ai else None,
            output_tokens=ai.output_tokens if ai else None,
            reasoning_tokens=ai.reasoning_tokens if ai else None,
            total_tokens=ai.total_tokens if ai else None,
            bytes_read=process.bytes_read if process else None,
            bytes_written=process.bytes_written if process else None,
            storage_byte_seconds=event.storage_byte_seconds,
            human_minutes=event.human_minutes,
            operation_code=cad.operation_code if cad else None,
            operation_count=cad.operation_count if cad else None,
            failed_feature_count=cad.failed_feature_count if cad else None,
            session_reuse_count=cad.session_reuse_count if cad else None,
            forced_termination=cad.forced_termination if cad else False,
            result_bytes=cad.result_bytes if cad else None,
            exit_code=process.exit_code if process else None,
            termination_reason=process.termination_reason if process else None,
            retry_number=process.retry_number if process else 0,
            success=event.success,
            failure_code=event.failure_code,
            event_metadata=event.metadata,
            content_sha256=fingerprint,
            recorded_at=self.clock(),
        )

    @staticmethod
    def _event(row: ResourceEventRow) -> ResourceEvent:
        ai = None
        if row.event_type == ResourceEventType.AI_RUN.value:
            ai = {
                "model": row.model,
                "reasoning_effort": row.reasoning_effort,
                "service_tier": row.service_tier or "standard",
                "cli_version": row.cli_version,
                "prompt_version": row.prompt_version,
                "thread_id": row.thread_id,
                "token_source": row.token_source or "UNKNOWN",
                "input_tokens": row.input_tokens,
                "cached_input_tokens": row.cached_input_tokens,
                "output_tokens": row.output_tokens,
                "reasoning_tokens": row.reasoning_tokens,
                "total_tokens": row.total_tokens,
            }
        return ResourceEvent(
            event_key=row.event_key,
            event_type=ResourceEventType(row.event_type),
            stage=ResourceStage(row.stage),
            attempt_no=row.attempt_no,
            agent_role=AgentRole(row.agent_role) if row.agent_role else None,
            started_at=_aware(row.started_at),
            finished_at=_aware(row.finished_at),
            wall_ms=row.wall_ms,
            success=row.success,
            failure_code=row.failure_code,
            ai=ai,
            process={
                "cpu_user_ms": row.cpu_user_ms,
                "cpu_system_ms": row.cpu_system_ms,
                "peak_memory_bytes": row.peak_memory_bytes,
                "bytes_read": row.bytes_read,
                "bytes_written": row.bytes_written,
                "exit_code": row.exit_code,
                "termination_reason": row.termination_reason,
                "retry_number": row.retry_number,
            },
            cad={
                "operation_code": row.operation_code,
                "operation_count": row.operation_count,
                "failed_feature_count": row.failed_feature_count,
                "session_reuse_count": row.session_reuse_count,
                "forced_termination": row.forced_termination,
                "result_bytes": row.result_bytes,
            },
            storage_byte_seconds=row.storage_byte_seconds,
            human_minutes=row.human_minutes,
            metadata=row.event_metadata or {},
        )


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; the ledger is always UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


#: Which ledger events feed which iteration counter.  Kept as data so a new
#: stage cannot silently fail to be counted.
_ANALYSIS_ROLES = {AgentRole.DRAWING_EXTRACTION, AgentRole.GEOMETRY_REASONING}


def derive_counters(events: list[ResourceEvent]) -> JobIterationCounters:
    """Fold the ledger into the iteration counters used for pricing.

    Counting happens here, once, from immutable events. Nothing upstream
    reports a counter directly, so a retry cannot inflate one.
    """
    counters = JobIterationCounters()
    human_minutes = counters.human_review_minutes
    fields: dict[str, int] = {}

    def bump(name: str, amount: int = 1) -> None:
        fields[name] = fields.get(name, 0) + amount

    for event in events:
        if event.event_type is ResourceEventType.AI_RUN:
            role = event.agent_role
            if role in _ANALYSIS_ROLES:
                bump("analysis_runs")
            elif role is AgentRole.CLARIFICATION:
                bump("clarification_cycles")
            elif role is AgentRole.CAD_PLANNING:
                bump("planning_runs")
            elif role is AgentRole.CAD_IR_COMPILATION:
                bump("cad_ir_generation_runs")
            elif role is AgentRole.REPAIR:
                bump("repair_runs")
        if event.event_type is ResourceEventType.REPAIR_ITERATION:
            bump("schema_repair_runs")
        if event.event_type is ResourceEventType.CAD_SESSION:
            bump("cad_build_attempts")
        if event.event_type is ResourceEventType.CAD_OPERATION and not event.success:
            bump("cad_feature_failures")
        if event.event_type is ResourceEventType.VALIDATION:
            bump("geometry_validation_runs")
        if event.event_type is ResourceEventType.EXPORT:
            bump("export_attempts")
        if event.human_minutes is not None:
            human_minutes += event.human_minutes

    return JobIterationCounters(**fields, human_review_minutes=human_minutes)
