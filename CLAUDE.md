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
- CAD-IR is **1.15** and is the parametric source of truth. It was the trust
  boundary precisely so the engine underneath it could be replaced, and ADR-018
  through ADR-022 survived the change intact. 1.4 added revolve
  (`docs/adr/ADR-024-*`), 1.5 fillet and chamfer (`docs/adr/ADR-026-*`), 1.6 patterns
  and mirror (`docs/adr/ADR-027-*`), 1.7 named bodies and booleans
  (`docs/adr/ADR-028-*`), 1.8 shell (`docs/adr/ADR-030-*`), 1.9 sweep and loft
  (`docs/adr/ADR-031-*`), 1.10 the extrusion modes (`docs/adr/ADR-033-*`), 1.11
  scalar arithmetic (`docs/adr/ADR-034-*`), 1.12 draft (`docs/adr/ADR-035-*`), 1.13 an extrusion up to a named face
(`docs/adr/ADR-039-*`), 1.14 a helical sweep path (`docs/adr/ADR-040-*`), 1.15 a path
that leaves its plane (`docs/adr/ADR-041-*`).
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
negative ones when it was built, **65 and 42 as of CAD-IR 1.15** — every version since
has added its own, which is what the coverage test is for. Generated by substituting
numbers into document shapes, with **every
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

**CAD-IR 1.11 paid it** (ADR-034). `ScalarQuotient` and `ScalarNegation` cover both rows of
the measured table — a diameter driving a radius, and one parameter driving both sides of a
symmetric outline — and `PARAMETER_DRIVES_NOTHING` shipped with them, because arithmetic
without the rule makes nothing use it. Structured nodes rather than the `{"expr": "d / 2"}`
0.1.0 had: `"d/2"` and `"d / 2"` are one part with two hashes, which is what ADR-018 traded
expressions away to prevent. Sums are refused for a stated reason — a difference of two
dimensions is a relationship nobody drew unless the drawing draws it, and that argument is
the one an up-to-face extrusion has to answer.

The parser 0.1.0 used is still in the tree (`cad_ir.expression`: a fixed grammar, bounded
input and result, three whitelisted functions and a test for `__import__('os').system(...)`),
reachable only from the 0.1.0 validator nothing calls. It is worth knowing it exists: the
question of how much expression language is safe was answered then, and what was actually
blocked all along was the canonical representation.

**One value, one spelling** (ADR-034's amendment). The two scalar nodes were written the
general way — each taking a whole `Scalar` — which admitted four spellings of −p/2 and two
of +p, so the byte-stable hash ADR-018 exists for did not identify a part. The fix adds
nothing: a quotient divides a **reference** by a positive constant that is not 1, and a
negation wraps a reference or a quotient. Three things fell out of it — the explicit depth
bound became unnecessary (the grammar bounds it at two), `negates` became one line, and the
output profile turned out to be **offering documents the validator would refuse**, which is
the worst kind of rejection because the repair loop has nothing to read. A test now holds
the profile and the contract to the same set.

**A failure can be worth neither repairing nor retrying** (POSTMVP-025). `BuildFeedback`
split failures in two — repairable by rewriting the document, or about the machine — and the
cases are three: a quota that returns on a stated date is not repairable *and* not worth
another attempt, so a machine failure on attempt 1 of 3 went quietly back to the queue.
`WillBeTheSameNextTime` is the third answer, and the distinction is that **a retry cannot
observe a change**: a container that would not start may start, and this service has one
locally authenticated CLI on one machine, so a quota has no second account to find.

The run that asked for it found the larger half. `RunClaimedJobAsync` caught
`WorkerException`, and a Codex failure raises `CodexRunnerException` — same shape, neither
deriving from the other — so it went past the reporting branch into the claim loop's blanket
backoff. **No report on any attempt, for every Codex failure there is.** That is why the job
stayed leased with an empty `output/` and the page said "waiting". `ClaimLoop.Typed` names a
failure from either type; anything without a code still falls through, because an exception
this worker did not name is a bug in the worker rather than a verdict about the drawing.

One correction worth keeping: `CODEX_BUDGET_EXHAUSTED` is the worker's **own per-order run
counter** and never comes from the CLI. An exhausted account quota arrives as
`CODEX_CAPACITY_LIMIT`, because `MapExit` reads "limit" out of the message text. Classifying
only the first would have left the measured failure retrying exactly as before.

One defect outside the geometry was found by the runs and fixed: **the Codex child
inherited the worker's own stdin**, so a pipe nobody closed made a stage fail with no
events at all — indistinguishable from the model failing — and any bytes that did arrive
would have been appended to the prompt. Redirected and closed at start.

**Nothing is left leased forever** (P0-3 of the production audit). Two states a job
could reach and never leave. `claim` selects `attempt < max_attempts`, so a worker that
dies on its **last** attempt leaves the row unclaimable *and* un-failed — measured, and
the two protocol implementations even spell it differently (the in-memory claim resets
the lease to PENDING first, the SQL one leaves it LEASED), which is one disease with two
names. And a quota that returns on a date is neither failed nor waiting.

So `JobStatus.PAUSED` with a `retry_after`, and a **reaper** on a timer rather than on a
claim — the case it exists for is the one where *nothing is claiming*. It requeues a
lapsed lease with attempts left, fails one with none (`LEASE_LOST`, a code of its own,
because the worker said nothing and that is what happened), and returns a pause when its
time comes.

**A pause hands the attempt back**, which a test caught by asserting the opposite: nothing
was attempted, and spending one means a four-day outage burns every job's three tries in
the first hour and then fails them all with a code that lies twice. The worker sends a
*duration* rather than the date the CLI prints — parsing prose is the weakness `MapExit`
already has — so a quota that is still out simply pauses again, hourly, for free.

The page stops lying and stops polling: a pause reads as a pause with the time it will be
retried, and the three-second poll now ends on READY and FAILED instead of running until
the tab closes.

**The raw upload never crosses into the pipeline** (P0-2 of the production audit,
`docs/SECURE-INPUT-ADDENDUM.md`). What stood in the approved requirement's place was
`payload = await request.body()`: the whole upload in memory, eight magic bytes checked, and
the file a stranger sent written into the directory the worker downloads from. Three stages
now, each doing what the next cannot — a **quarantine** that counts and hashes as it reads and
*stops* at the limit rather than measuring what already happened, a **sanitizer in a child
process** with no environment of ours and `RLIMIT_AS`/`RLIMIT_CPU` (the wall clock stays on
our side, because a child that has stopped responding cannot enforce its own timeout), and a
page **rebuilt from pixels** so nothing the decoder attached travels. Alpha is composited onto
white rather than dropped — dropping it keeps the RGB the uploader believed was invisible. The
answer is one JSON line, measured against the bytes on disk before it is believed, the way the
CAD launcher treats the engine. Not done and not implied: the container image itself (the argv
is asserted, the process mode is what runs), WEBP, and the PDF contour.

**An order is a row, and there is one vocabulary for it** (P0-4, ADR-036, migration 0008).
Jobs, artifacts and the ledger had been in PostgreSQL since 0001; the order — the thing the
customer has — was two dictionaries in `app.main`, so a restart lost every order in flight and
a second API process never saw the first one's. Reading the code found two things worse than
that. The stored status was **written and never read**, so persisting it unchanged would have
made a lie durable. And the API answered in **two vocabularies at once** — `READY` and
`WAITING_FOR_USER_ANSWERS` from `OrderStatus`, `PENDING` and `LEASED` from `JobStatus` —
depending on which branch fired.

So the row holds what only the order knows and the job keeps progress, because copying it
would be a second place for one truth to live. `pipeline_status` is the single translation:
`LEASED` says a worker holds the job and says nothing about what it is doing, and the job's
**type** is the only thing that does. `PAUSED` joins `OrderStatus` as **derived-only** —
nothing transitions into or out of it, an empty transition set here means "not stored" rather
than "terminal". And a **decision outranks an observation**: cancelling does not reach into
the worker, so the build finishes and the order is still cancelled. That is what makes the
stored status stop being write-only, and it is the column the moderation queue will write.
Measured on a real PostgreSQL: one process creates and cancels an order, a second process
reads it back cancelled — where before it would have found the order through the tracking
file and reported `PENDING`.

Regenerating the published contract for one new enum value found that `schemas/openapi.v1.json`
had been **stale since 0007**. Neither existing check could see it: one validates the document's
shape, the other only that nothing v1 promised has disappeared, and a field that never arrived
fails neither. `generate_openapi.py --check` now runs in CI.

**An order belongs to somebody** (P0-1, ADR-037, migration 0009). The only
authentication the service had was `authenticated_manual_api` — one static token shared
by everyone who held it — and `orders` had no column saying whose an order was. Anybody
with the token could read and cancel anybody else's drawing. It is the one audit item
that directly blocks letting strangers in, and it could not be fixed in the handlers:
thirty checks are thirty chances to forget one, and no check can consult a column that
does not exist.

So `users`, `sessions`, and `orders.owner_id` — **nullable, and staying nullable**. Every
order created before 0009 has no owner and there is nothing to fill it with; a backfill
would have to invent an answer, and handing those orders to whoever asks first is not a
guess but a giveaway. They are visible to an operator and to nobody else, decided by
`may_see_order` in one place rather than in every handler.

Three decisions carry the rest. **404 and not 403** — a 403 answers "does this order
exist?" for anybody guessing an id, and the existence of an order is itself information
about somebody's business; an order you do not own and an id that was never issued return
the same status and the same body. **A session is a row**, because revoking has to take
effect on the next request rather than at expiry, and nothing can recall a self-contained
signed token without keeping a list — at which point the token has bought nothing.
And **`MANUAL_API_TOKEN` becomes an operator, not a customer**: it authenticates as staff
with no `user_id`, so it can look at everything the way an operator can and owns nothing,
which is what keeps "a diagnostic operator key and never a client authorization" true
while the client paths move onto sessions.

CSRF is **bound to the session** rather than compared cookie-to-header: the naive double
submit loses to anything that can write a cookie on a sibling subdomain, since an attacker
who sets both halves passes a check that only compares them to each other. It is checked
for cookie-borne writes only — a credential that has to be typed into a header cannot be
sent by accident.

bcrypt and not Argon2id, recorded rather than hidden: `argon2-cffi` is not in the tree and
`bcrypt` is, and the difference that matters is between *a hash* and *a hash that costs
something*. Two details are not optional — the 72-byte pre-hash (bcrypt ignores everything
past 72, so two passphrases sharing a prefix would be one password and both users could
still sign in) and the **decoy hash**, because saying the same words in a microsecond for
an unknown address and a quarter of a second for a real one is an account-enumeration
oracle bolted to a form that was careful about its wording.

Two defects older than the task came out of it. `orders.owner_id REFERENCES users(id)` was
in the migration and not in the ORM, and nothing could see it: the tests build their schema
with `create_all`, and SQLite does not enforce foreign keys, so an order owned by a
nonexistent account inserted cleanly everywhere and would have been refused in production.
Real PostgreSQL found it; `test_migration_parity` now compares **constraints and not only
columns**, which is what would have found it without a database.

**Neither environment sees the project whole**, and that is now three findings of one
shape. The cloud cannot collect `packages/build123d-adapter` or read a drawing; this
machine could not run the sanitizer at all (`import resource` is POSIX, so the child died
with an empty stdout and every upload came back 503) and does not collect the adapter
either unless the run uses `.venv-cad`, where build123d actually is. A summary line that
does not say what it left out is not a result. The sanitizer's answer to it is the pattern
worth copying: the child **reports which ceilings it got**, in every answer including its
refusals, and this side asks twice — the platform before the file is handed over, the
process that ran after it answers — with the unconfined mode allowed only in `local`.

**No part reaches a customer without somebody having looked at it** (P0-5, ADR-038,
migration 0010). `automatic_acceptance` was an idea and never a setting: in practice it
was always on, and `pipeline_status` turned "the job delivered a STEP and an STL" into
`READY` with no person between a stranger's upload and the file they download. The
reason that is not acceptable is specific — the model can write a document that is
canonically valid, builds a closed manifold and measures exactly what it declares, and
is **not the part on the drawing**. The claim catches a great deal of that and not all
of it, and the difference is what an operator is for.

The hold happens where `has_model` is already decided, and is **stored** rather than
derived — which is the decision the rest follows from. A derived `MANUAL_REVIEW` would
make the operator's page a scan of every order looking for the ones whose artifacts
happen to constitute a model; a stored one makes it a query on the index 0008 already
created. *Build a queue, not a state.*

**`READY` and `FAILED` had to become decided statuses**, and that is the consequence
nobody would have predicted. Approving stores `READY` and happened to read correctly
anyway, because the pipeline agrees. A **rejection** has no such luck: the files the
operator rejected are still in the artifact store, so the pipeline still sees a model,
so a rejected order would have told the customer their part was ready — the one that
had just been refused.

A decision and its audit row are **one transaction**, because an order that became
`READY` with no row saying who approved it is indistinguishable from one the pipeline
released by itself. A table and not a log: a log rotates, is not queryable, and cannot
be joined to the order it is about.

And `request_changes` **carries the operator's note or does nothing** — the same
inputs through the same reading stage produce the same document, which is a button
that appears to work. The note travels as a job input, disables round reuse (reuse
exists to skip a second vision call, and a note says the previous *reading* was
wrong), and is the one piece of trusted free text in this pipeline: a signed-in member
of staff who has seen the delivered part is not the drawing's own words, which stay
untrusted data forever. The prompt says which is which, and says the drawing wins
where the two disagree.

**A job that needs the model is not handed to a worker that cannot reach it** (rest of
P0-3, migration 0011). `WorkerCapabilityManifest` carried `codex_cli_version` — which
version is *installed* — and nothing that says whether it answers. The measured cost of
that gap: the account's quota ran out until a stated date, and orders went on being
handed to workers that returned `CODEX_CAPACITY_LIMIT` the moment they tried. Three
leases and three failures per order, every one predictable from the first, and the page
said "no worker has capacity" — true, and not the reason. **A status page that names the
wrong cause sends somebody to check the wrong thing.**

The worker now reports what it *last saw* of its own CLI, and the gate withholds only
jobs that need the model — `AI_DRAWING`, read off the capability a job already declares,
so there is no second list. `BUILD_CAD` still flows, because withholding geometry during
a quota outage turns one stopped stage into a stopped service.

Three decisions kept it from being worse than the problem. **Silence is availability** —
a worker that cannot say is not refused, the rule `engine` already follows, and it is
what makes this gate incapable of withholding work from anybody who has not said they
cannot do it. **The clock is on the API's side**: a pause whose `retry_after` has passed
is availability, so a fleet that went quiet during an outage does not stay blocked until
every worker sends a second message. And the worker's state **starts at available rather
than unknown**, which is a deadlock fix rather than optimism: only a successful run
clears an `unavailable`, so a worker that started silent would leave a stored refusal
behind with nothing able to contradict it — a machine somebody has just fixed, still
refused.

Two shapes of "cannot", and the split is the interesting part. A quota **comes back on a
date** and the worker says which; a CLI that is not installed or not signed in **comes
back when a person acts**, so it carries no horizon and blocks until somebody does. A
date on that would be a promise nobody made. `CODEX_TIMEOUT` is deliberately in neither
set: a slow run is a slow run, and calling it an unreachable CLI would stop the fleet
after one long drawing — a rule that can lock itself is worse than the problem it was
written for.

**The first run of the whole perimeter found five defects and none of them was in
geometry** (`docs/acceptance/P0-RUN-2026-08-09-*`). An account created from nothing, an
order that belongs to it, through the compose deployment rather than the test suite.

Four were invisible to 1 100 green tests because each lives where the tests do not go.
**The API did not start at all**: the Dockerfile chowned `/data/artifacts` and quarantine
went beside it at `/data/quarantine`, so the container crashed on import — and a
Dockerfile is not something the suite runs. **The sanitizer was never in the image**:
`packages/image-sanitizer` and Pillow were not copied, so the secure-input path could not
have worked in any deployment, and `_sanitizer_path()` counted four parents up, which is
right in a checkout and an `IndexError` at `/app/app/input/sanitizer.py`.

**Three attempts, no report on any of them — again.** `ClaimLoop.Typed` named
`WorkerException` and `CodexRunnerException`; the third type carrying a code is
`CadAdapterException`, which is what a refused document arrives as once the compile
repairs are spent. It walked past the reporting filter into the blanket backoff and the
page ended on `LEASE_LOST`. The same defect as the `CodexRunnerException` one, one type
later — so the test now **enumerates** the types rather than exampling one, because one
example per type is what let the second through. Measured after the fix: attempt 1,
`CAD_IR_INVALID`, with the message.

And that message was the fifth: **the worker offered a version its engine does not
speak.** `supported_cad_ir` — what the scheduler checks before leasing — was this worker
build's constant, 1.12, while the manifest beside it carried the engine's answer, 1.11,
and nothing compared them. A stale image was leased a job it would refuse at the first
line, after paying for a vision call and a compilation. It reads the engine's number
now, for the launcher's reason: *what a component is beats what something upstream
believes about it.*

Every one of the five sits in a seam — image, process, exception type, or a number copied
from the wrong side of a boundary — and a seam is what a suite that imports its subject
cannot see.

**The cycle closed, on a current engine** (`docs/acceptance/P0-RUN-2026-08-09b-*`). The
image was rebuilt against CAD-IR 1.12 and everything the perimeter gained ran in one
sequence: a stranger's account, an order that belongs to it, a sanitized page, a read
that needed no clarification round, a build, a verification, the moderation queue, and
an operator's approval. Bounding box [60, 30, 8], genus 2, **14085.8407 mm³** against a
closed form of 60·30·8 − 2π·2.5²·8 = 14085.8407 — four decimal places against a number
nothing in the pipeline computed.

Rebuilding the image made `ContainerEngineTests` run for the first time in a while, and
three of its four failed at once: `JobWith` had been left building a fixture path with no
version suffix and no `.json`, so every call raised `FileNotFoundException`. **A skip in
the summary line looks exactly like a pass** — the third time that sentence is the
explanation, and the first time the tests were in a position to say otherwise. Fixed
from `CadIr.FileSuffix`, and then 35 of 35 with nothing skipped, which is the launcher's
first clean whole-suite run.

**What one account may ask of a service with one worker** (P1-7, migration 0012). Three
orders in flight, twenty a day, ten wrong passwords and then fifteen minutes. What it is
*not* was the decision: **no new table** — an order already records who owns it and when,
and an upload *is* an order, so the daily count is the upload rate limit with nothing
written per request — and **no per-IP limiting**, which belongs to the reverse proxy and
would be theatre in an application that sees whatever `X-Forwarded-For` it is handed.

The two refusals differ on purpose. A quota answers **429 with `Retry-After`**, because
the caller is authenticated and there is nothing left to disclose. A sign-in answers the
same **401** it always did: a 429 there would announce that the address has an account,
which is the one thing that endpoint's careful wording exists to avoid. The lockout is
therefore inside the service rather than in a middleware that answers by status code, and
it resets on the first success rather than on a timer.

**A hundred labelled orders** (POSTMVP-027,
`docs/acceptance/POSTMVP-027-one-hundred-labelled-orders.md`). Everything before it was
about the service not breaking; this is about whether it works, and there was no other
way to find out. Four families, every expected number closed-form from the sheet, three
hours of real Codex on the trusted machine.

**91 of 100 delivered, 89 of 91 correct, 2 wrong with nothing said.** `plate` 22/22,
`pocket` 23/23, `flange` 25/25 after a fix, `pad` 19/21. And **107 questions, none
unanswerable from the drawing** — the number most likely to embarrass the service is
the cleanest in the run.

The largest finding is a defect nine earlier acceptance runs could not have seen,
because none of them built a part with two hole sizes: **the claim could not add up two
groups of one kind.** Every flange was refused with "read as 1 round opening, builds 5;
read as 4 round openings, builds 5" — both clauses comparing a declared group against
the same total. The reading was right, the document was right, 1 + 4 = 5, and
`_opening_disagreements` matched each group against *every* built opening of its kind
rather than against its share. Any flange, any plate with two hole sizes. Grouped on
kind **and** depth now; 2/25 became 25/25.

The failure mode that matters is narrow and real. Both silent wrong parts are `pad` —
one boss twice its height, one hanging over the edge of its plate with the volume exact
to the milligram — and both are the mechanism this file has described and never
measured: **the claim compares compilation against reading and never reading against
the drawing.** Two in a hundred is what the moderation queue is for, and it is the
measurement that justifies `automatic_acceptance` staying off.

**The compiler never reaches for `new_body`**: 21 of 21 plates-with-a-boss came back as
one body. Not a defect — `solids` and `body_count` are different questions — but the
fourth wall from POSTMVP-016 measured on a family rather than noticed once: an
operation can be offered, readable and *unnecessary*.

**And twice the corpus's finding was about the corpus**, both times before anything was
published. `solid_count` is not `solids`; a mesh bounding box is a faceted
approximation and `verify.py` had already written down `MESH_CHORD_TOLERANCE_MM = 0.05`
after an 80 mm part measured 79.898 in its mesh. The runner records the geometry it
measured rather than only a verdict, which is exactly why a wrong rule could be
corrected and everything rescored without spending a model call. **A harness is a
measuring instrument and gets calibrated like one.**

**A reach is computed, not asked for** (CAD-IR 1.13, ADR-039). The fork closed on the
side that had measurements: `until_face` reproduces the kernel's own answer to
`0.000e+00` where the kernel is right, and `ScalarDifference` is an idea. It is not
refused, it is unbuilt — the evidence for it is a drawing whose reach genuinely is the
difference of two stated dimensions and which no face expresses.

**`Solid.extrude_until` is not called from anywhere in this repository.** Sixteen
measured cases: two correct, three raising, three *succeeding and returning the wrong
part* — a profile inside the material comes back as one valid solid reaching
`5 + √(40²+40²+10²) = 62.45`, which is the trial extrusion's own length. And no
post-check could catch them, because **`until` states no number at all**: the pattern
that caught the shell, the sweep and the draft has nothing to compare with.

So the document names the face and trusted code divides once —
`reach = ((p−o)·n)/(d·n)` — and the engine extrudes by it, the operation it has done
since ENGINE-MIG-003. **What that buys is a number**: one the manifest records, the
corpus states in closed form, and an expectation measures against.

Five refusals, each a measured case: `UNTIL_FACE_NOT_ONE` (two faces are two different
reaches — sharper than ADR-026's blend rule, which is only about a feature that
silently did not happen), `UNTIL_FACE_NOT_PLANAR`, `UNTIL_FACE_PARALLEL`,
`UNTIL_FACE_BEHIND` (the kernel's answer is to reverse, which contradicts the
`direction` the document states) and `UNTIL_FACE_COINCIDENT` — the one geometry that
made the first investigation think `extrude_until` was broken in general. Plus two
exclusions in the contract: a distance *or* a face, and no taper and no
`both_directions`.

**What is deliberately not caught**: a named plane is infinite, so the arithmetic
always answers and cannot know whether the extrusion lands on the face. It does not
need to — the part comes back in two pieces and `body_count` already sees it. Trusted
code refuses what it can decide; an expectation catches what only the built part shows.

Declared `experimental`, and the cycle cannot ask for it: a face selector is
dialect-legal only as a named selection written here (ADR-032), and "the face this rib
lands on" is not a constant. It arrives the way the shell did.

**A helix is not a 3D curve** (`docs/TASK-POSTMVP-P4-3-*`, probe committed). Gate P4's
table put the whole of P4.4 — spring, auger, helical groove, real thread — behind P4.3, a
coordinate vocabulary CAD-IR does not have and the largest single piece of the stage. That
sentence was inherited rather than measured, and the kernel says otherwise: a helix is
`pitch, height, radius, hand` and **an axis** — five numbers and a direction, **not one of
them a point in space**, and CAD-IR states all five already. Three of the four templates
are behind one new `SweepPath` kind; only a general spline is genuinely P4.3. The same
shape of finding as ADR-032's dialect wall, arrived at the same way.

Three measurements came with it. A section left on its own plane instead of the path's
normal sweeps its **projection** — 376.99 mm³ where 4752.39 was drawn, one valid solid, no
error — which 1.9's right-angle rule already refuses and which now has a number saying what
that rule is worth. A spring wound tighter than its own wire **matches Pappus**, because
the material counted twice is the material the formula counts twice, so only the genus
cross-check sees it — and `pitch ≤ 2·section_radius` is closed-form, so it should be
refused rather than discovered in a mesh. And **handedness is invisible to every number
this service measures**: a left-hand and a right-hand thread share volume, topology and
bounding box, so it cannot be checked after the fact — it has to be read correctly, and
only a person can catch it being wrong.

**A helix is five numbers and a direction** (CAD-IR 1.14, ADR-040). The investigation
above became a contract: a second `SweepPath` kind whose **plane's normal is the axis**,
so a spring, an auger, a helical groove and a profiled thread are expressible and P4.3 is
untouched. Three findings decided its shape.

**`hand` is required**, because it is the one property of a part in this contract that
cannot be checked against the built solid — a left-hand and a right-hand helix have the
same volume, topology and bounding box. A default would have made the uncheckable property
the one a document may leave out.

**The section's plane comes from the path** (`{"on": "path_start"}`). A planar path leaves
the profile's plane a real choice the drawing shows, so 1.9 makes the document state it; a
helix's tangent leans by the lead angle, so exactly one plane works and the path already
states the numbers that fix it. Getting it wrong costs an order of magnitude — 376.99 mm³
where 4752.39 was drawn, one valid solid, no error.

**No discriminator field.** The two path kinds have disjoint required properties and both
forbid extras, so exactly one validates any payload. A required `kind` would have been
tidier and would have invalidated every earlier document the moment the normalizer
relabelled it — and the normalizer is relabel-only by design.

`HELIX_PITCH_TIGHTER_THAN_SECTION` is the new refusal and the fifth instance of ADR-033's
rule: a spring wound tighter than its own wire passes through itself, reports valid, and
**matches Pappus**, because the material counted twice is the material the formula counts
twice. The genus cross-check sees it afterwards; the condition is closed-form beforehand.

**P4.3 is not one wall but five questions** (CAD-IR 1.15, ADR-041,
`docs/TASK-POSTMVP-P4-3-a-path-that-leaves-its-plane.md`). "A new coordinate vocabulary
in CAD-IR; the largest single piece of P4" covers five roadmap items, and only one of
them is about coordinates. Built: a **3D polyline**, which needs one number per point,
because tangency, a perpendicular profile and bends that clear it are rules 1.9 already
states. Built: a **conical helix**, one field. Refused, with measurements: a 3D spline,
a projected curve, imported points. The fourth wall in a row to turn out lower than the
document describing it, found the same way — by asking the kernel.

**Pappus is exact for a path in space**, and that is what makes a spatial sweep a corpus
case at all: the volume element of a tube is `(1 − uκ) du dv ds`, so the correction is
the section's first moment about the path — zero when the centroid rides it, whatever
the torsion. Which also means **volume cannot see the third dimension**: a run kept
planar and the same run bent out of its plane both come back 12003.3857. The bounding
box can, and documents already state one.

**A spline is refused rather than unbuilt.** One point list gives three curves depending
on a parameterization the document does not carry (111.5688 / 113.2632 / 113.0538), and
the curve leaves the box its own points define — z = 24.974 where the highest stated
point is 20. Reproducible is not determined, and ADR-018 needs the second: a hash
identifies a part only if the document does. Its swept volume also agrees with Pappus to
1e-3 rather than 1e-12, against a length that is no closed form, so the corpus would have
nothing to state.

**`pitch` is not what the kernel means by it.** A `cone_angle` makes this kernel measure
the pitch along the cone's *slant* while a drawing dimensions it along the axis, so a
tapered spring stating pitch 10 over height 30 at 30° gets **3.464 turns where it drew
3** — valid, plausible, and agreeing with every closed form computed from the kernel.
A new shape of finding: the five before it are the kernel answering the right question
wrongly, this is the kernel answering a **different question with the same word**.
Trusted code divides by `cos(cone_angle)` once, which is `until_face`'s pattern again.

**A swept path that comes back beside itself passes every check this service has**, and
it is the first failure of this family that nothing caught. A flat spiral, four R35
bends, a section reaching 30, last run 25 mm from the first: one valid solid, volume
2643399.9499 matching Pappus to 4.657e-10, B-rep genus 0 **and** mesh genus 0 with zero
open edges — so POSTMVP-020's cross-check agrees with itself, because this surface passes
through itself *smoothly*. It has to be a spiral: two tangent bends of radius R put the
runs 2R apart and the bend rule already requires R to clear the profile, so a U-turn
cannot do it. **And that path is planar** — the hole is in 1.9, not a cost of 1.15.
`SOLID_PASSES_THROUGH_ITSELF` closes it with one question to the kernel that catches all
three known cases in milliseconds, and it does **not** replace the closed-form
pre-checks: those name the mistake in numbers a repair loop can read, this one can only
say it happened.

**1.14 broke a chain and nothing saw it.** `feature.sweep.helix` was spliced into the
middle of the `elif` that decides what a feature is, so a helical **cut** never required
`cut.sweep` — an operator's rollback switch that silently stopped covering a case — and a
solid sweep stopped counting as a solid, so a boss on a swept body no longer required
`feature.boss.additive`. Invisible to the corpus, whose one helical case is a solid sweep
standing alone. The test now parametrises over both kinds of feature and all three kinds
of path: one example per type is what let the second `ClaimLoop.Typed` defect through,
and it is the same lesson twice.

**A thread is a direction, and the frame it points in was nobody's**
(`docs/TASK-POSTMVP-P3-4-a-thread-is-a-direction.md`, ADR-040's amendment). Gate P3 asks
one thing this repository had never measured — *modeled threads pass a manifold check* —
and until 1.14 a thread was not expressible, so the clause could not be tested. It passes:
an M20 × 2.5 as a blank and a helical cut, at 2, 6 and 12 turns, **0 open edges, 0 flipped
normals, genus 0**, 0.13–1.68 s and 112–578 KiB. An internal thread passes too.
`feature.thread` is **not** added — a thread is a `solid.extrude` and a `cut.sweep`, which
is POSTMVP-011's rule again.

But the engine had to be fixed first, and it is not about threads. `SketchOnPathStart`
fixed the section's **normal** and left the frame *inside* that plane to build123d, whose
rule is to project whichever global axis is least parallel to it — the axis for a helix,
**+X** for one of the 3D-path probe's directions. A heuristic, not a convention. A round
section cannot tell, which is why 1.14 never asked; a thread's flanks are nothing but a
direction, and the same section aimed the other way removes **188.34 mm³ where 374.19 was
drawn**, with no error. The engine now builds the frame from the path: x is the helix's
axis projected into the section plane, y is radially outward — along the screw, depth
inward, which is how a drawing draws one.

**And the spring's own arithmetic was the special case.** OpenCascade's default framing
keeps a section from twisting relative to a *fixed* direction, which round a helix means
twisting relative to the path's own normal — 0.052%, 0.476%, 1.733%, 4.745% at 1, 3, 6 and
12 turns. Under Frenet the closed form `V = A·L·(1 − κ·ū)` is exact at every turn count,
and a circle sits *on* the path so `ū = 0` and the whole correction vanishes. Frenet stays
on the helical branch: a helix has no point of zero curvature and a straight run is nothing
but one.

**The order of the cuts is the whole part.** Three ways of writing one nut out of the same
three solids: `(shell − groove) − bore` is the part; `shell − bore − groove` is the plain
hollow nut **to the digit**, the groove having done nothing and said nothing; and
`shell − (bore + groove)` is 14 324 open edges. CAD-IR applies features in the document's
own order (ADR-028), so this is the document's decision and nothing tells it which is
right — only the silent one is dangerous, because the third fails `closed_manifold_mesh`
on every build.

**What is left of P3.4 is not geometry.** `thread.designation` — the callout — is the gap
POSTMVP-011 named and it is still open. It cannot be checked by measuring the delivered
solid: M20×2.5-6g is not a shape, and the same part carries it whether the tolerance class
is right or wrong. That puts it beside `hand` in ADR-040's argument — a property only a
person can catch being wrong — and decides its place: read off the drawing, carried by the
claim, shown to the operator. It is the next contract version this line needs.

**P3.5's high-level features are refused** for the reason they are described by: they
compile into operations the contract already has. Same argument as hole families and the
rib. "Simplifies the model's reasoning" is a case for the prompt and the output profile
(ADR-029, ADR-032), not for the contract.

**What is next**: the rest of Gate P4. Section correspondence — a square rotated 90° is
the same square, so a document that states the rotation gets a prism without one — and
the claimed topology for sweep and loft, where the closed forms are derived and what is
missing is cases rather than mathematics. `docs/POST-MVP-ROADMAP.md` has the order.

The contract is settled for now: there is no queued CAD-IR version, so the rule about
not running two contract changes side by side is not binding on the next piece of work.

**A draft names its walls** (POSTMVP-026, ADR-035), and it is the first operation admitted
against the rule three milestones arrived at. POSTMVP-024 had measured that a drafted boss
is *identical* either way — 26 689.1761 mm³ from `extrude(taper=10)` and from drafting the
walls afterwards — so the case had to be two things composition cannot reach: **two walls
of four** (29 178.7680 mm³, `a·h·(a − h·tanθ)`, bounding box unchanged because the walls
the drawing leaves alone still stand) and **a body no extrusion made** (a turned tube's
outer wall, 18 849.5559 → 14 678.4446, the frustum less the bore).

The faces are named by selector and so is the **neutral face**, whose plane holds still —
about the base 26 689.1761, about the top 37 974.1029, both valid. And its normal is turned
**inward**, which is the one thing the engine decides rather than passes through: read
straight off, a base face looks down and out of the part, so a positive angle would narrow
the part downwards. Turned inward, the named face keeps its size and the answer is the same
whichever end the document names — which is what makes the rule sayable: *positive draws
the walls in as they leave the neutral face.*

Two firsts in its failure modes. At exactly the closing angle the kernel returns the
pyramid and **reports `is_valid` false** — the first time it has volunteered that its own
answer is wrong, where the shell, the sweep, the taper and `until` all claimed validity.
Past it, `Standard_ConstructionError` **with an empty message**, which without a wrap
escapes as a crash rather than a refusal. Both are `DRAFT_TOO_STEEP`.

**Rib itself needs no operation** (POSTMVP-022): a closed contour extruded both ways,
31 468.0000 mm³ against a closed form of 31 468. What the roadmap listed beside it does.
`feature.draft(faces, angle)` is the one selections are waiting on — POSTMVP-024 found the
four upright walls of a boss are there to name, and then nothing in CAD-IR takes a set of
wall faces: a fillet takes edges and a shell takes the faces it removes. It earns its place
by the rule those three milestones arrived at, because it says what `taper_deg` cannot:
*these* walls and not those, and a draft on a body a revolve or a boolean produced.

**An up-to-face extrusion is designed and not built**
(`docs/TASK-POSTMVP-P3-2-up-to-a-face.md`), and the investigation ends by dropping
`extrude(until=…)` altogether. Sixteen
cases: two are correct, three raise, and three succeed wrongly — a profile inside the
material spikes 62.45 mm into open space and reports one valid solid, a cut to the next
surface can remove nothing. `until` is also the first operation that would state **no
number**, so the post-check pattern that caught the last three defects has nothing to
compare against. So an up-to-face extrusion **names the terminating face with a selector**
(ADR-019's rule, again) and trusted code computes the reach — `((p − o)·n)/(d·n)`, which
reproduces the kernel's own answer to 0.000e+00 where `until=` works, gives the corpus a
closed form the kernel used to keep to itself, and turns each failure into a refusal or into
two solids that `body_count` already sees. Building it is a CAD-IR version.

The local session probed the same thing independently and found two more of its lies
(POSTMVP-022): `Until.NEXT` added 14 834.94 mm³ to a bracket — a slab rather than a rib, and
closed-form from nothing — and `Until.LAST` added nothing at all, silently. The objection that
decides it is upstream of whether it works: **`until` answers a question the drawing has
already answered.** A rib is dimensioned, and answering by asking the kernel puts a number in
the part that no document states and no expectation can check. Where a reach genuinely is not
stated it is a *difference* of two dimensions, which is the one thing 1.11's arithmetic
deliberately cannot express — so that, and not the rib, is what an up-to-face extrusion is
for.

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
