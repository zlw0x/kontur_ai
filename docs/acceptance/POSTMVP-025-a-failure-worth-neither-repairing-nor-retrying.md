# A failure worth neither repairing nor retrying — acceptance

**Date:** 2026-08-04 · **Result:** the third case is in, and the run that asked for it
found a second, larger defect underneath: **a Codex failure on an online order was never
reported at all.**

## What the run did

A run meant to close the bushing never reached the model:

```text
{"type":"error","message":"You've hit your usage limit … try again at Aug 8th, 2026 8:44 AM"}
{"type":"turn.failed"}
```

The job stayed `LEASED`, `output/` was empty, and the order page said "waiting" — the exact
silence `JobStatus.FAILED` had been added that same day to end.

## The reason the local session gave, and the reason underneath it

The diagnosis was that `BuildFeedback` splits failures in two and the cases are three. That
is right, and it is the smaller half.

A worker reports a failure when the code is **repairable** or the attempt was the **last**. A
quota failure is neither: no document fixes it, and it was the first of three. So it goes
back to the queue to be told the same thing twice more, and only the third attempt reports
anything. Hence the third case: a failure that is neither repairable by rewriting nor worth
retrying, because nothing changes until a date.

**But the branch that reports was never reached.** `RunClaimedJobAsync` caught
`WorkerException`. A Codex failure raises `CodexRunnerException`, and the two carry the same
shape — a code and a safe message — while **neither derives from the other**. So the
exception went past that `catch` entirely, into the claim loop's blanket
`catch { backoff }`, which is where every unnamed exception goes. Not three silent retries:
**no report on any attempt, for every Codex failure there is** — an exhausted quota, a timed
-out run, a CLI that is not installed, a malformed event stream.

That is why `output/` was empty *and* the job was still leased. Nothing had decided anything
about it.

## What the code the failure actually carried

One step off, and worth recording because acting on the note as written would have fixed
nothing. `CODEX_BUDGET_EXHAUSTED` is **this worker's own per-order run counter**
(`CodexBudgetState.Reserve`) and never comes from the CLI. The account quota arrives through
`LocalCodexRunner.MapExit`, which reads the error text:

```csharp
parser.ErrorText.Contains("rate") || parser.ErrorText.Contains("limit")
    ? "CODEX_CAPACITY_LIMIT" : "CODEX_RUN_FAILED"
```

"You've hit your usage limit" contains *limit*, so the measured failure is
**`CODEX_CAPACITY_LIMIT`**. Both codes are now in the third case — the quota because it
returns on a date, the run budget because the count is deterministic and the same drawing
through the same policy exhausts it in the same place every time — and `MapExit` is
`internal` with a test that feeds it the message from the run verbatim.

The text match is a weakness and is left standing with the reason written beside it: the CLI
reports the condition in prose and there is nothing else to match on. A message reworded
upstream reads as `CODEX_RUN_FAILED` and goes back to the queue, which is the safe direction.

## The distinction the third case rests on

Not "everything about the machine". A container that would not start may start; an
interpreter may be installed; on a fleet the next worker may already have one. Report those
and an order that would have succeeded on the next attempt is told it failed.

What makes the quota different is that **a retry cannot observe a change**. This service
reaches the model through one locally authenticated CLI on one trusted machine — that is a
rule in `CLAUDE.md`, not a deployment detail — so there is no second account for a retry to
find, and the date is four days away.

## What is in

| change | where |
|---|---|
| `BuildFeedback.WillBeTheSameNextTime`, with `CODEX_CAPACITY_LIMIT` and `CODEX_BUDGET_EXHAUSTED` | `apps/local-worker/BuildFeedback.cs` |
| `ClaimLoop.Typed` — a failure this side can name, from either exception type | `apps/local-worker/Pipeline.cs` |
| `ClaimLoop.EndsTheJob` — the three reasons, separated so each is assertable | same |
| `LocalCodexRunner.MapExit` made internal, and asserted against the real message | `packages/codex-runner/` |

Both new helpers are `internal` rather than inlined for the reason the local session gave
about `CreateDrawingPipeline`: a decision nothing can assert is a decision nobody checked.
Neither needs an HTTP client or a lease.

## Tests

| suite | result |
|---|---|
| .NET | **6 + 89 + 31 + 33 = 159 passed**, 4 container tests skipped (no `CAD_ENGINE_IMAGE`) |
| Python | 926 passed, 1 skipped |

18 new: 10 in `BuildFeedbackTests` for the third case and its boundary, 8 in
`ClaimedJobFailureTests` for the recognition and the decision, 2 in
`CodexEventParserTests` for the mapping.

## What is not in

**The report itself is still untested end to end.** These assert that the worker decides to
report; that the API receives it and the page shows it is `test_job_failure.py` and the web
work from POSTMVP-023. Closing the loop needs a claimed job against a live API, which is a
run.

**The quota cannot be pre-empted.** A stage that knows the quota is exhausted still starts a
process, waits for it to fail and reports. Reading the reset date out of the message and
refusing to claim until then would be a scheduler decision, and the customer is better served
by being told than by a queue that goes quiet.
