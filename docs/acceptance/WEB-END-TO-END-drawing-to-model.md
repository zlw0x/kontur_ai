# Web end-to-end: a drawing uploaded in a browser becomes a model

**Date:** 2026-07-30 · **Result:** PASS on both paths, after four defects that
only a run through the browser could have found.

Every milestone so far was accepted by driving the adapter or the worker
directly. That proves the geometry and proves nothing about the product: the
page, the API, the queue, the worker and KOMPAS had never all been exercised in
one motion by a person with a drawing and no shell. This run does exactly that,
twice — once straight through, once through the clarification round.

## What was run

The stack on this machine, the trusted Windows box that has KOMPAS v22 and the
authenticated Codex CLI:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
dotnet run --project apps/local-worker -- run
```

The worker enrolled as `DESKTOP-LQGRUAU`. The drawing is the sample the site now
ships, `apps/web/public/sample-drawing.png` — the same 60 x 30 x 8 plate with two
Ø5 through-holes that `scripts/make_acceptance_drawing.py` generates and that the
acceptance runs build. A visitor with no drawing to hand can press **Попробовать
на образце** and get the same thing.

Both orders were created by clicking in the page at `http://localhost:3000/studio`,
not by curl.

### Run one — straight through

```text
order c004d3dd-fa28-451a-97c9-2fd1e0aa7601 · job db66b612-83be-4a4a-b8cc-3d898142d0b9
PENDING -> LEASED -> READY, no questions asked, 49 seconds end to end
```

### Run two — through a clarification round

Codex read the same drawing and this time was not willing to guess one number:

```text
q_left_hole_x / hole_1_center_x
"What is the left hole center's horizontal distance from the plate's left edge (mm)?"
```

Answered `15` in the page — which is what `HOLE_OFFSET_MM` in the generator says.

```text
order cfce2a04-b0f0-47dc-9f7d-7f41016ddcd6
PENDING -> LEASED -> WAITING_FOR_USER_ANSWERS -> PENDING -> LEASED -> READY (round 1)
job 965484d2-8931-4df5-ab42-16f787b47d7d
```

That the same drawing took different paths on two consecutive runs is not a
defect. The model is asked what it can see, and when it is unsure the design says
ask rather than invent — the clarification round exists for exactly this.

## Result

Both runs pass every check identically; the numbers below are run two, the
longer path. The exported bytes differ slightly between the runs because the two
CAD-IR documents place the holes with slightly different coordinates — the
measurements the verifier makes do not.

Every check the independent verifier makes:

| Check | Result |
|---|---|
| `m3d_nonempty` | 58 435 bytes |
| `step_header` | ISO-10303-21 found |
| `stl_structure` | 300 complete triangles |
| `finite_non_degenerate_triangles` | 0 degenerate |
| `closed_manifold_mesh` | 0 boundary or non-manifold edges |
| `solid_body_count` | expected 1, measured 1 |
| `bounding_box` | expected [60, 30, 8], **measured [60, 30, 8]** |
| `through_hole_count` | expected 2, topology-derived genus 2 |

All four artifacts download through the page and through the API:

```text
M3D  58 435 B   application/octet-stream
STEP 13 427 B   model/step
STL  53 743 B   model/stl
VALIDATION_REPORT 1 354 B  application/json
```

## Defects the run found

Four, none of which a unit test would have reached, because each lives in a seam
between two components that unit tests hold apart.

### 1. The prompt and the output schema disagreed about the CAD-IR version

`DrawingPipeline` hard-coded `1.2` in the prompt text while the schema it
generated demanded `1.3`. The model was told to write a version the validator
would refuse. Fixed by interpolating one constant:

```csharp
private const string CadIrVersion = WorkerCapabilities.CadIrVersion;
```

The version now cannot drift, because there is one place it is written.

### 2. Re-enrolling a known machine was rejected

`register` inserted a row unconditionally, so a worker that was rebuilt hit the
unique constraint on its name and the API answered `ENROLLMENT_REJECTED` — which
sends an operator to check their token when the token was never the problem.
Re-enrolment now rotates the credential and keeps the worker's identity, and it
clears what the old worker had published: slots, capabilities, supported CAD-IR
versions, manifest, last-seen. Eleven tests in
`apps/api/tests/test_worker_reenrollment.py`, over both the in-memory and the SQL
implementation.

It grants nothing new. The enrollment token already authorises registering a
worker, so anyone holding it could occupy the name anyway.

### 3. `public/` never reached the container

A Next.js standalone build does not carry `public/` with it. The sample drawing
worked in development and was a 404 in Docker — the first thing a visitor would
press, broken in the only environment that matters. One line in the Dockerfile.

### 4. The page stated dimensions it had not measured

The worst of the four, because it was quiet. The summary card read
**80 × 40 × 12 мм** next to a real 60 x 30 x 8 plate, and the chips over the 3D
view said the same. Those numbers came from the layout: a fallback for a
demonstration shape shown before any build, left in place after one.

A number displayed next to a model has to come from that model. The page now
reads the bounding box out of the validation report the worker wrote from the
exported file, and labels it **Габариты, измерено**. Before a model exists it
says so — `будут известны после построения` — and the dimension chips are absent
rather than invented. A report the page cannot parse produces no dimensions, not
a guess.

This is the same rule the rest of the service already follows on the inside: the
adapter re-reads geometry after the solver rather than trusting it moved nothing
(ADR-022), and the verifier measures the exported mesh rather than trusting the
build. The web page was the one surface still exempt from it.

## What this does not prove

- **One drawing.** The vision half still reads only a rectangle with round holes.
  Everything POSTMVP-006 and 007 added — arbitrary contours, islands, auxiliary
  planes, selectors, constraints — reaches the adapter through the manual API,
  never from a scan. Widening that is a vision problem, not a geometry one.
- **One machine.** Web, API, worker and KOMPAS are all local here. Nothing in
  this run exercises the VPS boundary, and by design nothing should: Codex auth
  and KOMPAS licensing never leave this box.
- **Nothing about failure.** Both runs succeeded. What a visitor sees when the
  build fails is untested from the browser.
