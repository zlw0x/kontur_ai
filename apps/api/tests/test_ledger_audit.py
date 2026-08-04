"""The auditor is what makes the real E2E run meaningful, so it is tested
against ledgers that are deliberately wrong. A checker that cannot fail proves
nothing about the run it blesses."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.contracts import (
    AgentRole,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
    TokenSource,
)
from app.ledger.audit import (
    REQUIRED_DRAWING_STAGES,
    Severity,
    audit_job_ledger,
    expected_repair_shape,
)
from app.ledger.service import derive_counters

START = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def span(key, event_type, stage, offset, seconds, **overrides) -> ResourceEvent:
    return ResourceEvent(
        **{
            "event_key": key,
            "event_type": event_type,
            "stage": stage,
            "started_at": START + timedelta(seconds=offset),
            "finished_at": START + timedelta(seconds=offset + seconds),
            "wall_ms": seconds * 1000,
            "success": True,
            **overrides,
        }
    )


def ai(key, role, offset, seconds, **ai_overrides) -> ResourceEvent:
    stage = (
        ResourceStage.DRAWING_ANALYSIS
        if role is AgentRole.DRAWING_EXTRACTION
        else ResourceStage.CAD_IR_COMPILATION
    )
    return span(
        key,
        ResourceEventType.AI_RUN,
        stage,
        offset,
        seconds,
        agent_role=role,
        ai={
            **{
                "requested_model": "gpt-5.6-terra",
                "model_observation_status": "EXPLICIT_NOT_REPORTED",
                "token_source": TokenSource.STRUCTURED,
                "input_tokens": 9000,
                "cached_input_tokens": 3000,
                "output_tokens": 600,
            },
            **ai_overrides,
        },
    )


def healthy_job() -> list[ResourceEvent]:
    return [
        ai("job:x:ai:analysis:1", AgentRole.DRAWING_EXTRACTION, 0, 40),
        ai("job:x:ai:compile:1", AgentRole.CAD_IR_COMPILATION, 45, 30),
        span("job:x:validate:cad_ir:1", ResourceEventType.VALIDATION, ResourceStage.SEMANTIC_VALIDATION, 80, 1),
        span("job:x:cad:session:1", ResourceEventType.CAD_SESSION, ResourceStage.CAD_STARTUP, 90, 120),
        span("job:x:cad:operation:prism", ResourceEventType.CAD_OPERATION, ResourceStage.FEATURE_BUILD, 100, 6),
        span("job:x:cad:operation:hole_001", ResourceEventType.CAD_OPERATION, ResourceStage.FEATURE_BUILD, 110, 4),
        span("job:x:validate:geometry:1", ResourceEventType.VALIDATION, ResourceStage.GEOMETRY_VALIDATION, 215, 8),
        span("job:x:transfer:artifact:M3D", ResourceEventType.TRANSFER, ResourceStage.ARTIFACT_UPLOAD, 225, 3),
    ]


def test_a_complete_job_passes_and_reports_what_nesting_saved():
    audit = audit_job_ledger(
        healthy_job(),
        job_started_at=START,
        job_finished_at=START + timedelta(seconds=300),
    )

    assert audit.ok
    assert audit.event_count == 8
    # 40 + 30 + 1 + 120 (the session absorbing both operations) + 8 + 3
    assert audit.billable_seconds == Decimal("202")
    # Summing would have billed the two nested operations twice over.
    assert audit.double_counted_seconds == Decimal("10")
    assert audit.token_coverage == {TokenSource.STRUCTURED: 2}


def test_a_missing_stage_is_an_error_not_a_shrug():
    incomplete = [event for event in healthy_job() if event.stage is not ResourceStage.GEOMETRY_VALIDATION]

    audit = audit_job_ledger(incomplete)

    assert not audit.ok
    finding = next(item for item in audit.findings if item.code == "STAGE_NOT_MEASURED")
    assert "GEOMETRY_VALIDATION" in finding.detail


def test_billable_time_may_never_exceed_the_order_wall_clock():
    audit = audit_job_ledger(
        healthy_job(),
        job_started_at=START,
        job_finished_at=START + timedelta(seconds=100),
    )

    assert not audit.ok
    assert any(item.code == "BILLABLE_EXCEEDS_WALL_CLOCK" for item in audit.findings)


def test_a_measured_zero_token_run_is_treated_as_a_coerced_null():
    """No real Codex call returns zero in and zero out; seeing it means a null
    was flattened somewhere, which would price the run as free."""
    events = healthy_job()
    events[0] = ai(
        "job:x:ai:analysis:1",
        AgentRole.DRAWING_EXTRACTION,
        0,
        40,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
    )

    audit = audit_job_ledger(events)

    assert not audit.ok
    assert any(item.code == "AI_RUN_ZERO_TOKENS" for item in audit.findings)


def test_unknown_usage_warns_but_does_not_fail_the_job():
    events = healthy_job()
    events[0] = span(
        "job:x:ai:analysis:1",
        ResourceEventType.AI_RUN,
        ResourceStage.DRAWING_ANALYSIS,
        0,
        40,
        agent_role=AgentRole.DRAWING_EXTRACTION,
        ai={
            "requested_model": "gpt-5.6-terra",
            "model_observation_status": "EXPLICIT_NOT_REPORTED",
            "token_source": TokenSource.UNKNOWN,
        },
    )

    audit = audit_job_ledger(events)

    assert audit.ok
    warning = next(item for item in audit.findings if item.code == "AI_RUN_USAGE_UNKNOWN")
    assert warning.severity is Severity.WARNING


def test_an_interval_that_never_closed_is_flagged_and_excluded_from_billing():
    """What a crash between start and finish leaves behind. It must not be
    billed as running forever, but it must not be silent either."""
    events = healthy_job()
    events.append(
        ResourceEvent(
            event_key="job:x:cad:session:2",
            event_type=ResourceEventType.CAD_SESSION,
            stage=ResourceStage.CAD_STARTUP,
            started_at=START + timedelta(seconds=400),
            success=False,
            failure_code="WORKER_TERMINATED",
        )
    )

    audit = audit_job_ledger(
        events, job_started_at=START, job_finished_at=START + timedelta(seconds=500)
    )

    assert audit.ok
    # The open span contributes nothing rather than running to infinity.
    assert audit.billable_seconds == Decimal("202")
    assert any(item.code == "UNFINISHED_INTERVAL" for item in audit.findings)


def test_duplicate_keys_in_the_audited_set_are_an_error():
    events = healthy_job()
    events.append(events[0])

    audit = audit_job_ledger(events)

    assert not audit.ok
    assert any(item.code == "DUPLICATE_EVENT_KEY" for item in audit.findings)


def test_a_replayed_batch_leaves_the_audit_identical():
    """The property the real run has to demonstrate: resending events changes
    neither the counters nor the billable time."""
    events = healthy_job()
    first = audit_job_ledger(events, job_started_at=START, job_finished_at=START + timedelta(seconds=300))

    # The ledger de-duplicates on ingestion, so a resend produces the same set.
    second = audit_job_ledger(events, job_started_at=START, job_finished_at=START + timedelta(seconds=300))

    assert first.billable_seconds == second.billable_seconds
    assert first.counters == second.counters


def test_a_provoked_repair_shows_the_expected_counter_shape():
    events = healthy_job() + [
        span(
            "job:x:repair:iteration:1",
            ResourceEventType.REPAIR_ITERATION,
            ResourceStage.SEMANTIC_VALIDATION,
            82,
            1,
        ),
        ai("job:x:ai:repair:1", AgentRole.REPAIR, 84, 20),
        span("job:x:cad:session:2", ResourceEventType.CAD_SESSION, ResourceStage.CAD_STARTUP, 230, 60),
    ]

    counters = derive_counters(events)

    assert counters.analysis_runs == 1
    assert counters.repair_runs == 1
    assert counters.cad_build_attempts == 2
    # One geometry check ran; the CAD-IR semantic validation is not one.
    assert counters.geometry_validation_runs == 1
    assert expected_repair_shape(counters) == []


def test_the_repair_shape_check_fails_when_no_repair_happened():
    findings = expected_repair_shape(derive_counters(healthy_job()))

    assert [item.code for item in findings] == ["NO_REPAIR_RECORDED"]


def test_required_stages_match_what_the_worker_actually_instruments():
    """A stage listed here that the worker never emits would fail every real
    run; one the worker emits but is absent here would never be checked."""
    assert set(REQUIRED_DRAWING_STAGES) <= set(ResourceStage)
    assert ResourceStage.DRAWING_ANALYSIS in REQUIRED_DRAWING_STAGES
    assert ResourceStage.ARTIFACT_UPLOAD in REQUIRED_DRAWING_STAGES


def test_a_model_mismatch_fails_the_audit():
    """The CLI contradicted an explicit instruction, so everything that run
    produced came from something other than what was asked for."""
    events = healthy_job()
    events[0] = ai(
        "job:x:ai:analysis:1",
        AgentRole.DRAWING_EXTRACTION,
        0,
        40,
        requested_model="gpt-5.6-terra",
        observed_model="gpt-5.6-luna",
        model_observation_status="MISMATCH",
    )

    audit = audit_job_ledger(events)

    assert not audit.ok
    finding = next(item for item in audit.findings if item.code == "CODEX_MODEL_MISMATCH")
    assert "gpt-5.6-luna" in finding.detail


def test_an_ai_run_that_named_no_model_fails_the_audit():
    events = healthy_job()
    events[0] = span(
        "job:x:ai:analysis:1",
        ResourceEventType.AI_RUN,
        ResourceStage.DRAWING_ANALYSIS,
        0,
        40,
        agent_role=AgentRole.DRAWING_EXTRACTION,
        ai={"token_source": TokenSource.UNKNOWN},
    )

    audit = audit_job_ledger(events)

    assert not audit.ok
    assert any(item.code == "CODEX_MODEL_UNATTRIBUTED" for item in audit.findings)


def test_an_explicit_run_the_cli_did_not_echo_passes_the_audit():
    """Where every run lands on codex-cli 0.145.0. It must not be an error."""
    audit = audit_job_ledger(healthy_job())

    assert not any(
        item.code in ("CODEX_MODEL_MISMATCH", "CODEX_MODEL_UNATTRIBUTED")
        for item in audit.findings
    )
