# POSTMVP-021 follow-up: a draft the claim can see — acceptance

**Date:** 2026-08-04 · **Result:** PASS. CAD-IR 1.10 unchanged, 889 Python tests passing.

`docs/adr/ADR-033-two-counts-of-one-integer.md` carries the decision, as an amendment to
the record it contradicts: the extrusion modes landed with the sentence "a draft angle is
a note the claim has no word for", and this is that word.

Nothing about the geometry changed. `taper_deg` has been buildable since 1.10 and the
corpus has drafted pads at 5° and 10° with prismatoid arithmetic. What changed is that the
reading stage can now state a draft and trusted code can disagree with the document about
it.

## Why a draft needed one at all

The claim exists for the failure no measurement catches: a document that is valid, builds,
measures exactly what it declares, and is the wrong part. A forgotten draft is the purest
example yet found. Measured against the kernel, a 20 × 20 sketch extruded 10 mm:

| taper | volume mm³ | x span | z span | bounding box |
|---|---|---|---|---|
| none | 4 000.000 | ±10.000 | 0 … 10 | 20 × 20 × 10 |
| +20° | 2 720.752 | ±10.000 | 0 … 10 | **20 × 20 × 10** |
| −20° | 5 632.513 | ±13.640 | 0 … 10 | 27.28 × 27.28 × 10 |

The middle row is the one that matters. A narrowing taper leaves the sketch as the widest
section, so a document that dropped it agrees with the drawing on the outline, the
openings, the solid count **and the bounding box**, and holds a third less material. The
volume expectation does see it — and the volume expectation is written by the same stage
that chose the taper, so it agrees with whatever that stage decided.

This is a step worse than the shell that ADR-030 introduced `wall` for. A hollow part at
least has an inside face and a quarter of the material; a drafted one differs in nothing
any other field of the claim counts.

## What the word is

`ShapeClaim.draft` — the id of the parameter holding the draft angle, or nothing. The
second field, after `wall`, that says how much of the part is there rather than what shape
it is, and the fifth to stay inside ADR-025's rule: **a name, never a number.**

`DRAFT_PARAMETER` is raised four ways:

| the document | reported as |
|---|---|
| extrudes square | `no taper` |
| tapers by a literal | `the literal 5.0` |
| tapers by another parameter | that parameter's id |
| tapers by the right parameter, which holds 0° | `p_draft = 0` |

And not raised when the claim says nothing. Silence is not a claim, here as in every
field since POSTMVP-016: a view that did not show the angle says nothing about it, and the
check exists for the drawing that plainly marks one against a document that ignored it.

## The direction is not in the claim, and that was measured

The obvious second word would be which way the walls lean, and it is refused. The kernel
was asked what a taper does when the extrusion runs backwards:

```
amount=+10.0 taper=+20.0  vol= 2720.752  x=[-10.000,+10.000]  faces: 400.0 → 161.814
amount=-10.0 taper=+20.0  vol= 2720.752  x=[-10.000,+10.000]  faces: 400.0 → 161.814
amount=+10.0 taper=-20.0  vol= 5632.513  x=[-13.640,+13.640]  faces: 400.0 → 744.166
amount=-10.0 taper=-20.0  vol= 5632.513  x=[-13.640,+13.640]  faces: 400.0 → 744.166
```

A positive taper narrows away from the sketch plane whichever way the extrusion travels,
so `direction` cannot flip it. The sign therefore lives entirely in the parameter's value,
which reaches the document from the same reading stage that writes the claim — and a
canonical `Scalar` is `float | ParameterRef` with no arithmetic, so the compilation stage
has no way to negate an angle it was handed. A claimed direction could only ever disagree
with the reading stage's own number, and a stage checked against itself is not a check
(ADR-018).

The one part of it worth keeping is the zero case, which is why it is in the table above:
the id and the angle arrive from the same reading, and a parameter referenced correctly
while holding 0° is the one place those two can be made to contradict each other.

## What is still not checked

**Which feature leans.** A drawing that drafts a pocket against a document that drafts the
outer wall by the right parameter agrees here. The same limit `wall` has, for the same
reason: a claim of kinds and names cannot say where.

**The cycle still cannot ask for one.** The output profile offers no tapered extrusion, so
the reading prompt does not ask for `draft_parameter` and the worker does not copy one into
`shape-claim.json`. That is the ADR-030 ordering repeated on purpose — the claim's word for
a thing arrives first, the offer follows — and here the offer is held by something specific
rather than by inertia: a drawing marks a draft as an angle with an arrow on a section
view, and whether an agent reads that off a scan is ADR-029's **vision** wall, which no
code in this repository settles. It is a question for a run.

## The contract's own rules got tests that need no kernel

Found while writing this: 1.10's refusals — the ±89° limit, a `through_all` cut that tries
to taper, a `through_all` cut that tries to reach both ways — were exercised only by the
engine's golden corpus, which skips itself on a machine with no CAD library. A contract
refusal that only a kernel can prove is a refusal CI cannot see. They are now in
`apps/api/tests/test_cad_ir_extrude_modes.py` alongside the claim's, where they run
everywhere.

## Tests

| suite | result |
|---|---|
| Python | **889 passed, 1 skipped** |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

24 of those tests are new, in one file. No fixture, schema or capability changed: the claim
is not part of CAD-IR and does not move its version.
