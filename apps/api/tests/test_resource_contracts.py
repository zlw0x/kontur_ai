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
    ModelObservationStatus,
    PricingProfile,
    ResourceEvent,
    ResourceEventBatch,
    ResourceEventType,
    ResourceStage,
    ServiceTier,
    TokenSource,
    WorkerCapability,
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


def test_a_manifest_may_say_which_engine_it_builds_with():
    """ENGINE-MIG-007. Two engines publish manifests during the migration, and
    when their models disagree the first question is which one built the file."""
    manifest = WorkerCapabilityManifest(
        worker_version="0.4.0",
        engine={
            "engine_id": "build123d",
            "engine_version": "0.11.1",
            "kernel_id": "opencascade",
            "kernel_version": "7.9.3.1.1",
        },
        cad_ir_versions=["1.6"],
        capabilities={"solid.rectangular_prism": CapabilityStatus.BETA},
    )
    assert manifest.engine.engine_id == "build123d"
    # And `kompas_version` is left alone rather than filled with a number that
    # belongs to a different engine.
    assert manifest.kompas_version is None


def test_a_worker_that_cannot_say_which_engine_it_uses_is_still_a_worker():
    """Older workers do not send the field, and that is not a reason to refuse
    their work."""
    manifest = WorkerCapabilityManifest(
        worker_version="0.3.0",
        kompas_version="22.0",
        cad_ir_versions=["1.6"],
        capabilities={"solid.rectangular_prism": CapabilityStatus.STABLE},
    )
    assert manifest.engine is None
    assert manifest.supports(["solid.rectangular_prism"]) == []


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


def ai_run_event(**ai_overrides) -> dict:
    return {
        "event_key": "job:a:ai:analysis:1",
        "event_type": ResourceEventType.AI_RUN,
        "stage": ResourceStage.DRAWING_ANALYSIS,
        "started_at": STARTED,
        "success": True,
        "ai": {
            "requested_model": "gpt-5.6-terra",
            "model_observation_status": "EXPLICIT_NOT_REPORTED",
            **ai_overrides,
        },
    }


def test_requested_and_observed_models_are_not_collapsed_into_one_field():
    """"We asked for Terra" and "Terra is what ran" are different claims, and
    only the second justifies charging Terra's weight."""
    asked = AiUsage(
        requested_model="gpt-5.6-terra",
        model_observation_status=ModelObservationStatus.EXPLICIT_NOT_REPORTED,
    )
    assert asked.observed_model is None
    assert asked.billable_model == "gpt-5.6-terra"

    confirmed = AiUsage(
        requested_model="gpt-5.6-terra",
        observed_model="gpt-5.6-terra",
        model_observation_status=ModelObservationStatus.VERIFIED,
    )
    assert confirmed.billable_model == "gpt-5.6-terra"


def test_a_disagreement_is_not_billed_to_either_model():
    mismatched = AiUsage(
        requested_model="gpt-5.6-terra",
        observed_model="gpt-5.6-luna",
        model_observation_status=ModelObservationStatus.MISMATCH,
    )
    # Charging the requested model would overstate; charging the observed one
    # would trust a CLI that just contradicted an explicit instruction.
    assert mismatched.billable_model is None


def test_an_unattributed_run_never_falls_back_to_a_default_model():
    unknown = AiUsage(model_observation_status=ModelObservationStatus.UNKNOWN)
    assert unknown.billable_model is None


def test_the_status_must_agree_with_the_fields_it_describes():
    with pytest.raises(ValidationError):
        AiUsage(model_observation_status=ModelObservationStatus.VERIFIED)
    with pytest.raises(ValidationError):
        AiUsage(requested_model="gpt-5.6-terra", model_observation_status=ModelObservationStatus.VERIFIED)
    with pytest.raises(ValidationError):
        AiUsage(requested_model="gpt-5.6-terra", model_observation_status=ModelObservationStatus.MISMATCH)
    with pytest.raises(ValidationError):
        AiUsage(
            requested_model="gpt-5.6-terra",
            observed_model="gpt-5.6-terra",
            model_observation_status=ModelObservationStatus.EXPLICIT_NOT_REPORTED,
        )
    with pytest.raises(ValidationError):
        AiUsage(requested_model="gpt-5.6-terra", model_observation_status=ModelObservationStatus.UNKNOWN)


def test_a_new_ai_run_must_say_which_model_it_asked_for():
    job_id = uuid4()
    assert ResourceEventBatch(job_id=job_id, events=[ai_run_event()]).events[0].ai is not None

    without_model = {
        **ai_run_event(),
        "ai": {"token_source": TokenSource.UNKNOWN},
    }
    with pytest.raises(ValidationError) as caught:
        ResourceEventBatch(job_id=job_id, events=[without_model])
    assert "must record the model it requested" in str(caught.value)

    with pytest.raises(ValidationError):
        ResourceEventBatch(
            job_id=job_id,
            events=[{**ai_run_event(), "ai": None}],
        )


def test_a_non_ai_event_needs_no_model():
    """Only AI runs have a model. Requiring one everywhere would make a file
    upload undeliverable."""
    batch = ResourceEventBatch(
        job_id=uuid4(),
        events=[
            {
                "event_key": "job:a:transfer:input:drawing",
                "event_type": ResourceEventType.TRANSFER,
                "stage": ResourceStage.IMAGE_PREPROCESSING,
                "started_at": STARTED,
                "success": True,
            }
        ],
    )
    assert batch.events[0].ai is None


def test_the_coarse_capability_no_longer_names_an_engine_and_the_old_name_still_parses():
    """ENGINE-MIG-008 renamed KOMPAS_BUILD to CAD_BUILD.

    The old member stays because it is *stored*: every release before this one
    wrote it into `worker.capabilities` and `order.required_capabilities` as a JSON
    string. Deleting it would make those rows unparseable, which turns a rename
    into an outage.
    """
    assert WorkerCapability("CAD_BUILD") is WorkerCapability.CAD_BUILD
    assert WorkerCapability("KOMPAS_BUILD") is WorkerCapability.KOMPAS_BUILD
    assert WorkerCapability.CAD_BUILD != WorkerCapability.KOMPAS_BUILD


def test_the_ledger_stage_no_longer_names_an_engine_and_the_old_value_still_parses():
    """A measurement that cannot be read back is a measurement that was not taken."""
    assert ResourceStage("CAD_STARTUP") is ResourceStage.CAD_STARTUP
    assert ResourceStage("KOMPAS_STARTUP") is ResourceStage.KOMPAS_STARTUP
