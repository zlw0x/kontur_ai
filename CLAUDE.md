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
- CAD-IR is **1.11** and is the parametric source of truth. It was the trust
  boundary precisely so the engine underneath it could be replaced, and ADR-018
  through ADR-022 survived the change intact. 1.4 added revolve
  (`docs/adr/ADR-024-*`), 1.5 fillet and chamfer (`docs/adr/ADR-026-*`), 1.6 patterns
  and mirror (`docs/adr/ADR-027-*`), 1.7 named bodies and booleans
  (`docs/adr/ADR-028-*`), 1.8 shell (`docs/adr/ADR-030-*`), 1.9 sweep and loft
  (`docs/adr/ADR-031-*`), 1.10 the extrusion modes (`docs/adr/ADR-033-*`), 1.11
  scalar arithmetic (`docs/adr/ADR-034-*`).
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

**The cap on the cycle is not the engine** (POSTMVP-016, ADR-029). The engine declares 33
capabilities; the drawing cycle could reach two of them. Three different walls hold the
rest back and they are worth telling apart: the **dialect** (Codex structured output has no
optional properties, so an operation whose input is honestly optional cannot be offered),
the **claim** (an operation the reading stage cannot state is an operation nothing checks),
and **vision** (whether the agent can see it on a scan — the only one no code here settles).

The profile now offers what the claim can already check: a blind cut, a datum plane and a
boss on it, a linear pattern and a circular one. None of the geometry is new — the corpus
already builds all of it — what is new is that the cycle may ask. A blind cut is **its own
branch** rather than an optional depth, because the contract refuses a cut that states both
`through_all` and a distance and the dialect cannot make one optional.

With it came `OpeningClaim.through`, because until now every opening the cycle could produce
went through, so a depth could not be got wrong. A misread depth is otherwise a document
that is valid, builds, and measures exactly what it declares — including the
`through_hole_count` it wrote to match. **Nothing is not false**: a reader that could not
settle the depth says nothing, and a claim that says nothing agrees with either.

A contract is not a run. Whether the model emits a pattern when it sees a bolt circle needs
real Codex on the trusted machine; the six runs that would close it are listed in
`docs/acceptance/POSTMVP-016-*.md`.

**A shell is how much of the part is there** (POSTMVP-017, ADR-030), which is a different
question from every operation before it. Hollow a 100 × 60 × 40 enclosure with a 3 mm wall
and it agrees with the solid block on the outline, the openings, the solid count, the
bounding box and the hole count — and differs by four times the material. That table is
the whole ADR.

Two measurements decided the contract and are kept as tests. `offset` is **two operations
wearing one name**: with a face open it hollows (52 188 mm³, outer size unchanged), with
nothing open it *shrinks the solid* (172 584 mm³ = 94 × 54 × 34). So a shell may not declare
a cardinality that permits zero matches — the blend rule from ADR-026, with a sharper
reason. And a wall the part has no room for **does not fail**: 30 mm inward returns the
original solid, whole, with no error, so the engine compares the volume before and after
and refuses with `SHELL_NO_CAVITY`. A pre-check could not do it — 25 mm walls are fine with
the top open and not with it closed, and only the kernel knows which.

The claim gains one word, `wall`: the id of the parameter holding the wall thickness. It is
the first thing a claim says about how much of the part is there rather than what shape it
is, and it stays inside ADR-025's rule — a name, never a number. Silence is still not a
claim. **The cycle cannot ask for a shell yet and that ordering is the point**: a face
selector is behind ADR-029's dialect wall, so the claim's word for a hollow part arrives
first and the output profile follows when the dialect allows.

**Sweep and loft are one question asked twice** (POSTMVP-018, ADR-031): given a profile,
what carries it — a path, or the next profile along. What makes them different from every
operation before is that a wrong document does not fail loudly. Five things were measured
and all five build: a path 30 mm from the profile builds the part **at the profile** (the
kernel ignores the path's position); a 45° path sweeps the profile's *projection*, so a
Ø16 tube comes back with 1/√2 of the section drawn; a bend tighter than the profile passes
through itself, reports `is_valid`, and matches Pappus exactly — only the mesh knows, as 69
open edges; two loft sections in one plane give a closed solid of **volume 0.0**; and a
square lofted into a circle gives a plausible solid whose correspondence the kernel chose
and never stated.

So a path is **stated from the profile** (it starts at its plane's origin, because there is
no absolute position the kernel would honour), is open, is tangent-continuous — a corner is
a bend radius the drawing did not give — and crosses the profile at a right angle. A bend
is checked against the profile's reach **on the side it turns towards**, which is exact and
not a circumradius: a profile 40 wide sitting 15 mm off the path may bend one way and not
the other.

A loft's sections are **the same kind of contour with the same number of vertices**, which
is Gate P4's "ambiguous section correspondence is rejected" from the other end. It also
means the claim needs nothing new: `profile` is the kind every section is. Round-to-square
comes back when the document can state which vertex meets which.

Both are checkable because both have closed-form arithmetic — **Pappus** for a sweep (exact
round the bends, because the centroid rides the path) and the **prismatoid rule** for a
loft. Neither is reachable from the drawing cycle, and that is ADR-029's claim and vision
walls rather than its dialect one.

**The dialect wall was lower than it looked** (POSTMVP-019, ADR-032). ADR-029 read rule 4
— every object lists all its properties as required — as "a selector cannot be offered,
because its predicates are individually optional". That is true of offering the predicate
*vocabulary*. Rule 4 governs the properties a schema **declares**, and a `where` that
declares three predicates and requires all three is dialect-legal *and* canonically valid,
because the ones it leaves out are optional in the contract. Three operations sat behind a
misreading for a milestone.

So the profile now offers **selections** rather than selectors: the upright convex corners
of the outline, the circular rims topmost along Z, the planar +Z face. Every predicate a
constant, `from_result` the constant `body.main`, nothing to choose but a count. **The
model composes nothing** — that is the decision: a selection is written here against the
topology this engine builds and is exercised by the corpus, where a composed one would be
a selector nobody has resolved against a real part.

Four operations follow — a corner fillet, a corner chamfer, a bore chamfer and a shell —
and the claim grew with them, because ADR-029's rule cuts both ways. `ShapeClaim.blends`
is kind and count: a plate with square corners where the drawing shows R5 agrees on the
outline, the openings, the solid count and the bounding box, and `surface_face_count` is
written by the same stage that chose the blend. A count, never a radius. The count is
comparable only because the profile emits `exactly_n` — which is also the only cardinality
ADR-026 allows. And `wall_parameter` finally reaches the reading stage, because the cycle
can now build the shell it describes.

The cycle reaches **ten** of the engine's 39 capabilities. Everything the claim can check
is on offer, and **vision is now the only wall that matters** — revolve, sweep, loft and
the booleans wait on whether an agent can read them off a scan, which no code here
settles.

**A part is now checked against itself** (POSTMVP-020, ADR-033). Every build delivers a
STEP and an STL written by two different exporters, and the genus of the solid — how many
handles it has — can be computed from either: Euler–Poincaré over the B-rep, Euler over
the triangles. Neither number comes from the document, so this check needs nothing to have
been stated. It runs on every build.

The `L` term is why it works and why an earlier attempt gave up: the naive `V − E + F =
2 − 2G` reads 0 for a plate that plainly has a hole, because a B-rep counts a full circle
as one edge with one vertex. Counting *loops* puts it right. What it catches is the
self-intersecting sweep — the STEP says a tidy genus-0 solid, the STL says genus −45 with
69 open edges, and neither half is wrong-looking on its own.

**Two ways an extrusion travels** came with it (POSTMVP-021). `both_directions` states the
**total**, split half each way, like a revolve's since 1.4. `taper_deg` narrows the
extrusion along `direction` — positive narrows, negative widens, and that is the only rule:
"draft" means opposite things on a boss and in a cavity, and a sign the document cannot see
is a sign somebody else chose. Both have closed-form arithmetic (the prismatoid rule for a
taper, exact to six decimal places), and neither is offered to the drawing cycle, because
neither is something a drawing states in words the reading stage has.

**The claim has since gained the word for a draft** (ADR-033's amendment,
`docs/acceptance/POSTMVP-021-draft-in-the-claim.md`). `ShapeClaim.draft` names the parameter
holding the angle, and it is the worst-hidden omission found so far: a *narrowing* draft
keeps the sketch as the widest section, so a document that dropped it agrees with the
drawing on the outline, the openings, the solid count **and the bounding box**, and holds a
third less material — 20 × 20 × 10 comes back 2 720.752 mm³ against 4 000. The claim says
the name and not the direction, measured rather than assumed: a positive taper narrows away
from the sketch plane whichever way the extrusion travels, so `direction` cannot flip it and
a `Scalar` with no arithmetic cannot negate it. A named angle holding **0°** is refused, as
the one place the id and the value can be made to disagree. The offer is still held back —
now by vision rather than by vocabulary.

**The kernel's failure mode is a plausible answer**, and that is now three findings of one
shape: a shell with no room returns the original solid, a sweep round too tight a bend
returns a self-intersecting one, a draft past the closing point returns a stump 10 mm tall
where 40 was asked for. Each reports itself valid. So **every operation that can be
over-driven gets a post-check comparing the result against what was asked** —
`SHELL_NO_CAVITY`, `SWEEP_BEND_TIGHTER_THAN_PROFILE`, `EXTRUDE_DRAFT_TOO_STEEP`.

**The nine runs are done** (`POSTMVP-016-run-1-*`, `POSTMVP-016-runs-2-6-*`,
`POSTMVP-019-runs-7-9-*`), on the machine Codex is signed in on. Eight parts built,
every number closed-form from the drawing and matching to four decimal places. The
sentence "the cycle reaches ten capabilities" stopped being about contracts and became
about behaviour, with three corrections.

**The pattern is offered and not taken.** A drawing saying "6 × Ø6 on a Ø60 PCD" comes
back as six islands in one sketch — perfect arithmetic, right part, no `pattern.circular`.
Vision is not the wall: the count was read correctly and the claim says 6. Composing six
contours is simply available and simpler. That is a **fourth kind of wall** beside
ADR-029's dialect, claim and vision — an operation can be offered, readable and
*unnecessary* — and it is the softest, because nothing makes the model prefer the form
that carries the count.

**The two ways of not knowing are two mechanisms.** A missing *number* produces a
question, so optional `through` is not what answers it — the clarification loop is. A
missing *view* is what nullable `through` is for, and there the claim omits the key
entirely and agrees with whatever gets built. Silence is the fallback, and it fires only
when asking cannot help.

**A parameter can state a dimension it does not drive**, and the copy with the best
provenance is the one nothing checks. A flange document carried `outer_diameter: 80` from
the reading stage — cited to the Ø80 callout — and drew a literal `radius: 40`, then
restated 80 as a literal in its expectation. The rule that would refuse it
(`PARAMETER_DRIVES_NOTHING`) was written, measured and **reverted**: a canonical `Scalar`
is `float | ParameterRef` with no arithmetic, so a diameter cannot drive a radius and one
parameter cannot drive both sides of a symmetric outline. Version 0.1.0 had expressions
and the canonical form traded them away; this is the bill.

**The unblocking is designed and half built** (`docs/TASK-POSTMVP-scalar-arithmetic.md`).
Two of the three things it was thought to need are already in the tree: `cad_ir.expression`
is a recursive-descent parser with a fixed grammar, bounded input and result, three
whitelisted functions and a test for `__import__('os').system(...)` — so the question of how
much expression language is safe was answered in 0.1.0 and the answer is still shipped. What
is blocked is only the **canonical representation**, and for a nameable reason: `"d/2"` and
`"d / 2"` are the same part with two byte-stable hashes, which is what ADR-018 traded
expressions away to prevent. An AST is no better — `a + b` and `b + a` are two hashes.

So the form is **one node, not an expression**: `{"parameter": "outer_diameter", "times":
0.5}`. No parser, no recursion, no precedence, one spelling per part — and it covers every
row of the measured table (a diameter driving a radius ×3, and one parameter driving both
sides of a symmetric outline). Never 1, which is a plain reference; never 0, which drives
nothing; bounded after the multiplication, because 900 000 × 100 is two legal numbers.
`ScaledParameterRef` and its resolver are built and tested (22 tests, including the two
refusals `Parameters` had carried untested since ENGINE-MIG-002); **`Scalar` is untouched**,
so nothing can reach it yet, and one test asserts that on purpose. Sums and trigonometry are
refused for stated reasons — the sum belongs in an expectation, and a bolt circle belongs in
`pattern.circular`, which is already there and already not being taken.

One defect outside the geometry was found by the runs and fixed: **the Codex child
inherited the worker's own stdin**, so a pipe nobody closed made a stage fail with no
events at all — indistinguishable from the model failing — and any bytes that did arrive
would have been appended to the prompt. Redirected and closed at start.

**What is next**: rib (P3.2), then the rest of Gate P4. `docs/POST-MVP-ROADMAP.md` has the
order.

**Rib is designed and not built** (`docs/TASK-POSTMVP-P3-2-up-to-a-face.md`), and the
investigation it was blocked on ends by dropping `extrude(until=…)` altogether. Sixteen
cases: two are correct, three raise, and three succeed wrongly — a profile inside the
material spikes 62.45 mm into open space and reports one valid solid, a cut to the next
surface can remove nothing. `until` is also the first operation that would state **no
number**, so the post-check pattern that caught the last three defects has nothing to
compare against. So an up-to-face extrusion **names the terminating face with a selector**
(ADR-019's rule, again) and trusted code computes the reach — `((p − o)·n)/(d·n)`, which
reproduces the kernel's own answer to 0.000e+00 where `until=` works, gives the corpus a
closed form the kernel used to keep to itself, and turns each failure into a refusal or into
two solids that `body_count` already sees. Building it is a CAD-IR version.

**The migration's last leftovers are gone.** `WorkerCapability.KOMPAS_BUILD`,
`ResourceStage.KOMPAS_STARTUP`, the manifest's `kompas_version` and the `M3D`
artifact type stayed parseable because stored rows carried them — deleting a name
rows still hold turns a rename into an outage. Migration 0006 rewrote the rows
first and the names went second, which is the order that matters. Nothing in the
vocabulary names which program does the work.

Two things were kept on purpose. `_COARSE_ALIASES` is now empty and still there:
it is the seam a rename goes through, and `canonical_capabilities` being the only
way anything compares capabilities is what made the last one a one-line change.
And every comment explaining *why* something is the way it is — a seam edge
OpenCascade carries and KOMPAS did not, constraints a STEP cannot hold — stays.
Those are the record of how the current behaviour was arrived at, not leftovers.
Artifact rows of type `M3D` are also left alone: such a row is a file really
delivered to a customer, and rewriting its type would make the record claim a
STEP was delivered when one was not.

The image is no longer merely defined: it has been **built and run on a real daemon**
(`docs/acceptance/ENGINE-MIG-DEPLOY-*.md`) — `describe` under `--read-only --network none`,
a real part through a bind mount, and the launcher's four container tests green on the first
attempt, 35 of 35 with nothing skipped once `CAD_ENGINE_PYTHON` gave the process runtime an
interpreter too. `ContainerEngineTests` still skips itself unless `CAD_ENGINE_IMAGE` names an
image, so a sandbox that cannot reach the Debian package hosts reports four skips, and that
is expected rather than a regression.

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
