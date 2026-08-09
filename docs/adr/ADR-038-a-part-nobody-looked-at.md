# ADR-038: no part reaches a customer without somebody having looked at it

**Date:** 2026-08-09 · **Status:** accepted · **Migration:** 0010 ·
**Builds on:** ADR-036 (an order is a row), ADR-037 (an order belongs to somebody)

## What was there

`automatic_acceptance` existed as an idea and nowhere as a setting. In practice it
was always on: `pipeline_status` turned "the job delivered a STEP and an STL" into
`READY`, and that was the end of it. No person was involved at any point between a
stranger's upload and a file the stranger downloads.

The reason that is not acceptable for a pilot is specific rather than nervous. The
model can produce a document that is canonically valid, builds a closed manifold,
and measures exactly what it declares — and is **not the part on the drawing**. The
shape claim (ADR-025) is what catches that, and it catches a great deal: a misread
outline, a hole count that disagrees with the reading, a missing draft. It does not
catch a reading that was wrong in the same way the compilation was wrong, and
POSTMVP-023 has a measured instance of exactly that.

The difference between "a great deal" and "all of it" is what an operator is for.

## Decision

`automatic_acceptance: bool = False`, a stored `MANUAL_REVIEW`, three decisions,
and an audit table.

### The hold happens where `has_model` is already decided

`complete_job` is the point at which the service learns a build delivered
everything a model owes, and it is the same condition — `not missing_model` — that
`pipeline_status` turns into `READY`. Putting the hold anywhere else would be a
second rule that has to be kept in step with the first.

### The hold is *stored*, not derived

`pipeline_status` could have returned `MANUAL_REVIEW` instead of `READY` when the
setting is off, and that would have been less code. It is wrong for one reason: the
queue.

An operator's page asks "what is waiting for me", and a derived status makes that a
scan of every order looking for the ones whose artifacts happen to constitute a
model. A stored status makes it `WHERE status = 'MANUAL_REVIEW'` on the index 0008
already created. The plan's phrasing was right — **build a queue, not a state.**

That in turn needed `WAITING_FOR_LOCAL_WORKER → MANUAL_REVIEW` in
`ALLOWED_TRANSITIONS`, which reads like a hole in the state machine and is not.
Since ADR-036 a drawing order's stored status does not move as the pipeline runs —
progress is read off the job — so it sits at its creation value until somebody
decides something. Every decision therefore has to be reachable from that value.

### `READY` and `FAILED` become decided statuses

The consequence nobody would have predicted from the outside, and it is the whole
reason a rejection works.

`DECIDED` held `CANCELLED`, `EXPIRED` and `MANUAL_REVIEW` — the statuses that
outrank whatever the pipeline is doing. Approving an order stores `READY`, and
`READY` was not in that set: it happened to read correctly anyway, because the
pipeline also says `READY` when a model exists.

A **rejection** does not have that luck. The files the operator rejected are still
in the artifact store, so the pipeline still sees a model, so a rejected order would
have told the customer their part was ready — the one the operator had just said was
wrong. Both are in `DECIDED` now, and both are only ever *stored* by a decision: the
pipeline's own `READY` and `FAILED` are derived and written nowhere.

### The decision and its audit row are one transaction

Not two calls, and not a best-effort write afterwards. An order that became `READY`
with no row saying who approved it is indistinguishable from one the pipeline
released by itself, which is the exact thing the setting exists to prevent. So if
the row cannot be written, the approval does not happen — `SqlOrderRepository.review`
does both inside one `sessions.begin()`, and the in-memory implementation writes the
row only after the transition has been allowed, so the two behave alike.

A table and not a log line, for the reason the plan gave and which is worth keeping:
a log rotates, is not queryable, and cannot be joined to the order it is about. The
question this has to answer months from now is "who released this part, and what did
they say about it".

### `request_changes` carries a note, or it does nothing

Three decisions: approve → `READY`, reject → `FAILED`, request changes →
`DRAWING_ANALYSIS` and a fresh round.

The last one is the only one that needed anything built. Sending the order back
through the same reading stage with the same inputs produces the same document —
a button that appears to do something. So the operator's reason travels with the
round as `operator-note.json`, a job input beside the drawing and the previous
reading, and the worker hands it to the reading agent.

Two details in the worker are load-bearing:

- **A note disables round reuse.** The reuse path exists so a clarification round
  does not pay for a second vision call, and it is exactly wrong here: a note says
  the previous *reading* was wrong, so reusing it carries the mistake into the round
  meant to fix it.
- **The note is the one piece of trusted free text in this pipeline.** Every word on
  the drawing is untrusted data and never an instruction — that rule does not move.
  A signed-in member of staff who has looked at the delivered part is a different
  thing, and the prompt says which is which. It also says the drawing wins where the
  two disagree, which is what keeps a note a correction to a reading rather than an
  override of what is drawn.

`PromptVersion` goes to `drawing-mvp-10`.

### 404 rather than 403 on the operator surface

The same rule ADR-037 set for orders. A 403 confirms the endpoint is there and worth
attacking; a customer asking for `/api/v1/operator/orders` gets the answer they would
get if it did not exist.

### `expected_version` is required and not defaulted

The optimistic lock has existed since 0008 and had nothing using it. An approval
that says "whatever version it is now" is an approval of something the operator has
not looked at, so the version they were shown travels with the decision, and a second
operator who decided in the meantime wins rather than being silently overwritten.

## What it does not do

There is no rate limit on the operator endpoints, no notification when the queue
grows, and no "how long has this been waiting" alert — the last is P1-8 and is named
there. There is no bulk approve, deliberately: the whole value of the queue is that
somebody looked at each one.

`automatic_acceptance = True` restores exactly the old behaviour, and both branches
are tested. A setting whose `True` case nobody exercises is a setting that stops
working quietly, and this one's `True` case was the *only* behaviour until now.

## What it is measured by

`apps/api/tests/test_moderation_queue.py`, fourteen of them, and the shape of the
list is the point — most are about what must not happen:

- a customer approving their own order gets 404, and the order stays held
- an approval of a version the operator did not see is `ORDER_VERSION_CONFLICT`,
  **and leaves no audit row** — a refused decision must not fill the record with
  things that did not happen
- an order cancelled while it waited never enters the queue and cannot be approved
  out of `CANCELLED`
- a rejected order does not read as `READY` even though its files are still there
- a rejection or a request for changes with no reason is refused; an approval needs
  none
- **every** decision, enumerated over `ReviewDecision` rather than exampled, leaves
  exactly one audit row naming the decision, the version decided about, and the
  status it produced
- the manual operator key's decisions record `reviewer_id: null`, because it is not
  a person

On real PostgreSQL: 0010 applied from nothing, dropped, re-applied; a refused
decision leaving neither a row nor a status change; an audit row read back through a
second repository, which is what a second API process behind one load balancer is.

In the worker: a note forces a second reading and reaches the analysis prompt; an
unparseable note is treated as absent rather than as a failure, because the half of
`request_changes` that does not depend on anybody's file being well-formed is that
the order goes round again.
