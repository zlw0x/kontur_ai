# ADR-036: an order is a row, and there is one vocabulary for it

## Status

Accepted on 2026-08-05. Migration 0008. No CAD-IR change — this is the service
around the engine, not the contract.

## Context

Jobs, artifacts, workers, the resource ledger and the cost snapshots have been in
PostgreSQL since migrations 0001 and 0002. The order — the thing a customer
actually has — was two dictionaries in the API process:

```python
order_records: dict[uuid.UUID, OrderRecord] = {}
drawing_orders: dict[uuid.UUID, dict] = {}
```

A restart lost every order in flight. A second API process never saw the first
one's, so the service could not be run behind a load balancer at all. The drawing
cycle survived a restart only because its tracking was *also* written to
`orders/{id}/drawing-tracking.json` beside the artifacts — a database with no
transactions, no constraints and no way to be locked.

Reading the code to plan the move turned up two things worse than the missing
durability, and they changed what this ADR decides.

**The stored status was written and never read.** It was set to
`WAITING_FOR_LOCAL_WORKER` when an order was created and moved only by the manual
`POST /orders/{id}/transition` endpoint. No stage of the pipeline touched it.
Persisting that field unchanged would have made a lie durable: the row would say
`WAITING_FOR_LOCAL_WORKER` about an order whose page already said "Модель готова".

**The API answered in two vocabularies at once.** `get_drawing_job` computed:

```python
status = ("READY" if has_model
          else "WAITING_FOR_USER_ANSWERS" if questions
          else job.status.value)
```

The first two are `OrderStatus`. The third is `JobStatus` — `PENDING`, `LEASED`,
`PAUSED`, `FAILED` — so which set of words a customer got depended on which branch
fired, and `statusCopy` in `apps/web/app/page.tsx` had to carry both. Three
representations of "where is this order", none of them authoritative.

## Decision

**The row holds what only the order knows. The job holds progress. The API answers
in one vocabulary, computed in one place.**

### 1. `orders` is a narrow table

`id`, `status`, `version`, `created_at`, `updated_at`, `latest_job_id`,
`source_job_id`, `clarification_round`. That is all.

Progress is deliberately not here. A job already records its lease, its attempt
count, its failure code and its `retry_after`, all kept current by the worker
protocol and the reaper (ADR: migration 0007). Copying that onto the order would be
a second place for one truth to live, and the second place is always the one that
goes stale — which is exactly the arrangement `drawing-tracking.json` and
`order_records` were already in. The same argument that keeps the capability list
in the engine rather than in the worker.

What the row does hold is what nothing can recompute: which job is answering now,
which job holds the page every clarification round copies, how many rounds have
been spent, and **a status somebody decided**.

### 2. Progress is derived, in `app/orders/progress.py`

`pipeline_status(job, has_model, has_questions) -> OrderStatus` is the only place
`JobStatus` becomes `OrderStatus`:

| job | order |
|---|---|
| `PENDING` | `WAITING_FOR_LOCAL_WORKER` |
| `LEASED`, by job type | `DRAWING_ANALYSIS` / `CAD_BUILDING` / `CAD_VALIDATION` |
| `PAUSED` | `PAUSED` |
| `FAILED` | `FAILED` |
| model artifacts present | `READY` |
| readable questions present | `WAITING_FOR_USER_ANSWERS` |

`LEASED` says a worker holds the job and says nothing about what it is doing. The
job's **type** does, and it is the only thing that does — which is why a single
"working" status would have been the mixture again under a different name.

`OrderStatus` gains `PAUSED` to make this total. It is **derived-only**: nothing
transitions into or out of it, because a pause is a fact about a job and the reaper
is what ends it. `DERIVED_FROM_THE_JOB` names that set, and a test asserts such a
status is unreachable from both directions — an empty transition set means "not
stored" here, not "terminal", and those must not be confused.

### 3. A decision outranks an observation

`CANCELLED`, `EXPIRED` and `MANUAL_REVIEW` are somebody's decision, so when the row
holds one it is the answer regardless of what the job is doing. Cancelling does not
reach into the worker and stop a build — the worker holds a lease, will finish, and
its artifacts will be stored. What must not happen is the page reporting progress on
an order the customer cancelled.

This is what makes the stored `status` stop being write-only: it is read on every
poll, and it is the column P0-5's moderation queue will write.

### 4. The tracking file is read and no longer written

Orders created before 0008 have only `drawing-tracking.json`. Dropping the read
would strand every one of them behind a 404, so it is read once, a row is written
from it, and every later request takes the row. The same order migration 0006 used:
the rows come first, the name goes second.

`put_drawing_tracking` is kept beside its reader on purpose, though nothing in the
request path calls it. The adoption test must produce exactly the bytes the reader
parses; a test hand-writing that JSON could drift from it, and the drift would show
up as an adoption path that passes its own test and fails on a real file.

### 5. Two implementations, one switch

`InMemoryOrderRepository` and `SqlOrderRepository`, chosen by the existing
`worker_repository_mode` — one tumbler, not a second one to forget. Every repository
test runs over both.

`OrderStateService.transition` stays the pure function it was and does the deciding.
The SQL repository wraps it in `SELECT … FOR UPDATE`, which is what the `version`
column always needed and, against a dictionary, never had: reading a version,
deciding on it and then writing is exactly the interleaving an optimistic check is
meant to catch and cannot when both readers see 3.

## What was measured

On a real PostgreSQL 16, with every migration applied in order from an empty
database:

- The whole schema builds, `0008` included, and the API's own repository serves the
  **migrated** schema rather than one built by `create_all` — the two agreeing is
  what `test_migration_parity.py` asserts and what this checks in fact.
- `0008` down drops the table and up re-applies cleanly.
- One Python process creates a drawing order and cancels it; a **second Python
  process**, a fresh API over the same database, reads it back as `CANCELLED`.
  Before this change the second process would have found the order — through the
  tracking file — and reported `PENDING`, because the cancellation lived only in the
  first process's memory. That is the failure this ADR is about, and it was silent.
- The version conflict is refused under a real row lock, not just under SQLite's
  parse-and-ignore of `FOR UPDATE`.

## Consequences

The customer-facing status strings change: `PENDING` becomes
`WAITING_FOR_LOCAL_WORKER`, `LEASED` becomes the named stage. `statusCopy`,
`getProgress` and the status-pill CSS move with them in the same commit; a
`working` set replaces three comparisons against `"LEASED"`.

`GET /api/v1/drawing-jobs/{order_id}` is not a typed response model, so neither
`check_openapi_compatibility.py` nor the schema check can see this — the web is the
only consumer and it moves in lockstep. Worth stating rather than discovering.

Regenerating the published document for `OrderStatus.PAUSED` turned up that
`schemas/openapi.v1.json` had **been stale since migration 0007**: `retry_after` was
added to `JobFailureRequest` and `JobFailureAck` and nothing regenerated it. Neither
existing check could see that — `validate_schemas.py` checks the document is
well-formed, `check_openapi_compatibility.py` checks nothing v1 promised has
disappeared, and a field that never arrived fails neither. `generate_openapi.py`
gains `--check` and CI runs it, the same arrangement `generate_schemas.py` has had
all along. Nothing in the .NET worker mirrors `OrderStatus`, so no contract crosses
that boundary.

**What this does not do**, and none of it is implied:

- Artifact **bytes** stay on local disk behind `LocalArtifactStore`. The rows
  describing them are already in PostgreSQL; object storage is an infrastructure
  decision with a bucket and a credential behind it.
- An order still has no owner. Users, sessions and ownership are P0-1, and this
  migration does not guess the column.
- No moderation queue. This unblocks it — `MANUAL_REVIEW` is now a state that
  survives a restart and outranks the pipeline — and does not build it.
