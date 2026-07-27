"""Deterministic job costing.

`calculate_cost` is a pure function of (events, profile, inputs). It reads no
global configuration, no clock and no database, which is what lets a snapshot
be recomputed years later and produce the same number.

Every rate comes from the pricing profile. The engine holds no money of its
own — not a default tariff, not a fallback margin, not a rounding constant.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.contracts import (
    COST_FORMULA_VERSION,
    AiUsage,
    CostInputs,
    JobCostBreakdown,
    PricingProfile,
    ResourceEvent,
    ResourceEventType,
    ResourceStage,
    TokenSource,
)
from app.ledger.service import derive_counters

SECONDS_PER_HOUR = Decimal(3600)
BYTES_PER_GB = Decimal(10) ** 9
SECONDS_PER_DAY = Decimal(86400)
MILLION = Decimal(10) ** 6
MONEY = Decimal("0.0001")
PRICE = Decimal("0.01")


class CostEngineError(Exception):
    """The profile cannot produce a price; never silently guess one."""


def calculate_cost(
    events: list[ResourceEvent],
    profile: PricingProfile,
    inputs: CostInputs,
) -> JobCostBreakdown:
    config = profile.config
    counters = derive_counters(events)

    job_units = sum((_run_units(event.ai, config.ai_usage_weights) for event in events), Decimal(0))
    ai_allocated = (
        inputs.subscription.ai_pool_amount * job_units / inputs.subscription.period_units
    )
    ai_shadow = sum((_shadow_cost(event.ai, config.shadow_prices) for event in events), Decimal(0))

    billable_seconds = _billable_seconds(events)
    billable_hours = billable_seconds / SECONDS_PER_HOUR
    worker_cost = billable_hours * config.worker.worker_hour_cost
    cad_license_cost = billable_hours * config.worker.cad_license_hour_cost
    vps_cost = config.infrastructure.vps_cost_per_job
    storage_cost = _storage_cost(events, config.infrastructure)
    human_cost = counters.human_review_minutes * config.human.review_minute_cost

    # Everything that does not depend on the final price.
    base_cost = ai_allocated + worker_cost + cad_license_cost + vps_cost + storage_cost + human_cost

    surcharge = (
        _excess(counters.analysis_runs, config.complexity.included_analysis_runs)
        * config.complexity.analysis_retry_fee
        + _excess(counters.cad_build_attempts, config.complexity.included_cad_attempts)
        * config.complexity.cad_retry_fee
        + _excess(counters.repair_runs, config.complexity.included_repair_runs)
        * config.complexity.repair_fee
        + inputs.advanced_feature_points * config.complexity.feature_point_price
    )

    risk_percent = config.margin.risk_percent.get(inputs.job_class, Decimal(0))
    margin = config.margin.target_gross_margin
    payment_percent = config.payment.percent
    payment_fixed = config.payment.fixed

    # The payment commission is a percentage of the final price, and the final
    # price is derived from a total that includes the commission. Solving
    #   F(1-m) = (B + fixed)(1+r) + S + p*F*(1+r)
    # for F removes the circularity instead of approximating it.
    denominator = (1 - margin) - payment_percent * (1 + risk_percent)
    if denominator <= 0:
        raise CostEngineError(
            "pricing profile cannot yield a price: the payment commission and "
            "target margin consume the whole revenue"
        )
    price = ((base_cost + payment_fixed) * (1 + risk_percent) + surcharge) / denominator

    minimum = config.margin.minimum_price.get(inputs.job_class, Decimal(0))
    final_price = _round_up(max(price, minimum), config.margin.rounding_step)

    # Restate the components against the price actually charged so the
    # breakdown adds up exactly, including after the minimum and rounding.
    payment_cost = payment_percent * final_price + payment_fixed
    resource_cost = base_cost + payment_cost
    risk_reserve = resource_cost * risk_percent
    pre_margin = resource_cost + surcharge + risk_reserve
    margin_amount = max(final_price - pre_margin, Decimal(0))

    return JobCostBreakdown(
        currency=profile.currency,
        pricing_profile_code=profile.code,
        pricing_profile_version=profile.version,
        job_class=inputs.job_class,
        formula_version=COST_FORMULA_VERSION,
        job_ai_units=_money(job_units),
        ai_allocated_cost=_money(ai_allocated),
        ai_shadow_cost=_money(ai_shadow),
        worker_cost=_money(worker_cost),
        cad_license_cost=_money(cad_license_cost),
        vps_cost=_money(vps_cost),
        storage_cost=_money(storage_cost),
        human_cost=_money(human_cost),
        payment_cost=_money(payment_cost),
        resource_cost=_money(resource_cost),
        complexity_surcharge=_money(surcharge),
        risk_reserve=_money(risk_reserve),
        margin_amount=_money(margin_amount),
        final_price=final_price,
        billable_worker_seconds=_money(billable_seconds),
        counters=counters,
        token_coverage=_token_coverage(events),
    )


def _run_units(ai: AiUsage | None, weights) -> Decimal:
    """Internal AI units for one run.

    COST-ACCOUNTING writes BASE_TOKENS as `input + cached*w + ...`. Codex
    reports `input_tokens` inclusive of the cached part, so adding both would
    charge a cached token *more* than an uncached one and invert the intent of
    a 0.20 weight. The cached portion is therefore subtracted from input and
    re-added at its own weight; see ADR-015.
    """
    if ai is None or ai.token_source is TokenSource.UNKNOWN:
        return Decimal(0)
    cached = Decimal(ai.cached_input_tokens or 0)
    uncached_input = max(Decimal(ai.input_tokens or 0) - cached, Decimal(0))
    base_tokens = (
        uncached_input
        + cached * weights.cached_token
        + Decimal(ai.output_tokens or 0) * weights.output_token
        + Decimal(ai.reasoning_tokens or 0) * weights.reasoning_token
    )
    model_weight = weights.models.get(ai.model, weights.default_model) if ai.model else weights.default_model
    effort_weight = weights.reasoning.get(ai.reasoning_effort, Decimal(1)) if ai.reasoning_effort else Decimal(1)
    tier_weight = weights.service_tier.get(ai.service_tier, Decimal(1))
    return base_tokens * model_weight * effort_weight * tier_weight


def _shadow_cost(ai: AiUsage | None, prices) -> Decimal:
    if ai is None or ai.token_source is TokenSource.UNKNOWN:
        return Decimal(0)
    cached = Decimal(ai.cached_input_tokens or 0)
    uncached_input = max(Decimal(ai.input_tokens or 0) - cached, Decimal(0))
    return (
        uncached_input / MILLION * prices.input_per_million
        + cached / MILLION * prices.cached_input_per_million
        + Decimal(ai.output_tokens or 0) / MILLION * prices.output_per_million
    )


def _billable_seconds(events: list[ResourceEvent]) -> Decimal:
    """Wall time the machine was actually busy, as a union of event intervals.

    Summing every event would double count: a CAD session encloses each of its
    feature operations. Merging overlapping intervals counts that wall time
    once. Time with no event — a user thinking about a clarification question,
    or a job sitting in the queue — is never inside an interval and so is
    never billed, which is exactly what COST-ACCOUNTING requires.
    """
    spans = sorted(
        (event.started_at, event.finished_at)
        for event in events
        if event.finished_at is not None and event.finished_at > event.started_at
    )
    total = Decimal(0)
    current_start = current_end = None
    for start, end in spans:
        if current_end is None or start > current_end:
            if current_end is not None:
                total += Decimal(str((current_end - current_start).total_seconds()))
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_end is not None:
        total += Decimal(str((current_end - current_start).total_seconds()))
    return total


#: Storage measured during these stages is billed at the matching rate; every
#: other stage stores a result artifact.
_SOURCE_STAGES = {ResourceStage.IMAGE_PREPROCESSING}


def _storage_cost(events: list[ResourceEvent], rates) -> Decimal:
    source_byte_seconds = Decimal(0)
    result_byte_seconds = Decimal(0)
    egress_bytes = Decimal(0)
    for event in events:
        if event.storage_byte_seconds is not None:
            if event.stage in _SOURCE_STAGES:
                source_byte_seconds += event.storage_byte_seconds
            else:
                result_byte_seconds += event.storage_byte_seconds
        if event.event_type is ResourceEventType.TRANSFER and event.process is not None:
            egress_bytes += Decimal(event.process.bytes_written or 0)
    divisor = BYTES_PER_GB * SECONDS_PER_DAY
    return (
        source_byte_seconds / divisor * rates.source_gb_day
        + result_byte_seconds / divisor * rates.result_gb_day
        + egress_bytes / BYTES_PER_GB * rates.egress_gb
    )


def _token_coverage(events: list[ResourceEvent]) -> dict[TokenSource, int]:
    """How many AI runs were measured, summarised, estimated or unknown.

    Carried into the snapshot so a reviewer can see how much of the AI cost
    rests on real numbers before trusting the margin.
    """
    coverage: dict[TokenSource, int] = {}
    for event in events:
        if event.event_type is ResourceEventType.AI_RUN and event.ai is not None:
            coverage[event.ai.token_source] = coverage.get(event.ai.token_source, 0) + 1
    return coverage


def _excess(actual: int, included: int) -> Decimal:
    return Decimal(max(actual - included, 0))


def _round_up(value: Decimal, step: Decimal) -> Decimal:
    """Round to the next whole step; rounding down would eat into the margin."""
    steps = (value / step).to_integral_value(rounding=ROUND_CEILING)
    return (steps * step).quantize(PRICE, rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)
