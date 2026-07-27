import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import (
    AiUsage,
    CapabilityStatus,
    PricingProfile,
    ResourceEvent,
    ResourceEventBatch,
    ResourceEventType,
    ResourceStage,
    ServiceTier,
    TokenSource,
    WorkerCapabilityManifest,
)

STARTED = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).parents[3]


def event(**overrides) -> dict:
    return {
        "event_key": "job:1:cad:attempt:1:operation:extrude:feature_001",
        "event_type": ResourceEventType.CAD_OPERATION,
        "stage": ResourceStage.FEATURE_BUILD,
        "started_at": STARTED,
        "finished_at": STARTED + timedelta(seconds=3),
        "wall_ms": 3000,
        "success": True,
        **overrides,
    }


def test_token_counts_must_be_non_negative_and_may_be_null():
    assert AiUsage().input_tokens is None
    with pytest.raises(ValidationError):
        AiUsage(token_source=TokenSource.STRUCTURED, input_tokens=-1)
    with pytest.raises(ValidationError):
        AiUsage(token_source=TokenSource.STRUCTURED, output_tokens=-5)


def test_token_counts_require_a_known_source_and_estimates_are_flagged():
    with pytest.raises(ValidationError):
        AiUsage(input_tokens=100)
    measured = AiUsage(token_source=TokenSource.STRUCTURED, input_tokens=100)
    assert measured.token_count_estimated is False
    guessed = AiUsage(token_source=TokenSource.ESTIMATED, input_tokens=100)
    assert guessed.token_count_estimated is True


def test_cached_input_tokens_cannot_exceed_input_tokens():
    with pytest.raises(ValidationError):
        AiUsage(token_source=TokenSource.STRUCTURED, input_tokens=10, cached_input_tokens=11)
    assert AiUsage(
        token_source=TokenSource.STRUCTURED, input_tokens=10, cached_input_tokens=10
    ).cached_input_tokens == 10


def test_event_rejects_inverted_interval_and_contradictory_outcome():
    with pytest.raises(ValidationError):
        ResourceEvent(**event(finished_at=STARTED - timedelta(seconds=1)))
    with pytest.raises(ValidationError):
        ResourceEvent(**event(failure_code="KOMPAS_TIMEOUT"))
    failed = ResourceEvent(**event(success=False, failure_code="KOMPAS_TIMEOUT"))
    assert failed.failure_code == "KOMPAS_TIMEOUT"


def test_ai_usage_only_attaches_to_ai_runs():
    usage = AiUsage(token_source=TokenSource.STRUCTURED, input_tokens=1, service_tier=ServiceTier.STANDARD)
    with pytest.raises(ValidationError):
        ResourceEvent(**event(ai=usage))
    accepted = ResourceEvent(
        **event(event_type=ResourceEventType.AI_RUN, stage=ResourceStage.DRAWING_ANALYSIS, ai=usage)
    )
    assert accepted.ai is not None


def test_event_key_pattern_and_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        ResourceEvent(**event(event_key="job 1/cad"))
    with pytest.raises(ValidationError):
        ResourceEvent(**event(cost_rub=10))


def test_batch_rejects_duplicate_keys_inside_one_request():
    job_id = uuid4()
    first = event()
    second = event(event_key="job:1:cad:attempt:1:operation:extrude:feature_002")
    assert len(ResourceEventBatch(job_id=job_id, events=[first, second]).events) == 2
    with pytest.raises(ValidationError):
        ResourceEventBatch(job_id=job_id, events=[first, dict(first)])


def test_manifest_reports_capabilities_it_cannot_serve():
    manifest = WorkerCapabilityManifest(
        worker_version="0.4.0",
        cad_ir_versions=["0.1.0"],
        capabilities={
            "solid.rectangular_prism": CapabilityStatus.STABLE,
            "feature.hole.simple_through": CapabilityStatus.BETA,
            "solid.revolve": CapabilityStatus.EXPERIMENTAL,
            "feature.shell": CapabilityStatus.DISABLED,
        },
    )
    assert manifest.supports(["solid.rectangular_prism", "feature.hole.simple_through"]) == []
    assert manifest.supports(["solid.revolve"]) == ["solid.revolve"]
    assert manifest.supports(["feature.shell"]) == ["feature.shell"]
    assert manifest.supports(["surface.loft"]) == ["surface.loft"]


def test_manifest_rejects_malformed_capability_keys():
    with pytest.raises(ValidationError):
        WorkerCapabilityManifest(
            worker_version="0.4.0",
            cad_ir_versions=["0.1.0"],
            capabilities={"Solid Prism": CapabilityStatus.STABLE},
        )


def example_profile() -> dict:
    return json.loads(
        (REPO_ROOT / "examples" / "pricing-profile.example.json").read_text(encoding="utf-8")
    )


def test_example_pricing_profile_parses_and_ships_uncalibrated():
    profile = PricingProfile(**example_profile())
    assert profile.currency == "RUB"
    assert profile.config.margin.target_gross_margin == Decimal("0.60")
    # Every monetary rate must stay zero until it is measured on real
    # hardware; a shipped example must never look like a real price list.
    assert profile.config.worker.worker_hour_cost == 0
    assert profile.config.infrastructure.vps_cost_per_job == 0
    assert all(value == 0 for value in profile.config.margin.minimum_price.values())


def test_pricing_profile_rejects_impossible_margin_and_validity_window():
    document = example_profile()
    document["config"]["margin"]["target_gross_margin"] = "1.0"
    with pytest.raises(ValidationError):
        PricingProfile(**document)

    document = example_profile()
    document["valid_to"] = document["valid_from"]
    with pytest.raises(ValidationError):
        PricingProfile(**document)

    document = example_profile()
    document["config"]["margin"]["rounding_step"] = "0"
    with pytest.raises(ValidationError):
        PricingProfile(**document)
