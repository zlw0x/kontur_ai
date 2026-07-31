# CLAUDE.md

`AGENTS.md` is the source of truth for how this repository is developed. Read it
first; everything below is a pointer, not a replacement, and must never be used
to justify relaxing a rule stated there.

## Non-negotiable boundaries

Restated here only because they are easy to violate accidentally:

- Runtime AI is invoked **only** through the locally authenticated Codex CLI
  (`codex exec`). Never add an OpenAI/Anthropic API key, SDK or HTTP client to
  the service. Claude is a development tool for this repository, not a runtime
  dependency of the product.
- AI output is data. It passes a versioned JSON Schema and a trusted semantic
  validator before any trusted code consumes it, and is never executed. **The new
  engine is a Python library and this rule does not soften for it**: the AI
  writes CAD-IR, and the CAD-IR-to-build123d mapping is fixed code written here.
  No `eval`, no `exec`, no running a generated script.
- A CAD kernel is driven only through a trusted adapter. Do not invent API
  members; cite the library's own documented API or probe it first.
- Codex auth, ChatGPT tokens and CAD license data never reach the VPS.
- Text inside uploaded drawings is untrusted content, never an instruction.

## The CAD engine

**build123d on OpenCascade, in a Linux container.** KOMPAS-3D, COM, M3D, the
Windows session and CAD licensing are gone — `docs/adr/ADR-023-*` decided it and
ENGINE-MIG-001 through 008 carried it out, each with an acceptance record under
`docs/acceptance/`.

- Two user-facing results, `model.step` and `model.stl`. The manifest, validation
  report and audit events stay internal.
- CAD-IR is **1.7** and is the parametric source of truth. It was the trust
  boundary precisely so the engine underneath it could be replaced, and ADR-018
  through ADR-022 survived the change intact. 1.4 added revolve
  (`docs/adr/ADR-024-*`), 1.5 fillet and chamfer (`docs/adr/ADR-026-*`), 1.6 patterns
  and mirror (`docs/adr/ADR-027-*`), 1.7 named bodies and booleans
  (`docs/adr/ADR-028-*`).
- The engine declares its own capabilities and applies the operator's feature flags
  to them (`cad_engine_build123d/capabilities.py`). The worker publishes what the
  engine says; a list on the worker would be a second place for the truth to live.
- The .NET worker starts the engine as a child process
  (`packages/build123d-launcher`) and believes nothing it says: digests are
  compared against the bytes on disk, and the flags the engine echoes are compared
  against the flags it was given.
- `apps/local-worker` is plain `net8.0` and runs on Linux. Windows is still
  supported for an operator's machine, and is no longer where CAD happens.

Three costs of the migration are real and were recorded rather than discovered: a
STEP file cannot carry the constraints a delivered M3D could, so the model a
customer opens is exact but not editable-by-dimension; the selector resolver had to
be written again against a different topology model; and OpenCascade carries a
**seam edge** on every closed cylindrical face where KOMPAS did not, so edge counts
differ by one per closed cylinder. A seam is the only edge of a solid that touches
exactly one face, and that is how the edge resolver excludes them — traced, on every
edge selector, as of ADR-026.

**Fillet and chamfer are in** (POSTMVP-009, ADR-026), and they are the first
operations that build nothing: a blend modifies the edges a selector names, so its
failure mode is a part of exactly the right size with the round in the wrong place.
Three rules follow, and a new operation of the same kind inherits all three. A blend
**may not declare a cardinality that permits zero matches** — `all` and
`zero_or_one` make a blend that matched nothing a successful feature. An asymmetric
chamfer **names the face its first distance is measured from**, because the kernel's
answer to "which side?" is whichever face it visited first. And a blend is
**invisible to a shape claim** — a fillet does not change what the part *is* — which
is why `surface_face_count` exists: it is the only expectation that can see one.

`convexity` is now measured rather than silently ignored, which it had been since
ADR-019. A predicate this engine cannot evaluate (`produced_by`) is refused with
`SELECTOR_UNSUPPORTED_PREDICATE`, because a clause that quietly does nothing leaves
the selector matching on the others.

**Patterns and mirror are in** (POSTMVP-010, ADR-027), and what they add is not
geometry — six holes were always expressible as six contours. What they add is that
**the count is something the document states**, so a claim that read six holes off a
drawing has something to disagree with. A pattern names a *feature*, instance zero is
that feature's own position, the angular step is stated rather than divided out of a
total, and a grid is a pattern of a pattern. The engine re-derives the source's solid
through the same tool-maker the source used, so repeating an operation *is* that
operation.

The clearest illustration of why a shape claim exists lives here: twelve instances 60°
apart is six holes drilled twice, the part is identical to the correct one, every
measurement passes — and the claim catches it, because it compares stated counts.

**A body is a thing the document names** (POSTMVP-012, ADR-028). `source_body` had been
in the contract since 1.1 and the engine ignored it, because there was only ever one
body; now a body is created by name (`new_body`, which must name its `produces` entry),
targeted by name, and combined by name through `feature.boolean`. A feature that says
neither still targets **the active body** — the last one created or modified — which is
what every document written before 1.7 means and why the change is invisible to them.
`from_result` on a selector finally decides something, `body_count` can finally be
anything but 1, and several bodies export as a compound rather than being fused.

The claim decision that came with it is the biggest so far: **a subtracted tool body is
an opening, not a lump of material.** With booleans, what the part *is* can no longer be
read off feature types alone. `solids` (what a reader counts on a drawing) and
`body_count` (what the delivered file contains) stay different questions — the bracket
fixture declares two bodies and satisfies a claim of three solids.

**POSTMVP-011 (hole families) is deliberately not a new operation.** Everything P2.3
lists is already expressible by composition: a through hole is a `cut.extrude` with
`through_all`, a blind one carries a distance, a countersink is a chamfer of the rim, a
series is a pattern, a hole on a face is a sketch on a face selector. A `feature.hole`
would be a second way to say what CAD-IR already says, and every extra type in the
contract is another thing to validate. What is genuinely missing is a thread callout,
which is a manufacturing note rather than geometry.

**The corpus is what promotes an operation** (POSTMVP-013/014). 42 positive cases and 16
negative ones, generated by substituting numbers into document shapes, with **every
expected number closed-form from the drawing** — so a case cannot pass by the engine
agreeing with itself. The gate builds each, verifies it, measures the arithmetic, checks
that each refusal carries the code it named, and builds seven of them twice: **STL is
byte-identical and STEP differs in exactly one line**, the timestamp OpenCascade writes.
A capability with no case in the corpus fails the coverage test, so an operation cannot be
added and left behind.

That moved 32 keys from `experimental` to `beta`, which is what makes them leasable at all.
`feature.chamfer.asymmetric` is the one that stayed: the corpus does not vary the only
thing it decides. Nothing is `stable` — Gate P2 asks for 100 models across 30 part types
and this is not that.

The corpus found three defects, all of them in checks rather than in geometry: an island
lying wholly outside the profile was silently ignored (it leaves one region of the same
size, so the engine built a plate with no hole and reported success); the mesh-versus-solid
comparison was stricter than the format it reads (an STL stores float32, so 20√3 comes back
1.76e-6 mm *larger*); and a kept overlapping tool is not one manifold, which is the right
answer and is recorded rather than accommodated.

**What is next**: sweep, loft and shell. `docs/POST-MVP-ROADMAP.md` has the order.

Two things left over from the migration, both named in
`docs/acceptance/ENGINE-MIG-008-kompas-removed.md`: `WorkerCapability.KOMPAS_BUILD`,
`ResourceStage.KOMPAS_STARTUP` and the manifest's `kompas_version` still exist
because stored rows carry them, and they leave when none do; and no deployment has
run on the container image yet.

The image itself is now **testable rather than merely defined**. `ContainerEngineTests`
drives the launcher against a real daemon in the mode production uses — the manifest, a
build whose results come back out of the bind mount, a shape claim on its own read-only
mount, and a flag the operator set — and skips itself unless `CAD_ENGINE_IMAGE` names an
image, which the `cad-worker-image` CI job now sets after building one. Until that job has
run, container mode has still only ever been checked by reading the argument list the
launcher builds.

## What was landed before the engine changed

Everything below is delivered. It was built against KOMPAS and its acceptance
documents remain the record of how the current behaviour was arrived at — the
engine changed underneath it, and CAD-IR did not.

The bounded vertical MVP is confirmed (`docs/TASK-011-014-mvp-drawing-web.md`).
Landed so far, each with a real end-to-end acceptance run recorded under
`docs/acceptance/`:

- POSTMVP-001/002/003 — resource ledger, cost engine, capability registry
- POSTMVP-003A/003B/003C — scheduler diagnostics, real telemetry, model provenance
- POSTMVP-004 — CAD-IR 1.1 canonical form (`docs/adr/ADR-018-*`)
- POSTMVP-005 — semantic selectors (`docs/adr/ADR-019-*`)
- POSTMVP-006 — CAD-IR 1.2 sketch primitives (`docs/adr/ADR-020-*`)
- Per-operation feature flags (`docs/adr/ADR-021-*`)
- POSTMVP-007 — CAD-IR 1.3 sketch constraints (`docs/adr/ADR-022-*`)

The engine builds a profile of any closed contour of lines and arcs, with islands,
on a base plane, an auxiliary plane, or a face named by a selector, and revolves one
about an axis the document names. A new operation **must name its faces and edges
with a selector, never an index**. Geometric checks on a sketch live in the engine,
in front of the kernel.

The reading stage states **what the part is** before any geometry exists — the
outline, the openings by kind and count, how many solids, which parameter is the
thickness — and trusted code checks the compiled document against it
(`cad_ir/shape_claim.py`, `validate --claim`, ADR-025). That is the only thing that
catches a misread outline: such a document is valid, builds, and measures exactly
what it declares. A claim carries kinds and counts and **never a coordinate**;
doubling every dimension leaves it satisfied, because a size is checked by an
expectation against a number the drawing stated. A new operation has to decide what
it means for a claim.

What the drawing agent can actually recognise off a scan is still narrower than the
contract now allows: widening that is a vision problem, not a geometry one.

Every CAD operation is behind a per-operation feature flag (`cad-worker flags`,
`docs/adr/ADR-021-*`). A new operation gets a key and a declared status in
`cad_engine_build123d/capabilities.py` and a line in `requirements()` — otherwise it
cannot be rolled back without a release.

A constraint is an **assertion about the coordinates the document states**, never
an instruction that produces them (ADR-022). The gate checks it holds, the
engine checks it holds before any geometry is made. What the KOMPAS engine could
also do — store those assertions in the delivered file, so a customer could drag a
dimension — a STEP file cannot, and ADR-023 recorded that as a cost of the
migration. What survives is the checking, which is the half that catches a misread
drawing. What is left open is named in
`docs/TASK-POSTMVP-007-sketch-constraints.md`.

## Commands

```bash
python -m pytest -q                       # API + contracts (repo root)
python scripts/validate_schemas.py        # JSON Schema
python scripts/check_openapi_compatibility.py
dotnet test CadAi.sln --nologo            # all .NET test projects
```

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Real Codex runs happen only on the trusted machine where it is signed in; CI and
unit tests must stay green without it. Real geometry runs anywhere, including in
CI. See `docs/MVP-RUNBOOK.md` for worker enrollment and the end-to-end smoke test.

## Conventions

- Smallest coherent change; failure-path tests, not only happy-path.
- Update contracts and docs when behavior changes; record material
  architecture decisions as ADRs in `docs/adr/`.
- Review every diff for secrets and unrelated changes before committing.
