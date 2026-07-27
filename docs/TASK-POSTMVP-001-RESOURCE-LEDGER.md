# TASK-POSTMVP-001: resource ledger and worker instrumentation

## Milestone and acceptance

The instrumentation foundation from `CODEX-START-POST-MVP.md`. No new KOMPAS
operation is added: the confirmed MVP surface — one rectangular prism with
circular through-holes — is unchanged, and this milestone only makes what it
consumes measurable.

Acceptance: a job emits resource events, a resend never double-counts, an
unavailable metric stays null, and the existing pipeline still passes.

## What the worker records

| Stage | Event type | Notes |
|---|---|---|
| input download | `TRANSFER` | bytes read, per manifest input |
| each Codex run | `AI_RUN` | model, effort, prompt version, thread, CLI version, tokens, child CPU/peak memory |
| CAD-IR semantic validation | `VALIDATION` | one per candidate, including rejected ones |
| repair iteration | `REPAIR_ITERATION` | carries the validator code that triggered it |
| KOMPAS session | `CAD_SESSION` | wall time, operation count, result bytes |
| each adapter step | `CAD_OPERATION` | startup, document, prism, each hole, save, export |
| geometry validation | `VALIDATION` | pass/fail |
| artifact upload | `TRANSFER` | bytes written, per artifact |
| unresolved usage | `WARNING` | untested CLI version or unreadable token counts |

Wall time is always recorded. CPU time and peak memory are recorded when the
OS still reports them and are `null` otherwise — never a fabricated zero.

## Idempotency

Event keys are deterministic, for example:

```text
job:{job_id}:cad:operation:hole_003
job:{job_id}:ai:repair:1
```

`(job_id, event_key)` is unique. Each row stores a content fingerprint:

- same key, same content — replay, reported as a duplicate;
- same key, different content — rejected as `LEDGER_EVENT_CONFLICT`, because
  overwriting breaks append-only and keeping the first hides a worker defect;
- partially delivered batch — the retry appends only what is missing.

Ingestion is scoped to the active lease. A batch that arrives after the lease
moved on belongs to a superseded attempt.

## Which Codex metrics are actually available

Measured against `codex-cli 0.145.0` with `codex exec --json`. The final
`turn.completed` event carries `usage`:

| Field | Availability |
|---|---|
| `input_tokens` | present; **includes** the cached portion |
| `cached_input_tokens` | present |
| `output_tokens` | present |
| `reasoning_output_tokens` | present |
| `total_tokens` | present |
| per-run credit or money cost | **not reported** — there is none to report |
| service tier | not reported; recorded as `standard` |

Everything else in the AI record comes from the trusted host, not from Codex:
model, reasoning effort and prompt version are what the router asked for, and
the CLI version is read from `codex --version`.

`token_source` marks how the counts were obtained (`STRUCTURED`, `SUMMARY`,
`ESTIMATED`, `UNKNOWN`). A tokenizer estimate is not implemented; the enum
value exists so that when one is added it can never be mistaken for a
measurement.

An untested CLI version still parses, still completes the order, and records a
warning — the model produced valid CAD-IR either way, and failing a customer's
job over an accounting gap would be the wrong trade.

## Nullable fields

Every token count, CPU figure, memory figure, byte count and exit code is
nullable. `AiUsage` refuses a count that arrives without a `token_source`, so
"measured" and "unknown" cannot be confused once the number reaches pricing.

## Shipping

Batches of 200, three attempts with backoff, shipped while the lease is held
and before completion. Shipping never throws and never retries a 4xx: the
artifacts the customer asked for are already uploaded, losing accounting data
is a smaller failure than losing a finished model, and a rejected batch is a
defect in the worker build rather than a transient fault. Undelivered batches
are logged with the job id.

## Verification

- Python API and contracts: 87 passed, 1 skipped (PostgreSQL integration).
- .NET: 43 passed (LocalWorker 14, CodexRunner 19, KompasAdapter 7,
  GeometryValidation 3).
- Generated JSON Schemas match the contract models; OpenAPI v1 compatible.
- A migration/ORM parity test fails if a column exists in only one of them.

Not yet verified against real KOMPAS or a real Codex run on this milestone.
The first real end-to-end job after this change should be checked for a
complete event set before any pricing is trusted.

## Follow-up

- Publish a calibrated pricing profile; the shipped example is all zeros.
- Surface "a job is waiting and no enrolled worker can serve it".
- Decide whether storage needs an explicit class on the event rather than
  being inferred from the stage.
