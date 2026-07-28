from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.contracts import (
    AgentRole,
    ErrorCode,
    JobType,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
    TokenSource,
    WorkerCapability,
)
from app.database import Base, create_session_factory
from app.ledger.service import (
    LedgerError,
    ResourceLedgerService,
    content_fingerprint,
    derive_counters,
)
from app.main import app
from app.workers.protocol import InMemoryWorkerRepository, Job, WorkerProtocolService

STARTED = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def ledger_fixture() -> ResourceLedgerService:
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return ResourceLedgerService(sessions)


def ai_event(key: str, role: AgentRole = AgentRole.DRAWING_EXTRACTION, **overrides) -> ResourceEvent:
    return ResourceEvent(
        **{
            "event_key": key,
            "event_type": ResourceEventType.AI_RUN,
            "stage": ResourceStage.DRAWING_ANALYSIS,
            "agent_role": role,
            "started_at": STARTED,
            "finished_at": STARTED + timedelta(seconds=30),
            "wall_ms": 30_000,
            "success": True,
            "ai": {
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "token_source": TokenSource.STRUCTURED,
                "input_tokens": 1200,
                "cached_input_tokens": 400,
                "output_tokens": 300,
            },
            **overrides,
        }
    )


def cad_event(key: str, **overrides) -> ResourceEvent:
    return ResourceEvent(
        **{
            "event_key": key,
            "event_type": ResourceEventType.CAD_OPERATION,
            "stage": ResourceStage.FEATURE_BUILD,
            "started_at": STARTED,
            "finished_at": STARTED + timedelta(seconds=2),
            "wall_ms": 2_000,
            "success": True,
            "cad": {"operation_code": "extrude_add", "operation_count": 1},
            **overrides,
        }
    )


def test_duplicate_event_is_replayed_not_counted_twice():
    ledger = ledger_fixture()
    job_id = uuid4()
    event = ai_event("job:a:ai:analysis:1")

    assert ledger.record(job_id, [event]) == (1, 0)
    assert ledger.record(job_id, [event]) == (0, 1)
    assert len(ledger.events(job_id)) == 1


def test_partially_delivered_batch_completes_on_retry():
    ledger = ledger_fixture()
    job_id = uuid4()
    first, second = ai_event("job:a:ai:analysis:1"), cad_event("job:a:cad:extrude:1")

    # The connection dropped after the first event was persisted.
    assert ledger.record(job_id, [first]) == (1, 0)
    # The worker resends the whole batch; only the missing event is appended.
    assert ledger.record(job_id, [first, second]) == (1, 1)
    assert len(ledger.events(job_id)) == 2


def test_same_key_with_different_content_is_rejected():
    ledger = ledger_fixture()
    job_id = uuid4()
    ledger.record(job_id, [ai_event("job:a:ai:analysis:1")])

    with pytest.raises(LedgerError) as caught:
        ledger.record(job_id, [ai_event("job:a:ai:analysis:1", role=AgentRole.REPAIR)])
    assert caught.value.code == ErrorCode.LEDGER_EVENT_CONFLICT
    assert len(ledger.events(job_id)) == 1


def test_events_read_back_are_identical_to_what_was_submitted():
    """Found by the first real end-to-end run.

    A TRANSFER event carries no CAD usage, but every event shares one wide
    row, so reconstruction used to return an all-null `cad` object. That
    changed the event's content fingerprint, and re-recording events read back
    from the database was rejected as a key collision — which would break any
    backfill, migration or replication that round-trips the ledger.
    """
    ledger = ledger_fixture()
    job_id = uuid4()
    submitted = [
        ResourceEvent(
            event_key="job:a:transfer:input:drawing",
            event_type=ResourceEventType.TRANSFER,
            stage=ResourceStage.IMAGE_PREPROCESSING,
            started_at=STARTED,
            finished_at=STARTED + timedelta(milliseconds=9),
            wall_ms=9,
            success=True,
            process={"bytes_read": 11359},
        ),
        ai_event("job:a:ai:analysis:1"),
        cad_event("job:a:cad:extrude:1"),
    ]
    ledger.record(job_id, submitted)

    read_back = {event.event_key: event for event in ledger.events(job_id)}
    for event in submitted:
        assert content_fingerprint(read_back[event.event_key]) == content_fingerprint(event)

    transfer = read_back["job:a:transfer:input:drawing"]
    assert transfer.cad is None
    assert transfer.ai is None
    assert transfer.process is not None and transfer.process.bytes_read == 11359

    # Re-recording what was read back is a replay, not a conflict.
    assert ledger.record(job_id, list(read_back.values())) == (0, 3)


def test_the_same_key_may_repeat_across_different_jobs():
    ledger = ledger_fixture()
    first_job, second_job = uuid4(), uuid4()
    event = ai_event("job:a:ai:analysis:1")

    assert ledger.record(first_job, [event]) == (1, 0)
    assert ledger.record(second_job, [event]) == (1, 0)


def test_null_token_counts_round_trip_without_becoming_zero():
    ledger = ledger_fixture()
    job_id = uuid4()
    unmeasured = ResourceEvent(
        event_key="job:a:ai:analysis:1",
        event_type=ResourceEventType.AI_RUN,
        stage=ResourceStage.DRAWING_ANALYSIS,
        agent_role=AgentRole.DRAWING_EXTRACTION,
        started_at=STARTED,
        success=True,
        ai={"model": "gpt-5.6-terra", "token_source": TokenSource.UNKNOWN},
    )
    ledger.record(job_id, [unmeasured])

    stored = ledger.events(job_id)[0]
    assert stored.ai is not None
    assert stored.ai.input_tokens is None
    assert stored.ai.total_tokens is None
    assert stored.ai.token_source is TokenSource.UNKNOWN


def test_estimated_tokens_stay_marked_through_storage():
    ledger = ledger_fixture()
    job_id = uuid4()
    ledger.record(
        job_id,
        [
            ai_event(
                "job:a:ai:analysis:1",
                ai={"token_source": TokenSource.ESTIMATED, "input_tokens": 900},
            )
        ],
    )
    stored = ledger.events(job_id)[0]
    assert stored.ai.token_count_estimated is True


def test_geometry_and_semantic_validation_are_counted_separately():
    """Found by the acceptance run: both are VALIDATION events, and counting
    them together claimed two geometry checks on a job that ran one."""
    ledger = ledger_fixture()
    job_id = uuid4()
    ledger.record(
        job_id,
        [
            ResourceEvent(
                event_key="job:a:validate:cad_ir:1",
                event_type=ResourceEventType.VALIDATION,
                stage=ResourceStage.SEMANTIC_VALIDATION,
                started_at=STARTED,
                success=True,
            ),
            ResourceEvent(
                event_key="job:a:validate:geometry:1",
                event_type=ResourceEventType.VALIDATION,
                stage=ResourceStage.GEOMETRY_VALIDATION,
                started_at=STARTED,
                success=True,
            ),
        ],
    )

    assert derive_counters(ledger.events(job_id)).geometry_validation_runs == 1


def test_exports_recorded_as_cad_operations_still_count_as_attempts():
    """The adapter reports its export step as a CAD operation at the EXPORT
    stage; counting only the EXPORT event type left export_attempts at zero on
    every real job."""
    ledger = ledger_fixture()
    job_id = uuid4()
    ledger.record(
        job_id,
        [
            ResourceEvent(
                event_key="job:a:cad:operation:export_step_stl",
                event_type=ResourceEventType.EXPORT,
                stage=ResourceStage.EXPORT,
                started_at=STARTED,
                success=True,
                cad={"operation_code": "export_step_stl", "operation_count": 1},
            )
        ],
    )

    assert derive_counters(ledger.events(job_id)).export_attempts == 1


def test_counters_are_derived_from_events_and_ignore_replays():
    ledger = ledger_fixture()
    job_id = uuid4()
    events = [
        ai_event("job:a:ai:analysis:1"),
        ai_event("job:a:ai:compile:1", role=AgentRole.CAD_IR_COMPILATION),
        ai_event("job:a:ai:repair:1", role=AgentRole.REPAIR),
        ResourceEvent(
            event_key="job:a:cad:session:1",
            event_type=ResourceEventType.CAD_SESSION,
            stage=ResourceStage.KOMPAS_STARTUP,
            started_at=STARTED,
            success=True,
        ),
        cad_event("job:a:cad:hole:1", success=False, failure_code="KOMPAS_FEATURE_FAILED"),
        ResourceEvent(
            event_key="job:a:export:stl",
            event_type=ResourceEventType.EXPORT,
            stage=ResourceStage.EXPORT,
            started_at=STARTED,
            success=True,
        ),
        ResourceEvent(
            event_key="job:a:review:1",
            event_type=ResourceEventType.HUMAN_REVIEW,
            stage=ResourceStage.HUMAN_REVIEW,
            started_at=STARTED,
            success=True,
            human_minutes=Decimal("12.5"),
        ),
    ]
    ledger.record(job_id, events)
    ledger.record(job_id, events)  # full resend

    counters = derive_counters(ledger.events(job_id))
    assert counters.analysis_runs == 1
    assert counters.cad_ir_generation_runs == 1
    assert counters.repair_runs == 1
    assert counters.cad_build_attempts == 1
    assert counters.cad_feature_failures == 1
    assert counters.export_attempts == 1
    assert counters.human_review_minutes == Decimal("12.5")


def register_worker_with_job(monkeypatch):
    protocol = WorkerProtocolService(
        InMemoryWorkerRepository(), "local-development-enrollment-token-change-me"
    )
    monkeypatch.setattr("app.main.worker_protocol", protocol)
    monkeypatch.setattr("app.main.resource_ledger", ledger_fixture())
    client = TestClient(app)
    registered = client.post(
        "/api/v1/workers/register",
        json={
            "enrollment_token": "local-development-enrollment-token-change-me",
            "worker_name": f"ledger-worker-{uuid4()}",
            "app_version": "0.4.0",
        },
    ).json()
    worker = protocol.repo.workers[UUID(registered["worker_id"])]
    protocol.heartbeat(worker, [WorkerCapability.KOMPAS_BUILD], ["0.1.0"], 1)
    job_id = uuid4()
    protocol.repo.jobs[job_id] = Job(
        job_id, uuid4(), JobType.BUILD_CAD, "sha256:ledger", {WorkerCapability.KOMPAS_BUILD}, "0.1.0"
    )
    protocol.claim(worker)
    return client, {"Authorization": f"Bearer {registered['credential']}"}, job_id


def batch(job_id, events) -> dict:
    return {
        "schema_version": "1.0",
        "job_id": str(job_id),
        "events": [event.model_dump(mode="json") for event in events],
    }


def test_ingestion_endpoint_is_idempotent(monkeypatch):
    client, headers, job_id = register_worker_with_job(monkeypatch)
    payload = batch(job_id, [ai_event("job:a:ai:analysis:1"), cad_event("job:a:cad:extrude:1")])
    url = f"/api/v1/workers/jobs/{job_id}/resource-events"

    first = client.post(url, headers=headers, json=payload)
    assert first.status_code == 202
    assert first.json() == {"job_id": str(job_id), "accepted": 2, "duplicates": 0}

    second = client.post(url, headers=headers, json=payload)
    assert second.json() == {"job_id": str(job_id), "accepted": 0, "duplicates": 2}


def test_ingestion_requires_the_active_lease(monkeypatch):
    client, headers, job_id = register_worker_with_job(monkeypatch)
    payload = batch(job_id, [ai_event("job:a:ai:analysis:1")])

    unauthenticated = client.post(f"/api/v1/workers/jobs/{job_id}/resource-events", json=payload)
    assert unauthenticated.status_code == 401

    other_job = uuid4()
    mismatched = client.post(
        f"/api/v1/workers/jobs/{other_job}/resource-events", headers=headers, json=payload
    )
    assert mismatched.status_code == 400


def test_ingestion_rejects_negative_and_malformed_counters(monkeypatch):
    client, headers, job_id = register_worker_with_job(monkeypatch)
    url = f"/api/v1/workers/jobs/{job_id}/resource-events"
    valid = ai_event("job:a:ai:analysis:1").model_dump(mode="json")

    negative = {**valid, "ai": {**valid["ai"], "input_tokens": -1}}
    assert client.post(
        url, headers=headers, json={"schema_version": "1.0", "job_id": str(job_id), "events": [negative]}
    ).status_code == 422

    invented = {**valid, "ai": {**valid["ai"], "token_source": "UNKNOWN"}}
    assert client.post(
        url, headers=headers, json={"schema_version": "1.0", "job_id": str(job_id), "events": [invented]}
    ).status_code == 422


def test_ingestion_reports_a_key_collision_as_conflict(monkeypatch):
    client, headers, job_id = register_worker_with_job(monkeypatch)
    url = f"/api/v1/workers/jobs/{job_id}/resource-events"
    client.post(url, headers=headers, json=batch(job_id, [ai_event("job:a:ai:analysis:1")]))

    conflicting = client.post(
        url,
        headers=headers,
        json=batch(job_id, [ai_event("job:a:ai:analysis:1", role=AgentRole.REPAIR)]),
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == ErrorCode.LEDGER_EVENT_CONFLICT
