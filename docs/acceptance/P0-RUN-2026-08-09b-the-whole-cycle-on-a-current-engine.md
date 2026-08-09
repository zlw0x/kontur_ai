# The whole cycle, on a current engine, from a stranger to an approved model

**Date:** 2026-08-09 · **Machine:** the one Codex is signed in on ·
**Drawing:** `apps/web/public/sample-drawing.png` — 60 × 30 × 8 plate, two Ø5
through-holes at x = 15 and x = 45.

The run the earlier one could not finish. The engine image was rebuilt against
CAD-IR 1.12, and everything the pilot perimeter added today ran in one sequence:
a stranger's account, an order that belongs to it, a sanitized page, a read, a
compilation, a build, a verification, the moderation queue, and an operator's
approval.

## What happened

```text
POST /api/v1/auth/register                      201   session cookie + CSRF token
POST /api/v1/drawing-jobs                       201   owner_id = the new account
  ANALYZE_DRAWING → build → verify              (no clarification round needed)
GET  /api/v1/drawing-jobs/{id}                        MANUAL_REVIEW, 6 artifacts
GET  /api/v1/operator/orders                          total waiting: 1
POST /api/v1/operator/orders/{id}/review        200   approve, v1 → v2
GET  /api/v1/drawing-jobs/{id}                        READY
GET  /api/v1/operator/orders/{id}/reviews             approve → READY from v1
```

The queue held a finished build until a person released it, which is what
`automatic_acceptance = False` is for, and the audit row records
`reviewer_id: null` — the manual operator key is not a person, and the trail says
so rather than naming a user who does not exist.

## The part

From the validation report the worker wrote by reopening its own exported files:

| | |
|---|---|
| bounding box | expected [60, 30, 8], **measured [60, 30, 8]** |
| volume | **14085.8407 mm³** |
| through holes | expected 2, **mesh-derived genus 2** |
| mesh | 1028 triangles, 0 open edges, 0 inconsistent normals |
| solids | expected 1, measured 1 |

Closed form, from the drawing rather than from the engine:

```text
60 × 30 × 8 − 2 × π × 2.5² × 8 = 14400 − 314.1593 = 14085.8407
```

Exact to four decimal places against a number nothing in the pipeline computed.

## The engine image

`cad-ai/cad-worker:latest` was six days old and spoke CAD-IR **1.11** against a
contract at 1.12 — the refusal the previous run ended on. Rebuilt, it declares
1.12, build123d 0.11.1 on OpenCascade 7.9.3.1.1, and **43 capabilities**.

## What rebuilding it uncovered

`ContainerEngineTests` skips itself unless `CAD_ENGINE_IMAGE` names an image, and
with an image that works it ran for the first time in a while. Three of its four
tests failed immediately:

```text
System.IO.FileNotFoundException :
  ...\tests\fixtures\cad-ir\lever-plate
```

`JobWith` builds a fixture path and was left without the version suffix or the
`.json` extension when the version literals were taken out of the tree. Every call
raised. Nobody found out, because **a skip in the summary line looks exactly like a
pass** — the third time that sentence has been the explanation, and the first time
the tests were in a position to say otherwise.

Fixed by taking the suffix from `CadIr.FileSuffix`, which is the rule
`test_fixture_versions` enforces everywhere else. Then:

```text
Пройден!: не пройдено 0, пройдено 35, пропущено 0, всего 35
```

**35 of 35, nothing skipped.** That is the first clean run of the launcher's whole
suite, container tests included.

## Limits, measured on the way

P1-7 shipped alongside this run, and what it is *not* is as decided as what it is —
no new table, and no per-IP request limiting, which belongs to the reverse proxy
and would be theatre in an application that sees whatever `X-Forwarded-For` it is
handed. What the application can bound exactly, because it owns the rows, is what a
known account consumes:

- **three orders in flight**, which is the limit that actually protects a pilot
  with one worker behind it;
- **twenty a day**, counted off `orders.created_at` — an upload *is* an order, so
  the daily count is the upload rate limit with nothing new written per request;
- **ten wrong passwords** and then fifteen minutes, per account and durable.

The two refusals are deliberately different. A quota answers `429` with
`Retry-After`, because the caller is authenticated and there is nothing left to
disclose. A sign-in answers the same `401` it always did: a `429` there would
announce that the address has an account, which is the one thing that endpoint's
careful wording exists to avoid.

## What is still open

The clarification round did not fire on this run — the reading settled both hole
positions from the drawing itself. That is better than the previous run and is one
sample; it is not evidence that the questions have stopped being needed.

The compile-repair observation from the earlier run is now explained rather than
outstanding: the three repairs that each broke the dependency graph were rewriting a
document the engine had refused for its *version*, so the loop was repairing a
document that was never the problem. Worth a fresh look only if it recurs against a
current image.
