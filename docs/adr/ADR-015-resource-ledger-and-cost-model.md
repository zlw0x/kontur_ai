# ADR-015: resource ledger, subscription allocation and shadow pricing

## Status

Accepted on 2026-07-27.

## Context

Codex CLI runs against the owner's personal ChatGPT account, so there is no
per-token invoice to reconcile against. Cost has to be reconstructed from
measurements taken on the local machine, and the price shown to a customer has
to be defensible months later. `COST-ACCOUNTING.md` specifies the model; this
ADR records the decisions its implementation required.

## Decision

### The worker measures; the API prices

The worker reports `resource_events` and never a cost, a rate or a counter it
derived itself. Iteration counters are folded out of stored events by the API,
so a retried batch cannot inflate one.

### Identity and idempotency

`(job_id, event_key)` is unique, and every row also stores a fingerprint of the
submitted event. A resend of identical content is a replay; the same key with
different content is rejected as `LEDGER_EVENT_CONFLICT`. Overwriting would
break append-only and silently keeping the first would hide a worker defect.

Ingestion is scoped to the active lease. Only the worker running the job can
say what it consumed, and a batch arriving after the lease moved on belongs to
a superseded attempt.

### Identifiers stay `varchar(36)`

`COST-ACCOUNTING.md` specifies `UUID` primary keys. The v1 tables use
`varchar(36)` because the same SQLAlchemy models back the SQLite test database.
Mixing the two types across tables in one schema is worse than being uniformly
explicit, so the new tables match the existing ones. Values are still UUIDs.

### Cached tokens reduce cost rather than increasing it

The specification writes `BASE_TOKENS = input + cached*0.20 + ...`. Codex
reports `input_tokens` inclusive of the cached portion, so adding both charges
a cached token 1.2× an uncached one — the opposite of what a 0.20 weight
expresses. The engine subtracts the cached portion from input and re-adds it at
its own weight. The same correction applies to the API-equivalent shadow price.

### The payment commission is solved, not approximated

The commission is a percentage of the final price, while the final price is
derived from a total that includes the commission. Solving

```text
F(1 - margin) = (base + fixed)(1 + risk) + surcharge + percent*F*(1 + risk)
```

for `F` removes the circularity exactly. A profile whose margin and commission
consume the whole revenue is refused with a typed error rather than priced
wrong.

### Billable time is a union of intervals

Summing event durations would double count, because a CAD session encloses each
of its feature operations. Billable worker time is the union of event
intervals. Time with no event — a user considering a clarification question, or
a job waiting in the queue — falls outside every interval and is never billed.

### Unknown usage is not zero usage

A run whose token counts could not be read contributes no AI cost, rather than
being priced as a zero-token run. `token_coverage` records how many runs were
measured, summarised or estimated, so a reviewer can see how much of a margin
rests on real numbers. An untested Codex CLI version still completes the order
and records a warning event.

### Snapshots

A draft may be recalculated with any profile version. A `FINAL` snapshot is
written once — a partial unique index enforces one per job — and finalising
again returns the stored snapshot instead of repricing. It carries the formula
version and the full breakdown, so it can be explained without recomputation.

### Rates live only in a pricing profile

The cost engine holds no money: no default tariff, no fallback margin, no
rounding constant. A number enters a calculation only through a versioned
profile, which is what makes a snapshot reproducible. `calculate_cost` is a
pure function of its arguments — no clock, no database, no global config.

The shipped example profile has every monetary rate at zero. The usage weights
come from `COST-ACCOUNTING.md`, but electricity, hardware amortisation, the
KOMPAS licence and VPS costs must be measured on the real machine, and an
example must never be mistaken for a calibrated price list.

## Consequences

Prices cannot be produced until someone measures the real rates and publishes a
profile; that is intended. Subscription allocation needs `period_units` from
completed jobs in the period, supplied by the caller rather than read inside
the engine.

Storage is currently classified by stage rather than by an explicit storage
class on the event, so source and result storage are distinguished only where
the stage already implies it. If backup or egress accounting needs finer
attribution, that is a new column and a new migration, not a change to the
formula.

The weights are uncalibrated. `COST-ACCOUNTING.md` requires recalibration
against actual credit consumption, and again after 100 and 500 orders.
