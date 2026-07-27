# TASK-POSTMVP-002: cost engine, pricing profiles and capability registry

## Milestone and acceptance

Turn the ledger from POSTMVP-001 into a defensible price, and stop scheduling
work a worker cannot do. Acceptance: the same ledger and profile always produce
the same number, a completed price never changes, and an incapable worker never
receives a job.

## The formula

`calculate_cost(events, profile, inputs)` is pure — no clock, no database, no
global configuration, and no money of its own.

```text
BASE_TOKENS   = (input - cached)
              + cached    * cached_weight
              + output    * output_weight
              + reasoning * reasoning_weight

RUN_UNITS     = BASE_TOKENS * model_weight * effort_weight * tier_weight
JOB_UNITS     = sum(RUN_UNITS)
AI_ALLOCATED  = ai_pool_amount * JOB_UNITS / period_units

AI_SHADOW     = (input - cached)/1e6 * input_price
              + cached/1e6           * cached_price
              + output/1e6           * output_price

BILLABLE_SECONDS = union of event [started_at, finished_at) intervals
WORKER        = BILLABLE_SECONDS/3600 * worker_hour_cost
CAD_LICENSE   = BILLABLE_SECONDS/3600 * cad_license_hour_cost
VPS           = vps_cost_per_job
STORAGE       = gb_days * rate + egress_gb * egress_rate
HUMAN         = human_minutes * review_minute_cost

BASE          = AI_ALLOCATED + WORKER + CAD_LICENSE + VPS + STORAGE + HUMAN

SURCHARGE     = max(0, analysis_runs      - included) * analysis_retry_fee
              + max(0, cad_build_attempts - included) * cad_retry_fee
              + max(0, repair_runs        - included) * repair_fee
              + advanced_feature_points * feature_point_price

FINAL         = round_up_to_step(max(minimum_price,
                  ((BASE + payment_fixed)*(1 + risk) + SURCHARGE)
                  / ((1 - margin) - payment_percent*(1 + risk))))

PAYMENT       = payment_percent * FINAL + payment_fixed
RESOURCE      = BASE + PAYMENT
RISK_RESERVE  = RESOURCE * risk
MARGIN        = FINAL - (RESOURCE + SURCHARGE + RISK_RESERVE)
```

Three points differ from a literal reading of `COST-ACCOUNTING.md`, each
recorded in [ADR-015](adr/ADR-015-resource-ledger-and-cost-model.md):

1. **Cached tokens are subtracted from input**, because Codex reports
   `input_tokens` inclusive of them. Adding both would make caching more
   expensive than not caching.
2. **The payment commission is solved algebraically** rather than approximated,
   because it depends on the price it helps determine. A profile whose margin
   and commission consume the whole revenue raises `CostEngineError`.
3. **Billable time is a union of intervals, not a sum**, because a CAD session
   encloses its feature operations. Waiting for a user produces no event and is
   therefore never billed.

Rounding is upward to the profile's step; rounding down would eat the margin.

## Pricing profiles

Every rate, weight, fee, risk percentage, minimum price and rounding step lives
in a versioned profile. `(code, version)` is unique and immutable once
published. Recalculating a draft under a different version is how a price is
revised — never by editing a profile.

`examples/pricing-profile.example.json` ships with **every monetary rate at
zero**. The usage weights come from `COST-ACCOUNTING.md`, but electricity,
hardware amortisation, the KOMPAS licence and VPS costs have to be measured on
the real machine. A shipped example must not be mistakable for a real price
list, and a test asserts the zeros stay zero.

## Snapshots

| Status | Behaviour |
|---|---|
| `DRAFT` | replaced on every recalculation |
| `FINAL` | written once; a partial unique index enforces one per job |

Finalising an already-final job returns the stored snapshot. A retried
completion must not reprice work the customer has already been quoted. Each
snapshot carries the formula version and the full breakdown, so it can be
explained later without recomputation.

## Capability registry

A worker publishes what it can build; the API refuses to lease a job whose
operations it cannot serve. Only `beta` and `stable` qualify — see
[ADR-016](adr/ADR-016-capability-registry-gate.md). Registered today:

```text
solid.rectangular_prism      feature.hole.simple_through
export.m3d  export.step  export.stl
validate.manifold  validate.bounding_box  validate.hole_count
```

## Verification

- Python: 87 passed, 1 skipped. Covers determinism, breakdown summing to the
  final price after minimum and rounding, cached tokens costing less, unknown
  usage contributing nothing, waiting time not being billed, profile
  immutability, draft recalculation, and finalisation replay.
- .NET: 43 passed.
- The capability gate is tested on both the in-memory and SQL protocols and
  through the claim endpoint.

No price has been calculated from a real job yet, because no calibrated profile
exists. That is the next task, and it needs measurements — a smart plug for
idle/Codex/KOMPAS power draw, the actual licence cost, and the VPS bill — not
another code change.
