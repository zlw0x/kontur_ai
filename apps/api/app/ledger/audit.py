"""Invariant checks over a job's recorded resources.

The ledger only becomes trustworthy once a real job has been measured and the
numbers have been checked against reality rather than against the fixtures that
produced them. These checks are what "checked" means, and they run the same way
on synthetic events in CI and on a real PostgreSQL row set.

Everything here is read-only and reports findings; nothing repairs a ledger.
A ledger that needs repairing is evidence of a defect upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.contracts import (
    AgentRole,
    JobIterationCounters,
    ModelObservationStatus,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
    TokenSource,
)
from app.costing.engine import billable_seconds
from app.ledger.service import derive_counters


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    detail: str


#: Stages a completed drawing job must have measured. A gap here means an
#: interval of real machine time that nothing accounted for.
REQUIRED_DRAWING_STAGES: tuple[ResourceStage, ...] = (
    ResourceStage.DRAWING_ANALYSIS,
    ResourceStage.CAD_IR_COMPILATION,
    ResourceStage.SEMANTIC_VALIDATION,
    ResourceStage.CAD_STARTUP,
    ResourceStage.FEATURE_BUILD,
    ResourceStage.GEOMETRY_VALIDATION,
    ResourceStage.ARTIFACT_UPLOAD,
)


@dataclass
class LedgerAudit:
    event_count: int
    billable_seconds: Decimal
    naive_sum_seconds: Decimal
    counters: JobIterationCounters
    token_coverage: dict[TokenSource, int]
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(item.severity is Severity.ERROR for item in self.findings)

    @property
    def double_counted_seconds(self) -> Decimal:
        """How much summing durations would have over-charged.

        Expected to be positive whenever nested spans exist; it is the value
        the union calculation exists to avoid billing.
        """
        return self.naive_sum_seconds - self.billable_seconds


def audit_job_ledger(
    events: list[ResourceEvent],
    *,
    job_started_at: datetime | None = None,
    job_finished_at: datetime | None = None,
    required_stages: tuple[ResourceStage, ...] = REQUIRED_DRAWING_STAGES,
) -> LedgerAudit:
    findings: list[Finding] = []
    billable = billable_seconds(events)
    naive = sum(
        (
            Decimal(str((event.finished_at - event.started_at).total_seconds()))
            for event in events
            if event.finished_at is not None and event.finished_at > event.started_at
        ),
        Decimal(0),
    )
    counters = derive_counters(events)

    findings += _check_unique_keys(events)
    findings += _check_open_intervals(events)
    findings += _check_wall_clock(billable, job_started_at, job_finished_at)
    findings += _check_stage_coverage(events, required_stages)
    findings += _check_token_honesty(events)
    findings += _check_model_provenance(events)
    findings += _check_nesting(billable, naive)

    return LedgerAudit(
        event_count=len(events),
        billable_seconds=billable,
        naive_sum_seconds=naive,
        counters=counters,
        token_coverage=_token_coverage(events),
        findings=findings,
    )


def _check_unique_keys(events: list[ResourceEvent]) -> list[Finding]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for event in events:
        if event.event_key in seen:
            duplicates.add(event.event_key)
        seen.add(event.event_key)
    if duplicates:
        return [
            Finding(
                Severity.ERROR,
                "DUPLICATE_EVENT_KEY",
                f"the same key appears more than once: {', '.join(sorted(duplicates)[:5])}",
            )
        ]
    return []


def _check_open_intervals(events: list[ResourceEvent]) -> list[Finding]:
    """An event with no finish is a span that never closed.

    A crash between start and finish leaves one. It must never be treated as
    running forever, so billing has to exclude it — but it should be visible,
    because it marks work whose cost is genuinely unknown.
    """
    open_events = [event.event_key for event in events if event.finished_at is None]
    if not open_events:
        return []
    return [
        Finding(
            Severity.WARNING,
            "UNFINISHED_INTERVAL",
            f"{len(open_events)} event(s) never recorded a finish and are excluded from "
            f"billable time: {', '.join(sorted(open_events)[:5])}",
        )
    ]


def _check_wall_clock(
    billable: Decimal, started_at: datetime | None, finished_at: datetime | None
) -> list[Finding]:
    if started_at is None or finished_at is None:
        return []
    wall = Decimal(str((finished_at - started_at).total_seconds()))
    if billable > wall:
        return [
            Finding(
                Severity.ERROR,
                "BILLABLE_EXCEEDS_WALL_CLOCK",
                f"billable {billable}s exceeds the order's wall clock {wall}s",
            )
        ]
    return [
        Finding(
            Severity.INFO,
            "WALL_CLOCK",
            f"billable {billable}s of {wall}s wall clock "
            f"({(billable / wall * 100).quantize(Decimal('0.1')) if wall else 0}% busy)",
        )
    ]


def _check_stage_coverage(
    events: list[ResourceEvent], required: tuple[ResourceStage, ...]
) -> list[Finding]:
    present = {event.stage for event in events}
    missing = [stage.value for stage in required if stage not in present]
    if missing:
        return [
            Finding(
                Severity.ERROR,
                "STAGE_NOT_MEASURED",
                f"no event covers: {', '.join(missing)}",
            )
        ]
    return []


def _check_token_honesty(events: list[ResourceEvent]) -> list[Finding]:
    """Zero means "measured as zero"; null means "not known".

    Conflating them is the single most damaging thing that can happen to this
    ledger: an unmeasured run priced as zero tokens looks free.
    """
    findings: list[Finding] = []
    for event in events:
        if event.event_type is not ResourceEventType.AI_RUN or event.ai is None:
            continue
        usage = event.ai
        if usage.token_source is TokenSource.UNKNOWN:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "AI_RUN_USAGE_UNKNOWN",
                    f"{event.event_key}: token counts were not obtained; the run "
                    "contributes no AI cost",
                )
            )
            continue
        if usage.input_tokens == 0 and usage.output_tokens == 0:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "AI_RUN_ZERO_TOKENS",
                    f"{event.event_key}: reports a measured zero-token run, which no "
                    "real Codex call produces — a null was probably coerced to 0",
                )
            )
    return findings


def _check_model_provenance(events: list[ResourceEvent]) -> list[Finding]:
    """Every AI run must be attributable to a model.

    A mismatch means the CLI contradicted an explicit instruction, which is a
    defect worth stopping for rather than a rounding detail: everything that
    run produced was generated by something other than what was asked for.
    """
    findings: list[Finding] = []
    for event in events:
        if event.event_type is not ResourceEventType.AI_RUN or event.ai is None:
            continue
        status = event.ai.model_observation_status
        if status is ModelObservationStatus.MISMATCH:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "CODEX_MODEL_MISMATCH",
                    f"{event.event_key}: requested {event.ai.requested_model} but the CLI "
                    f"reported {event.ai.observed_model}; the run is not attributable",
                )
            )
        elif status is ModelObservationStatus.UNKNOWN:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "CODEX_MODEL_UNATTRIBUTED",
                    f"{event.event_key}: the run named no model, so its AI cost cannot "
                    "be attributed",
                )
            )
    return findings


def _check_nesting(billable: Decimal, naive: Decimal) -> list[Finding]:
    if naive <= billable:
        return []
    return [
        Finding(
            Severity.INFO,
            "NESTED_SPANS_DEDUPLICATED",
            f"summing durations would have billed {naive}s; overlapping spans were "
            f"counted once for {billable}s",
        )
    ]


def _token_coverage(events: list[ResourceEvent]) -> dict[TokenSource, int]:
    coverage: dict[TokenSource, int] = {}
    for event in events:
        if event.event_type is ResourceEventType.AI_RUN and event.ai is not None:
            coverage[event.ai.token_source] = coverage.get(event.ai.token_source, 0) + 1
    return coverage


def expected_repair_shape(counters: JobIterationCounters) -> list[Finding]:
    """Checks specific to a deliberately provoked repair.

    A controlled repair is the only way to see the repair path working before
    a customer's order depends on it.
    """
    findings: list[Finding] = []
    if counters.repair_runs < 1:
        findings.append(
            Finding(Severity.ERROR, "NO_REPAIR_RECORDED", "the provoked repair produced no repair run")
        )
    if counters.cad_ir_generation_runs < 1:
        findings.append(
            Finding(
                Severity.ERROR,
                "NO_COMPILATION_RECORDED",
                "a repair implies an original compilation that failed validation",
            )
        )
    if counters.analysis_runs < 1:
        findings.append(
            Finding(Severity.ERROR, "NO_ANALYSIS_RECORDED", "no drawing analysis run was recorded")
        )
    return findings


ROLE_LABELS = {
    AgentRole.DRAWING_EXTRACTION: "drawing analysis",
    AgentRole.CAD_IR_COMPILATION: "CAD-IR compilation",
    AgentRole.REPAIR: "repair",
}
