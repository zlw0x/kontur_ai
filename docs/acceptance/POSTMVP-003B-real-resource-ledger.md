# POSTMVP-003B: first real resource-ledger run

**Date:** 2026-07-28 · **Result:** PASS, with four defects found and fixed and
three findings left open.

The point of this run was not to prove the pipeline works — the MVP already
did that. It was to find out whether the numbers the ledger records are true.
They were not, in four separate ways, none of which any unit test caught.

## Environment

| Component | Version |
|---|---|
| API / web / PostgreSQL 16 / Redis 7 | Docker Compose, `infra/docker-compose.yml` |
| KOMPAS-3D | v22 (x64), file version 22.0.0.1302 |
| Codex CLI | codex-cli 0.145.0, local ChatGPT auth |
| Local worker | 0.4.0 |

Migrations `0002_resource_ledger` and `0003_scheduler_diagnostics` applied
incrementally on top of a `0001_worker_protocol` database created during the
earlier MVP run, so the upgrade path was exercised rather than a clean create.

## Input

`scripts/make_acceptance_drawing.py` renders the reference part: a 60 × 30 × 8
mm plate with two Ø5 through-holes 30 mm apart. Generating it rather than
checking in a photograph means a failed run can be repeated against exactly
the same bytes.

## Scheduler diagnostics (POSTMVP-003A) on live data

With the worker enrolled but not yet running, the order reported:

```json
{ "claimability": "blocked", "online_workers": 0, "compatible_workers": 0,
  "blockers": [
    { "code": "NO_ONLINE_WORKERS", "detail": "every enrolled worker is stale" },
    { "code": "WORKER_HEARTBEAT_STALE", "worker_name": "DESKTOP-LQGRUAU",
      "detail": "worker has never sent a heartbeat" }]}
```

and the customer-facing view said only *"The order is waiting for an available
modelling module."* This is the case ADR-016 flagged as invisible; it is now
named precisely for an operator and vaguely, on purpose, for a customer.

## Order timeline

The drawing gives hole pitch and plate width but not hole offset from the
edge, so the analysis agent asked one clarification rather than assuming
symmetry — the intended behaviour. After the answer the order completed.

Final job `439251dd-cabf-449f-b56e-eb171f11665d`: 21 events, seven artifacts
(M3D 63 115 B, STEP 13 427 B, STL 25 628 B, plus validation report, analysis,
questions and CAD-IR).

| Measure | Value |
|---|---|
| billable worker time | 70.44 s |
| order wall clock | 70.59 s (99.8 % busy) |
| naive sum of spans | 74.90 s |
| double counting avoided by interval union | 4.46 s |

Counters: 1 analysis run, 1 CAD-IR compilation, 1 CAD build attempt,
1 geometry validation, 2 export attempts, 0 repairs.

`scripts/verify_resource_ledger.py` reports **PASS** on this job.

## Codex usage actually available

Read from `turn.completed` on `codex exec --json`:

| Field | Reported? | Example |
|---|---|---|
| `input_tokens` | yes | 14 843 |
| `cached_input_tokens` | yes, as a real 0 | 0 |
| `output_tokens` | yes | 1 114 |
| `reasoning_output_tokens` | yes | 466 |
| `total_tokens` | yes | — |
| per-run cost or credits | **no** | — |

`cached_input_tokens: 0` is a measured zero, not a missing field: the CLI emits
the key. So on this version a `null` would mean the field genuinely vanished,
which is what the parser is built to survive.

## Idempotency, checked against the live PostgreSQL

| Check | Result |
|---|---|
| resend the whole 21-event batch | 0 accepted, 21 duplicates |
| row count / billable time / counters after resend | unchanged |
| same `event_key`, different content | rejected `LEDGER_EVENT_CONFLICT` |
| ledger after the rejected batch | unchanged |

## Provoked repair

Run through the local `analyze-drawing` command with `--inject-cad-ir-fault`,
which corrupts the first compiled CAD-IR so the trusted parser rejects it. The
flag exists only on that diagnostic command; the claim loop that serves real
orders cannot reach it.

```text
AI_RUN            DRAWING_ANALYSIS     ok    28 634 ms  DRAWING_EXTRACTION
AI_RUN            CAD_IR_COMPILATION   ok    39 560 ms  CAD_IR_COMPILATION
WARNING           SEMANTIC_VALIDATION  ok                ACCEPTANCE_FAULT_INJECTED
VALIDATION        SEMANTIC_VALIDATION  FAIL      26 ms  UNSUPPORTED_FEATURE_TYPE
REPAIR_ITERATION  SEMANTIC_VALIDATION  ok
AI_RUN            CAD_IR_COMPILATION   ok    33 619 ms  REPAIR
VALIDATION        SEMANTIC_VALIDATION  ok         7 ms
```

`repair_runs = 1`, `schema_repair_runs = 1`, `analysis_runs = 1`. The rejected
candidate is visible as a failed validation, not only as a retry.

`cad_build_attempts` is 0 here rather than the 2 one might expect: the repair
was provoked at the CAD-IR semantic gate, *before* any CAD session, so no
build was attempted. A repair triggered by a failed KOMPAS build would show 2.

## Recovery

The worker was killed while holding a lease. The lease expired, the job was
re-leased as attempt 2, and it completed. No events were duplicated and no
interval was left open in the ledger.

This is also where the fourth defect surfaced — see below. The measurements
buffered by the killed attempt were lost entirely, because the worker ships
its batch once, at the end. That is a deliberate trade (shipping must not be
able to fail a job) but it means a crashed attempt is unaccounted for, not
partially accounted for.

## Cost draft

Computed on the real ledger with a deliberately non-zero **test** profile —
arbitrary numbers, not a price list:

```text
job_ai_units          39 088          resource_cost        124.0250
ai_allocated_cost    117.2640         risk_reserve          12.4025
ai_shadow_cost         3.8256         margin_amount        213.5725
worker_cost            1.1740         final_price          350.00
cad_license_cost       0.5870
vps_cost               5.0000
```

Components sum to `resource_cost` and the breakdown sums to `final_price`
exactly, after the minimum-price and rounding adjustments.

## Defects found and fixed

1. **Events read back differed from those submitted.** Every event shares one
   wide row, so a TRANSFER event with no CAD usage was reconstructed with an
   all-null `cad` object. That changed its content fingerprint, so re-recording
   events read from the database was rejected as a key collision — breaking any
   backfill, migration or replication that round-trips the ledger.

2. **Semantic validation was counted as geometry validation.** Both are
   `VALIDATION` events; the counter did not discriminate by stage, so every job
   claimed two geometry checks having run one.

3. **All CAD steps were recorded as `FEATURE_BUILD`.** KOMPAS startup, document
   creation, save and export were indistinguishable from actual modelling,
   `export_attempts` was always 0, and because every step shared one finish
   timestamp the operations were stored in an order the build never ran in.

4. **The attempt was missing from the event identity.** `attempt_no` was
   hardcoded to 1 and the event key carried no attempt, even though the worker
   is told which attempt it is on. A retry re-measures the same stages, so had
   the first attempt shipped anything, the second would have resubmitted its
   keys with different timings, been rejected as a collision, and lost its
   measurements silently. In this run attempt 1 shipped nothing, which is the
   only reason it looked fine.

Each fix carries a regression test naming this run as its origin.

## Open findings

- **`model` is recorded as NULL.** `CodexModelRouter` pins no model, so Codex
  uses its default and the worker honestly records "unknown". AI cost
  allocation therefore falls back to `default_model` weight for every run.
  Model-weighted allocation is meaningless until the router names a model.

- **The clarification protocol carries one number per question.** The agent
  asked for two hole-centre coordinates in a single question; `ClarificationAnswer`
  can express one scalar. The answer was accepted and the compile stage
  recovered the rest from the analysis, but the contract cannot represent what
  the agent asked.

- **A crashed attempt is unaccounted for.** Events are buffered until the end
  of the job. Incremental shipping would close that gap at the cost of more
  round trips and a partially-written ledger for an attempt that may be
  abandoned.

## Verification after the fixes

- Python 127 passed, 1 skipped (PostgreSQL integration).
- .NET 45 passed (LocalWorker 16, CodexRunner 19, KompasAdapter 7,
  GeometryValidation 3).
- A second full order after the fixes: stages now recorded as
  `KOMPAS_STARTUP` / `DOCUMENT_BUILD` / `FEATURE_BUILD` / `EXPORT`, operations
  in true execution order, `geometry_validation_runs = 1`,
  `export_attempts = 2`, audit PASS.
- No KOMPAS or worker process left running.

The ledger's numbers can now be trusted for this pipeline. They still cannot
be turned into a price, because no calibrated pricing profile exists.
