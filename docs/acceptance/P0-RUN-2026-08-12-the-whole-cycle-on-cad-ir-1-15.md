# The whole cycle on CAD-IR 1.15, and the health check that could never pass

**Date:** 2026-08-12 · **Machine:** the one Codex is signed in on ·
**Drawing:** `apps/web/public/sample-drawing.png` — 60 × 30 × 8 plate, two Ø5 through
holes at x = 15 and x = 45.

The contract had moved to 1.15 over four milestones and the engine image still spoke
**1.12**, which is the refusal that ended `P0-RUN-2026-08-09` and the first thing
`P0-RUN-2026-08-09b` had to fix. Third time: the drift is the most reliably repeated
failure this deployment has, and it is repeated because nothing rebuilds the image when
the contract moves.

## What happened

```text
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:latest .
docker run --read-only --network none … describe          cad_ir_version 1.15, 47 capabilities
dotnet test packages/build123d-launcher/tests             35 of 35, nothing skipped
docker compose up -d                                      api healthy, 12 migrations applied
local-worker run                                          registered: supported_cad_ir ["1.15"], codex available

POST /api/v1/auth/register                          201   session + CSRF
POST /api/v1/drawing-jobs        (image/png)        201   WAITING_FOR_LOCAL_WORKER
  → DRAWING_ANALYSIS                                      WAITING_FOR_USER_ANSWERS, 1 question
POST /api/v1/drawing-jobs/{id}/answers              200   15 mm
  → DRAWING_ANALYSIS → build → verify                     MANUAL_REVIEW, 6 artifacts
POST /api/v1/operator/orders/{id}/review            200   approve, v1 → v2
GET  /api/v1/drawing-jobs/{id}                            READY
GET  …/artifacts/STEP, …/artifacts/STL                    22 682 and 51 484 bytes, downloaded as the owner
```

## The part

From the validation report the worker wrote by reopening its own exported files:

| | |
|---|---|
| bounding box | expected [60, 30, 8], **measured [60, 30, 8]** |
| volume | **14085.8407 mm³** |
| through holes | expected 2, mesh-derived genus 2 |
| mesh | 1028 triangles, 0 open edges, 0 inconsistent normals |
| solids | expected 1, measured 1 |
| engine | build123d 0.11.1 / OpenCascade 7.9.3.1.1, **cad_ir_version 1.15** |

```text
60 × 30 × 8 − 2 × π × 2.5² × 8 = 14400 − 314.1593 = 14085.8407
```

Four decimal places against a number nothing in the pipeline computed — and the same
digits as the 1.12 run, which is what a contract change is supposed to leave alone.

## The question it asked

One clarification round, and the question was a real one:

> *What is the distance in mm from the left edge to the left hole centre?*

Answered 15. The document it then wrote carries seven parameters — including
`left_hole_center_offset: 15`, the answer, as a parameter rather than a literal — one
`solid.extrude` with two islands, and three expectations. That is the reading stage
asking for the one dimension the raster does not settle, which is what the clarification
loop is for.

## What the run found

**`probe-codex` could never pass.** It builds a `CodexStageRequest` and never named a
model; `CodexRunner` requires one and answers `CODEX_MODEL_UNSPECIFIED`. So the
operator's first health check — the one the runbook tells them to run *before*
enrolling — failed on every machine it had ever been run on, and failed in a way that
reads like "Codex is broken here" rather than "this command is".

Fixed by asking the router for a route rather than writing a model name into the probe:
`CodexStage.InputTriage`, which is the cheapest rule the routing table has and whose
only question is whether the CLI answers at all. Taking it from the router means the
probe exercises the same decision the pipeline makes and cannot drift from it. Measured
after the fix:

```json
{"status":"CODEX_OK","auth":"local-chatgpt","model":"gpt-5.6-luna",
 "Usage":{"InputTokens":11743,"OutputTokens":46}}
```

**`doctor` reports `"mode":"fake"` as a string literal.** It is not a state — the field
is written that way in `WorkerCore.cs` whatever the worker is configured to do, and this
worker went on to run real Codex and a real container in the same session. Recorded
rather than fixed here: it is a one-line change in a diagnostic, and changing a
diagnostic in the middle of an acceptance run is how a run stops being evidence.

**A stale image is silent until it is asked.** Nothing in CI or in the release routine
rebuilds `cad-ai/cad-worker` when `CAD_IR_VERSION` moves, and the failure it produces —
a worker that registers, heartbeats and then refuses every document at the first line —
looks like a code regression. The runbook already says to rebuild after pulling; what it
cannot do is make anybody.

## Reproducing

```bash
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:latest .
docker run --rm --read-only --network none --tmpfs /tmp cad-ai/cad-worker:latest describe
```

If `cad_ir_version` there disagrees with `cad_ir.canonical.CAD_IR_VERSION`, the image is
stale and nothing is wrong with the code.
