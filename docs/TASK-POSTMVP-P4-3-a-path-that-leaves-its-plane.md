# P4.3: what a 3D curve is worth, item by item — the investigation

**Date:** 2026-08-12 · **Status:** investigated; one of the five items became CAD-IR 1.15,
three are refused for measured reasons, one had already shipped.
**Probe:** `scripts/probe_build123d_3d_path.py`, build123d 0.11.1 / OpenCascade 7.9.3.1.1

`docs/GATE-P4-ANALYSIS.md` calls P4.3 "a new coordinate vocabulary in CAD-IR; the
largest single piece of P4", and the roadmap lists five things behind it:

```
3D polyline · 3D spline · cylindrical/conical helix · intersection/projected curve
· imported points
```

The helix investigation (`docs/TASK-POSTMVP-P4-3-a-helix-is-not-a-3d-curve.md`) already
took three of P4.4's four templates out from behind this wall by asking the kernel
instead of re-reading the table. This does the same for what is left, and the answer is
that P4.3 is **not one wall but five different questions**, only one of which is about
coordinates at all.

| item | verdict | why |
|---|---|---|
| 3D polyline | **built** (1.15) | one new number per point; everything else 1.9 already checks |
| cylindrical helix | shipped (1.14) | ADR-040 |
| conical helix | **built** (1.15) | one field, closed form verified — and `pitch` does not mean what a drawing means by it |
| 3D spline | **refused** | the stated points do not determine the curve, and the curve leaves the box they define |
| intersection / projected curve | **refused** | it states no number, which is the `until` argument (ADR-039) |
| imported points | **refused** | a part whose shape is not in its own document cannot be identified by its hash (ADR-018) |

And the probe found one thing nobody was looking for, which is the largest item in this
document: **a swept path that meets itself far from any bend passes every check this
service has.** See "The sixth instance, and the first one nothing caught".

---

## 1. A path that leaves its plane needs one number, not a vocabulary

The smallest genuinely three-dimensional path is the one a drawing of a bent tube
gives: straight runs and bend radii, with two of the bends **in different planes**.

```text
A (0,0,0)  --+X, 30-->  B (30,0,0)
B          --bend R20 in XY-->  C (50,20,0)
C          --+Y, 30-->  D (50,50,0)
D          --bend R20 in YZ-->  E (50,70,20)
E          --+Z, 30-->  F (50,70,50)

path length   152.8319    closed form 90 + 20*pi = 152.8319    diff 2.842e-14
```

Swept with a Ø10 section:

```text
circle 5, the 3D run                12003.3857   7/11/6   valid   Pappus 12003.3857   diff 1.819e-12
circle 5, the same run kept planar  12003.3857   7/11/6   valid   Pappus 12003.3857   diff 1.819e-12
```

**Pappus is exact for a path in space**, and that is not an accident of this example. For
a tube whose section's centroid rides the path and stays perpendicular to it, the volume
element is `(1 − uκ) du dv ds`, so the correction is the section's first moment about the
path — which is zero when the centroid is on it. Torsion, the entire difference between a
3D path and a planar one, **drops out of the volume**. So the corpus can state a 3D
sweep in closed form, which is the property that has to hold before an operation can be
promoted at all.

The second row of that table is worth reading twice: the 3D run and the planar run have
the **same volume to the digit**. Volume cannot see the third dimension of the path.
The bounding box can, and it is an expectation documents already carry.

A section that is not across the path is still swept as its projection, exactly as in the
plane:

```text
section perpendicular   12003.3857
section tilted 45 deg    8487.6754     ( = 12003.3857 / sqrt(2) )
```

so 1.9's `SWEEP_PROFILE_NOT_PERPENDICULAR` needs nothing new — only three components
instead of two.

### The bend needs no new vocabulary either

```text
tangent arc (start, tangent, end)  length 31.4159
three-point arc                    length 31.4159   diff 7.105e-15
and the centre is derivable:       |start-c| 20.0000   |end-c| 20.0000
```

An arc in space is fixed by any of three equivalent statements, and CAD-IR 1.9 already
requires the path to be **tangent-continuous**, which removes the ambiguity the 2D form
carries a `sweep` field for. So a spatial arc states `start`, `end` and `center` — the
same three things the 2D one states, each with a third component — and the way round is
the shorter of the two arcs, which is the only one a tangent-continuous bend can be.

A half turn or more is the one thing that form cannot say: `start`, `center` and `end`
collinear leaves the arc's plane undefined and the kernel raises
`gp_Dir::Crossed() - result vector has zero norm`, an empty-message construction error of
the same kind the draft investigation found. It is refused with a reason, and a U-bend is
two quarter turns joined tangentially — which is what the document has to say anyway,
because 1.9 checks the join.

**So the coordinate vocabulary P4.3 was said to need is one number.** A point in a
spatial path has three components where a planar one has two, and every rule around it
already exists.

---

## 2. A spline: the points do not determine the curve

This is the item P4.3 is really about, and it fails upstream of the kernel.

Four points, five ways of asking for the spline through them:

```text
default              length 111.5688   bbox y[-0.208, 20.000]  z[ -3.858, 24.974]
scale=False          length 111.5688   bbox y[-0.208, 20.000]  z[ -3.858, 24.974]
uniform parameters   length 113.2632   bbox y[-0.175, 20.000]  z[ -5.034, 25.034]
tangents stated      length 113.0538   bbox y[-0.384, 20.000]  z[ -1.376, 21.717]
the points themselves                  bbox y[ 0.000, 20.000]  z[  0.000, 20.000]
```

Two findings, and either alone would be enough.

**One point list, three curves.** The parameterization — how the curve is asked to
distribute its parameter across the points — is a choice nobody drew, and it changes the
length by 1.5%. A document stating four points states a curve only in company with a
convention it does not carry. ADR-018 traded an expression language away so that a
canonical document would hash to a part; a document whose part depends on a convention
outside it defeats that trade in a way no canonicalization can repair.

**The curve leaves the box its own points define.** The highest stated point is at
z = 20 and the curve reaches **z = 24.974**; the lowest is 0 and it reaches −3.858. Nearly
5 mm of part in each direction that no number in the document bounds — and the bounding
box is one of the two expectations that catch a wrong part at all.

A spline is at least reproducible:

```text
forwards 111.5688332395   backwards 111.5688332395   diff 0.000e+00
```

which is a **different thing from determined**, and it is the second that ADR-018 needs.

And the part it makes cannot be checked:

```text
circle 4 along the spline   5608.0599   valid   Pappus (kernel's own length) 5608.0612   diff 1.338e-03
```

Against an analytic path Pappus agrees to 1e-12. Against a spline it agrees to 1e-3 — and
that comparison used *the kernel's own measurement of the length*, which is not a closed
form at all. There is no number here a corpus case could state from a drawing, so a
spline sweep could only ever be checked by writing down what a run happened to produce,
which is exactly what the corpus's own rules forbid: *a figure whose source cannot be
named is a figure somebody typed to make a test pass.*

**Refused, and not merely unbuilt.** Unlike `ScalarDifference`, which ADR-039 left open
because the evidence for it is a drawing nobody has produced yet, this one has been
measured and the measurement is against it.

---

## 3. A conical helix: `pitch` is not the drawing's pitch

`Helix` takes a `cone_angle`, so a tapered spring looks like one more field on the node
1.14 already has. It is — with one trap in it.

```text
cone   0.0 deg  turns 3.00000  z per turn 10.00000  length 378.1829  closed 378.1829  diff 4.795e-10
cone   5.0 deg  turns 3.01146  z per turn  9.96195  length 404.3868  closed 404.3868  diff 5.403e-10
cone  15.0 deg  turns 3.10583  z per turn  9.65926  length 469.7609  closed 469.7609  diff 3.369e-10
cone  30.0 deg  turns 3.46410  z per turn  8.66025  length 624.7993  closed 624.7993  diff 1.680e-10
```

`z per turn` is `pitch · cos(cone_angle)`: **the kernel measures the pitch along the
cone's slant, and a drawing dimensions it along the axis.** A document stating pitch 10
over height 30 at 30° gets **3.464 turns where it drew 3** — a spring with half a turn
too many, valid, plausible, and matching every closed form anybody would compute *from
the kernel*.

This is a new shape of finding here. The previous five are the kernel returning a wrong
answer to the right question; this is the kernel answering a **different question with
the same word**. Nothing about it is a bug — a slant pitch is a reasonable definition —
and nothing downstream would ever notice.

So trusted code converts, once: the document states the axial pitch a drawing states, and
the engine passes `pitch / cos(cone_angle)` to the kernel. That is the `until_face`
pattern again — *what a division in trusted code buys is a number* — and with the
conversion in place the closed form for the length,

```text
L = (1 / (k·tanα)) · [ r√(r²+c²) + c²·asinh(r/c) ] / 2   evaluated from r₀ to r₁
    with k = p_axial / 2π,  c = k·secα,  r₁ = r₀ + h·tanα
```

matches the kernel to **3e-10** across the whole range. Verified in the probe, and it is
what the corpus case states.

---

## 4. The two that are refused for reasons that are not about coordinates

**An intersection or projected curve** is a path derived from geometry that already
exists rather than stated. It is `until` under another name (ADR-039): it puts a number
in the part that no document states and no expectation can check, and unlike `until_face`
there is no division in trusted code that reproduces it — projecting a curve onto a
general surface is not arithmetic on stated numbers. What it would be *for* is a groove
following a shape somebody else made, and the honest form of that is a path the drawing
dimensions.

**Imported points** would make the part depend on bytes the document does not contain.
Every argument in ADR-018 applies at once — a canonical document is supposed to identify
a part by its hash — and boundary 5 of this project applies on top: content that arrived
with an upload is data, never an instruction, and a point file is an instruction to the
kernel wearing a data hat.

---

## 5. The sixth instance, and the first one nothing caught

### It has to be a spiral, and that is why the gap was never found

The first candidate was two runs joined by a U-turn, and it does not work — which is
worth writing down, because it is the reason the existing per-bend check almost covers
this whole family. **Two tangent bends of radius R put the outgoing and returning runs
2R apart**, and `SWEEP_BEND_TIGHTER_THAN_PROFILE` already requires R to clear the
profile. So `2R ≥ 2 × reach`, and a U-turn's two runs can never touch. (The first
attempt at this measurement got that wrong twice over — the geometry it used had R10
bends under a section reaching 25, so the bend rule caught it, and a later one put the
return run past the flat end cap of the first, where the two tubes miss by 5 mm.)

What the per-bend check cannot see is a path that comes back **alongside a part of
itself that is not its neighbour**. A flat spiral: four bends of R35, a section reaching
30 — every bend clears — and a last run 25 mm from the first.

```text
spiral, runs 25 apart, section 30   2643399.9499   11/19/10   valid   Pappus 2643399.9499   diff 4.657e-10
the same spiral, section 10          293711.1055   11/19/10   valid   Pappus  293711.1055   diff 5.821e-11
```

Volume matches Pappus because the material counted twice is the material the formula
counts twice, which is the helix-pitch finding with different geometry. What is new is
what happens next:

```text
B-rep   solids 1  shells 1  faces 11  edges 19  vertices 10  genus 0   is_valid True
mesh    triangles 33764  open edges 0  inconsistent normals 0  genus 0
```

**Every check this service has passes.** The genus cross-check of POSTMVP-020 — the one
that catches the self-intersecting sweep of POSTMVP-018 — agrees with itself, because
this surface passes through itself *smoothly*: no triangle edge is left unmatched, so the
mesh is a closed manifold and both computations of the genus give 0. The bounding box is
right. The volume matches its own closed form. A `body_count` of 1 is right.

And **this path is planar.** The hole is in 1.9, shipped, and it is not about the third
dimension at all — a spatial path only makes it easier to write by accident, because two
views of a bent tube do not show the clearance between two runs.

Every closed-form check this repository has written for this family is **local**:
`SWEEP_BEND_TIGHTER_THAN_PROFILE` looks at one bend against the profile,
`HELIX_PITCH_TIGHTER_THAN_SECTION` at one turn against its neighbour. Two *different*
parts of a path meeting each other is not visible to either, and no closed form over
segment pairs is exact once the section is not round — the section's orientation at each
run is composed from every bend before it.

### The kernel can answer it exactly, and cheaply

`BOPAlgo_ArgumentAnalyzer` with `SelfInterMode` is in OCP and takes milliseconds:

```text
a plain block                      self-intersects=False   0.00s
a cylinder                         self-intersects=False   0.00s
the spiral, section 10             self-intersects=False   0.09s
the spiral, section 30             self-intersects=True    0.18s
tight bend R4, section 8           self-intersects=True    0.03s
the same bend, section 2           self-intersects=False   0.03s
helix pitch 2.0 under a 2 mm wire  self-intersects=True    0.84s
```

**One question catches all three known cases**, and reports clean on every ordinary part.

That does not make the two closed-form pre-checks redundant, and the distinction is the
one this repository keeps arriving at: a pre-check refuses with **a number the repair
loop can read** — "bends at radius 4 while the profile reaches 8 towards the centre of
that bend" — and this one can say only "it passes through itself somewhere". The
pre-checks name the mistake; this is the backstop for the cases no closed form covers,
and it is the answer to a question that until now had no answer at all.

---

## What was built from this

CAD-IR **1.15** (ADR-041): a spatial path, a cone angle on the helical one, and
`SOLID_PASSES_THROUGH_ITSELF` as a post-check on every sweep and loft.

**What P4.3 leaves behind**: a general 3D spline, and the guide curves and orientation
modes of P4.1/P4.2 that would have used one. Those are not blocked on a coordinate
vocabulary any more — 1.15 has one — they are blocked on the same three walls as
everything else (ADR-029), plus the one this document adds: **a curve the document does
not determine is not a curve this service can deliver.**

## Reproducing

```bash
.venv-cad/Scripts/python.exe scripts/probe_build123d_3d_path.py
```

Committed, like the helix probe, because its numbers are the argument and a reader should
be able to disagree with them. The same caution as both earlier investigations:
`Shape.is_valid` is a **property** in build123d 0.11.1 and calling it raises
`TypeError: 'bool' object is not callable`, which reads like a geometry failure and is
not.
