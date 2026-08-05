# POSTMVP-020/021: the topology oracle and the extrusion modes — acceptance

**Date:** 2026-08-02 · **Result:** PASS. CAD-IR 1.10, 42 capabilities, 59 positive and 31
negative corpus cases, 832 Python tests passing.

`docs/adr/ADR-033-two-counts-of-one-integer.md` is the decision. Two pieces of work in
one record because they were done together and share a finding.

## POSTMVP-020: the topology oracle

Gate P4 asks for an oracle that checks the *structure* of a result rather than its size.
The obstacle looked like this: a drawing agent will never state a face count, so what
would the check compare against?

It compares the result against **itself**. Every build delivers two files written by two
different exporters, and the genus of the solid — how many handles it has — can be
computed from either:

```
from the STEP   V - E + F = 2(S - G) + (L - F)      Euler-Poincare, over the B-rep
from the STL    V - E + F = 2c - 2G                 Euler, over the triangles
```

Neither number comes from the document, so nothing has to have been stated and the check
cannot be satisfied by a plan agreeing with itself. It runs on every build as
`topology_agrees_with_mesh`, keyed `validate.topology`.

### The `L` term, and why a previous attempt gave up

`_genus`'s own docstring records trying the naive `V − E + F = 2 − 2G` on the B-rep and
reading **0 for a plate that plainly had a hole in it**: a B-rep counts a full circle as
one edge with one vertex. The general formula counts *loops*, and the face carrying a
hole has two. Measured before anything was written:

| solid | V | E | F | wires | genus |
|---|---|---|---|---|---|
| box | 8 | 12 | 6 | 6 | 0 |
| plate, 1 hole | 10 | 15 | 7 | 9 | 1 |
| plate, 3 holes | 14 | 21 | 9 | 15 | 3 |
| cylinder | 2 | 3 | 3 | 3 | 0 |
| tube | 4 | 6 | 4 | 6 | 1 |
| shelled box | 16 | 24 | 11 | 12 | 0 |

### What it catches

The self-intersecting sweep from ADR-031, which is a document OpenCascade builds without
complaint:

| | the STEP says | the STL says |
|---|---|---|
| Ø16 pipe round a 4 mm bend | genus 0, 4 faces, `is_valid` true | genus **−45**, 69 open edges |

Neither half is obviously wrong alone — plenty of correct parts are genus 0, and a mesh
fault usually reads as an exporter problem. The mismatch is the finding.
`test_the_topology_oracle_catches_the_tear_that_the_solid_alone_denies` builds it through
build123d directly, because the engine now refuses the document before the kernel sees it.

### The corpus states its topology where the drawing settles it

Sixteen cases, closed-form like the volume: a box is 6 faces, 12 edges, 8 vertices, and
every round through hole adds **one face, three edges and two vertices** — two circles and
the seam OpenCascade puts on a closed cylinder. The seam is the migration's recorded cost
(ADR-023) turned into a number a check reads.

## POSTMVP-021: how an extrusion travels

Two modes on `solid.extrude` and `cut.extrude`.

**`both_directions` states the total**, split half each way — the reading a revolve's has
had since 1.4. The alternative would build a part twice as thick and make a claimed
thickness parameter name half of it. The volume is identical either way; only the
position says which happened, so the test checks both:

```
plain      z 0.0 .. 10.0
symmetric  z -5.0 .. 5.0     same volume
```

**`taper_deg` narrows the extrusion as it travels along `direction`.** Positive narrows,
negative widens, and that is the only rule. Making it mean "draft" — about withdrawal,
therefore opposite on a boss and in a cavity — would have the engine flip the sign for a
cut, and a sign the document cannot see is a sign somebody else chose. A moulded pocket
writes a negative taper, explicitly.

The arithmetic is the prismatoid rule, exact for a linear taper, measured against the
kernel to six decimal places before being written down:

| taper | built | `h/6 × (A + 4·A_mid + A_top)` |
|---|---|---|
| 3° | 7 689.215425 | 7 689.215425 |
| 5° | 7 485.273707 | 7 485.273707 |
| 10° | 6 983.493055 | 6 983.493055 |

### A draft steep enough to close the section is refused

The measurement that earns the check: a 20 × 20 pad drafted 45° over 40 mm comes back as
a **pyramid 10 mm tall**. The section closes at 10, the kernel stops there and reports
one valid solid of five faces with a plausible volume. The document asked for 40.

The engine compares the built height along the plane's own normal against the stated
distance and refuses with `EXTRUDE_DRAFT_TOO_STEEP`. A pre-check would have to offset the
profile inward and ask whether anything survived, which is another kernel behaviour to
trust; the kernel is asked and then checked, as it is for a shell.

### Two combinations the contract refuses

A `through_all` cut may declare neither mode. It has no second side to reach, and its far
end is measured against the body it cuts — so a tapered one would be tapered over a length
the *engine* chose. Both are contract refusals, both are corpus negatives.

## The pattern these share

This is the third silent-wrong-part finding in three milestones, and they are the same
shape every time: **OpenCascade returns something valid rather than refusing.**

| operation | what the document asked | what the kernel returned |
|---|---|---|
| shell (ADR-030) | hollow with a 30 mm wall | the original solid, whole |
| sweep (ADR-031) | a pipe round a 4 mm bend | a self-intersecting solid, `is_valid` true |
| draft (ADR-033) | 40 mm at 45° | a stump 10 mm tall |

Each is now a named code: `SHELL_NO_CAVITY`, `SWEEP_BEND_TIGHTER_THAN_PROFILE`,
`EXTRUDE_DRAFT_TOO_STEEP`. The rule worth stating on its own is that **every operation
which can be over-driven gets a post-check comparing the result against what was asked**,
because a pre-check would have to predict the kernel and the kernel is the only thing that
knows.

## Tests

| suite | result |
|---|---|
| Python | **832 passed, 1 skipped** |
| .NET | 6 + 30 + 44 + 31 (4 container tests skipped — no `CAD_ENGINE_IMAGE` here) |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

## What this is not

**Neither addition reaches the drawing cycle, and neither should yet.**
`both_directions` and `taper_deg` are modelling choices rather than things a drawing
states in words the reading stage has — a part is not drawn "symmetric about a plane",
and a draft angle is a note the claim has no word for. Offering them would be the trade
ADR-029 forbids. The oracle needs no offer at all: it runs on every build, including
every build the cycle already produces.

> **Half of that is no longer true.** Two days later the claim gained the word:
> `ShapeClaim.draft` names the parameter holding the angle
> (`docs/acceptance/POSTMVP-021-draft-in-the-claim.md`, ADR-033's amendment). The offer is
> still held back, now by ADR-029's vision wall rather than by the claim's vocabulary.
> `both_directions` stands as written — a symmetric extrusion is a choice about where the
> part sits, and nothing on a drawing states it.

**It is not Gate P4 complete.** The oracle checks the genus two ways and the corpus checks
face, edge and vertex counts against closed-form arithmetic on sixteen cases. What Gate P4
also wants is that check on *every* golden model, and there are 59 rather than 100.

**Rib (P3.2), up-to-face extrusion (P2.1) and the thread callout (P2.3) are not in.** Rib
needs "extend to the next face", which is `extrude(until=…)` — probed and failing on the
first attempt with `Extrusion is None`, so it needs its own investigation rather than a
guess. The thread callout is a manufacturing note rather than geometry and belongs with
the annotation work in P3.4.

> **That investigation is done** (`docs/TASK-POSTMVP-P3-2-up-to-a-face.md`, 2026-08-04) and
> it ends by dropping `until=` altogether. `Extrusion is None` turned out to be one geometry
> rather than a general failure — two of sixteen cases are plainly correct — but three others
> are worse than an exception: a profile inside the material spikes 62.45 mm into open space
> and reports success. The design instead **names the terminating face with a selector and
> computes the reach in trusted code**, which reproduces the kernel's own answer to
> 0.000e+00 on the case where `until=` works and turns each of its failures into either a
> refusal or something `body_count` already catches. Still designed rather than built: it is
> a CAD-IR version.
