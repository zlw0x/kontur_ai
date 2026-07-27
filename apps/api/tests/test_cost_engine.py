import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.contracts import (
    AgentRole,
    CostInputs,
    CostSnapshotStatus,
    ErrorCode,
    JobClass,
    PricingProfile,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
    TokenSource,
)
from app.costing.engine import CostEngineError, calculate_cost
from app.costing.service import CostServiceError, CostSnapshotService, PricingProfileStore
from app.database import Base, create_session_factory

STARTED = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).parents[3]


def profile(**config_overrides) -> PricingProfile:
    """A calibrated-looking profile. These are test numbers, not a price list."""
    document = json.loads(
        (REPO_ROOT / "examples" / "pricing-profile.example.json").read_text(encoding="utf-8")
    )
    config = document["config"]
    config["shadow_prices"] = {
        "input_per_million": "100",
        "cached_input_per_million": "10",
        "output_per_million": "400",
    }
    config["worker"] = {"worker_hour_cost": "60", "cad_license_hour_cost": "30"}
    config["infrastructure"]["vps_cost_per_job"] = "5"
    config["human"]["review_minute_cost"] = "20"
    config["complexity"] = {
        "included_analysis_runs": 1,
        "analysis_retry_fee": "25",
        "included_cad_attempts": 1,
        "cad_retry_fee": "40",
        "included_repair_runs": 1,
        "repair_fee": "15",
        "feature_point_price": "12",
    }
    for key, value in config_overrides.items():
        config[key] = {**config.get(key, {}), **value}
    document["config"] = config
    return PricingProfile(**document)


def inputs(**overrides) -> CostInputs:
    return CostInputs(
        **{
            "job_class": JobClass.AUTO_STANDARD,
            "subscription": {"ai_pool_amount": "3000", "period_units": "1000000"},
            **overrides,
        }
    )


def ai_run(key: str, role: AgentRole, seconds: int = 30, **ai_overrides) -> ResourceEvent:
    return ResourceEvent(
        event_key=key,
        event_type=ResourceEventType.AI_RUN,
        stage=ResourceStage.DRAWING_ANALYSIS,
        agent_role=role,
        started_at=STARTED,
        finished_at=STARTED + timedelta(seconds=seconds),
        wall_ms=seconds * 1000,
        success=True,
        ai={
            **{
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "token_source": TokenSource.STRUCTURED,
                "input_tokens": 10_000,
                "cached_input_tokens": 4_000,
                "output_tokens": 2_000,
            },
            **ai_overrides,
        },
    )


def span(key: str, event_type, stage, offset: int, seconds: int, **overrides) -> ResourceEvent:
    return ResourceEvent(
        **{
            "event_key": key,
            "event_type": event_type,
            "stage": stage,
            "started_at": STARTED + timedelta(seconds=offset),
            "finished_at": STARTED + timedelta(seconds=offset + seconds),
            "wall_ms": seconds * 1000,
            "success": True,
            **overrides,
        }
    )


def typical_job() -> list[ResourceEvent]:
    return [
        ai_run("job:a:ai:analysis:1", AgentRole.DRAWING_EXTRACTION, seconds=40),
        ai_run("job:a:ai:compile:1", AgentRole.CAD_IR_COMPILATION, seconds=35),
        span("job:a:cad:session:1", ResourceEventType.CAD_SESSION, ResourceStage.KOMPAS_STARTUP, 60, 90),
        # Nested inside the CAD session above; must not be billed twice.
        span("job:a:cad:prism:1", ResourceEventType.CAD_OPERATION, ResourceStage.FEATURE_BUILD, 70, 5),
        span("job:a:cad:hole:1", ResourceEventType.CAD_OPERATION, ResourceStage.FEATURE_BUILD, 80, 4),
        span("job:a:export:stl", ResourceEventType.EXPORT, ResourceStage.EXPORT, 150, 10),
        span("job:a:validate:1", ResourceEventType.VALIDATION, ResourceStage.GEOMETRY_VALIDATION, 160, 6),
    ]


def test_cost_is_deterministic_for_the_same_ledger_and_profile():
    events, pricing, cost_inputs = typical_job(), profile(), inputs()
    first = calculate_cost(events, pricing, cost_inputs)
    second = calculate_cost(list(reversed(events)), pricing, cost_inputs)
    assert first == second


def test_breakdown_adds_up_to_the_final_price():
    result = calculate_cost(typical_job(), profile(), inputs())
    components = (
        result.ai_allocated_cost
        + result.worker_cost
        + result.cad_license_cost
        + result.vps_cost
        + result.storage_cost
        + result.human_cost
        + result.payment_cost
    )
    assert abs(components - result.resource_cost) <= Decimal("0.0001")
    total = result.resource_cost + result.complexity_surcharge + result.risk_reserve + result.margin_amount
    assert abs(total - result.final_price) <= Decimal("0.01")


def test_overlapping_events_bill_wall_time_once():
    result = calculate_cost(typical_job(), profile(), inputs())
    # 0-40 and 0-35 AI runs merge to 40s; 60-150 CAD session absorbs both
    # nested operations; 150-160 export; 160-166 validation.
    assert result.billable_worker_seconds == Decimal("146.0000")


def test_time_waiting_for_the_user_is_never_billed():
    events = typical_job()
    late = span(
        "job:a:cad:session:2",
        ResourceEventType.CAD_SESSION,
        ResourceStage.KOMPAS_STARTUP,
        offset=100_000,  # the user answered a clarification a day later
        seconds=30,
    )
    baseline = calculate_cost(events, profile(), inputs()).billable_worker_seconds
    with_gap = calculate_cost(events + [late], profile(), inputs()).billable_worker_seconds
    assert with_gap - baseline == Decimal("30.0000")


def test_unknown_token_counts_contribute_no_ai_cost_instead_of_zero_tokens():
    measured = calculate_cost(
        [ai_run("job:a:ai:analysis:1", AgentRole.DRAWING_EXTRACTION)], profile(), inputs()
    )
    unmeasured = calculate_cost(
        [
            ai_run(
                "job:a:ai:analysis:1",
                AgentRole.DRAWING_EXTRACTION,
                token_source=TokenSource.UNKNOWN,
                input_tokens=None,
                cached_input_tokens=None,
                output_tokens=None,
            )
        ],
        profile(),
        inputs(),
    )
    assert measured.ai_allocated_cost > 0
    assert unmeasured.ai_allocated_cost == 0
    assert unmeasured.token_coverage == {TokenSource.UNKNOWN: 1}


def test_cached_tokens_are_cheaper_than_uncached_ones():
    """A cached token must reduce cost; the naive reading of the spec formula
    would make it more expensive than an uncached one."""
    all_fresh = calculate_cost(
        [ai_run("job:a:ai:1", AgentRole.DRAWING_EXTRACTION, cached_input_tokens=0)],
        profile(),
        inputs(),
    )
    mostly_cached = calculate_cost(
        [ai_run("job:a:ai:1", AgentRole.DRAWING_EXTRACTION, cached_input_tokens=9_000)],
        profile(),
        inputs(),
    )
    assert mostly_cached.ai_allocated_cost < all_fresh.ai_allocated_cost
    assert mostly_cached.ai_shadow_cost < all_fresh.ai_shadow_cost


def test_extra_iterations_land_in_the_surcharge_not_the_resource_cost():
    events = typical_job()
    retried = events + [
        ai_run("job:a:ai:analysis:2", AgentRole.DRAWING_EXTRACTION, seconds=40),
        ai_run("job:a:ai:repair:1", AgentRole.REPAIR, seconds=20),
        ai_run("job:a:ai:repair:2", AgentRole.REPAIR, seconds=20),
    ]
    baseline = calculate_cost(events, profile(), inputs())
    result = calculate_cost(retried, profile(), inputs())
    assert baseline.complexity_surcharge == 0
    # one analysis retry beyond the included run, one repair beyond the one
    # included repair: 25 + 15
    assert result.complexity_surcharge == Decimal("40.0000")
    assert result.counters.analysis_runs == 2
    assert result.counters.repair_runs == 2


def test_payment_commission_is_solved_against_the_final_price():
    pricing = profile(payment={"percent": "0.05", "fixed": "3"})
    result = calculate_cost(typical_job(), pricing, inputs())
    expected = Decimal("0.05") * result.final_price + Decimal(3)
    assert abs(result.payment_cost - expected) <= Decimal("0.0001")


def test_impossible_margin_and_commission_combination_is_refused():
    pricing = profile(
        payment={"percent": "0.5", "fixed": "0"},
        margin={"target_gross_margin": "0.60", "rounding_step": "10"},
    )
    with pytest.raises(CostEngineError):
        calculate_cost(typical_job(), pricing, inputs())


def test_minimum_price_and_rounding_step_are_honoured():
    pricing = profile(
        margin={
            "target_gross_margin": "0.60",
            "rounding_step": "50",
            "minimum_price": {"AUTO_STANDARD": "900"},
            "risk_percent": {"AUTO_STANDARD": "0.10"},
        }
    )
    result = calculate_cost(typical_job(), pricing, inputs())
    assert result.final_price >= Decimal("900")
    assert result.final_price % Decimal("50") == 0


def test_a_different_profile_version_changes_the_price():
    events = typical_job()
    cheap = calculate_cost(events, profile(), inputs())
    document = profile().model_dump(mode="json")
    document["version"] = 2
    document["config"]["worker"]["worker_hour_cost"] = "600"
    expensive = calculate_cost(events, PricingProfile(**document), inputs())
    assert expensive.final_price > cheap.final_price
    assert expensive.pricing_profile_version == 2


def store_fixture():
    engine, sessions = create_session_factory("sqlite://")
    Base.metadata.create_all(engine)
    return PricingProfileStore(sessions), CostSnapshotService(sessions)


def test_pricing_profile_versions_are_immutable_once_published():
    profiles, _ = store_fixture()
    pricing = profile()
    profiles.publish(pricing)
    with pytest.raises(CostServiceError) as caught:
        profiles.publish(pricing)
    assert caught.value.code == ErrorCode.IDEMPOTENCY_CONFLICT

    stored_id, stored = profiles.get(pricing.code, pricing.version)
    assert stored.config.worker.worker_hour_cost == Decimal("60")
    assert stored_id is not None


def test_unknown_pricing_profile_is_a_typed_error():
    profiles, _ = store_fixture()
    with pytest.raises(CostServiceError) as caught:
        profiles.get("missing", 1)
    assert caught.value.code == ErrorCode.PRICING_PROFILE_UNKNOWN


def test_draft_can_be_recalculated_but_a_final_snapshot_cannot():
    profiles, snapshots = store_fixture()
    pricing = profile()
    profile_id = profiles.publish(pricing)
    job_id = uuid4()
    events = typical_job()

    draft = snapshots.save_draft(job_id, profile_id, calculate_cost(events, pricing, inputs()))
    assert draft.status is CostSnapshotStatus.DRAFT

    recalculated = snapshots.save_draft(
        job_id, profile_id, calculate_cost(events, pricing, inputs(advanced_feature_points="4"))
    )
    assert recalculated.breakdown.final_price > draft.breakdown.final_price

    final = snapshots.finalize(job_id, profile_id, recalculated.breakdown)
    assert final.status is CostSnapshotStatus.FINAL

    with pytest.raises(CostServiceError) as caught:
        snapshots.save_draft(job_id, profile_id, calculate_cost(events, pricing, inputs()))
    assert caught.value.code == ErrorCode.COST_SNAPSHOT_IMMUTABLE


def test_finalising_twice_returns_the_price_already_shown():
    profiles, snapshots = store_fixture()
    pricing = profile()
    profile_id = profiles.publish(pricing)
    job_id = uuid4()

    first = snapshots.finalize(job_id, profile_id, calculate_cost(typical_job(), pricing, inputs()))
    # A retried completion must not reprice the job, even with a fuller ledger.
    replay = snapshots.finalize(
        job_id,
        profile_id,
        calculate_cost(typical_job(), pricing, inputs(advanced_feature_points="10")),
    )
    assert replay.id == first.id
    assert replay.breakdown.final_price == first.breakdown.final_price
