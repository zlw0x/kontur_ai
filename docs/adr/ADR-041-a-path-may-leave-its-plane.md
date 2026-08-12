# ADR-041: CAD-IR 1.15 — a path may leave its plane, and a solid may not pass through itself

**Date:** 2026-08-12 · **Status:** accepted ·
**Investigation:** `docs/TASK-POSTMVP-P4-3-a-path-that-leaves-its-plane.md` ·
**Probe:** `scripts/probe_build123d_3d_path.py`

## What was believed

`docs/GATE-P4-ANALYSIS.md`:

> | P4.3 3D curves | out | a new coordinate vocabulary in CAD-IR; the largest single
> piece of P4 |

One wall, five items behind it. Measured, it is **five different questions**, and only
one of them is about coordinates. This is the fourth time in this repository that a wall
turned out lower than the document describing it (ADR-032, `until_face`, ADR-040), and
the fourth time the way through was to ask the kernel rather than re-read the table.

## Decision

### 1. A spatial path — one number per point

```
{ id, plane, segments: [ {line3: start,end} | {arc3: start,end,center} ] }
```

`plane` is the frame the coordinates are stated in and nothing more; the path no longer
lies in it. Every other rule is 1.9's, unchanged: the path starts at that plane's origin
(ADR-031), it is open, it is tangent-continuous, and it leaves the profile at a right
angle. The engine's checks are the planar ones with a third component.

**Why that is enough is Pappus.** For a tube whose section's centroid rides the path, the
volume element is `(1 − uκ) du dv ds`, so the correction is the section's first moment
about the path — zero. Torsion, the whole difference between a spatial path and a planar
one, **drops out of the volume**:

```text
circle 5, the 3D run                12003.3857   7/11/6   valid   Pappus 12003.3857   diff 1.819e-12
circle 5, the same run kept planar  12003.3857   7/11/6   valid   Pappus 12003.3857   diff 1.819e-12
```

So a spatial sweep is closed-form and can be a corpus case, which is what promotes an
operation at all. It also means **volume cannot see the third dimension** — the two rows
agree to the digit. What sees it is the bounding box, and documents already state one.

### An arc in space carries no `sweep`, and that is a consequence

A planar `ArcSegment` needs `sweep` because it is shared with sketch contours, where two
arcs share every endpoint and centre and differ only in which way round they go. A
**path** has no such freedom: 1.9 requires it to be tangent-continuous, and of the two
arcs through these points only the shorter one can continue in the direction the path
arrived. Stating it would be a second thing that can disagree.

What that form cannot say is a half turn or more — `start`, `center` and `end` on one
line leaves the arc's plane undecided, and the kernel's answer is
`gp_Dir::Crossed() - result vector has zero norm`, an empty-message construction error of
the kind the draft investigation found escaping as a crash. `SWEEP_PATH_ARC_AMBIGUOUS`
refuses it, and a U-bend is two quarter turns joined tangentially, which is what the
document has to state anyway because 1.9 checks the join.

### The bend check had to grow a memory

The planar version measures the profile's reach once, because a planar path rotates the
section about one fixed axis and every bend's inward direction rotates with it — the two
cancel. A path that leaves its plane has no such luck: by the third bend the section has
been turned by the two before it. So the rotation is accumulated as the path is walked,
one turn about each arc's own binormal, and the inward direction is carried back through
it before the profile is measured. Within a single arc nothing more is needed — section
and inward direction turn about the same binormal by the same angle, so the value at the
arc's start is exact.

### 2. A conical helix, and `pitch` is not what the kernel means by it

```text
cone   0.0 deg  turns 3.00000  z per turn 10.00000
cone  15.0 deg  turns 3.10583  z per turn  9.65926
cone  30.0 deg  turns 3.46410  z per turn  8.66025
```

`z per turn` is `pitch · cos(cone_angle)`: **this kernel measures the pitch along the
cone's slant, and a drawing dimensions it along the axis.** A document stating pitch 10
over height 30 at 30° would get **half a turn too many**, in a spring that is valid,
plausible, and agrees with every closed form computed from the kernel. Nothing
downstream could see it — a turn count is not something this service measures.

This is a new shape of finding. The five before it are the kernel returning a wrong
answer to the right question; this is the kernel answering a **different question with
the same word**. So trusted code divides by `cos(cone_angle)` once, which is the
`until_face` pattern again: *what a division in trusted code buys is a number.* With it
in place the arc length matches its closed form to 3e-10.

`feature.sweep.helix_conical` is exercised by `test_sweeps.py` rather than by the corpus,
and the exemption is listed in `test_corpus.py`. The reason is its **bounding box**, not
its volume: every corpus document states a box, and a tapered spring's is not
`2(r₁ + wire)` — the far side of the coil is a quarter-turn lower and therefore
narrower, so the box is off-centre and its extents depend on where the last turn lands.
That is derivable and it would be the whole of the case.

### 3. `SOLID_PASSES_THROUGH_ITSELF`

A post-check on every swept and lofted solid, and it exists because the probe found the
first failure in this family that **nothing else in the service catches**.

It has to be a spiral, and that is why the gap survived. Two tangent bends of radius R
put the outgoing and returning runs 2R apart, and `SWEEP_BEND_TIGHTER_THAN_PROFILE`
already requires R to clear the profile — so a U-turn's runs can never touch. A path that
comes back alongside a part of itself that is **not its neighbour** can. Four bends of
R35, a section reaching 30, a last run 25 mm from the first:

```text
volume  2643399.9499   valid   Pappus 2643399.9499   diff 4.657e-10
B-rep   1 solid, 1 shell, 11 faces, genus 0
mesh    33764 triangles, 0 open edges, 0 inconsistent normals, genus 0
```

Every check passes. The genus cross-check of POSTMVP-020 — which does catch the
self-intersecting sweep of POSTMVP-018 — agrees with itself here, because this surface
passes through itself *smoothly*: no triangle edge is left unmatched, so the mesh is a
closed manifold and both computations of the genus give 0.

And **that path is planar**, so this is a hole in 1.9 rather than a cost of 1.15. A
spatial path only makes it easier to write by accident, because two views of a bent tube
do not show the clearance between two runs.

`BOPAlgo_ArgumentAnalyzer` with `SelfInterMode` answers it exactly, in milliseconds, with
no false positive on an ordinary part — and catches all three known cases of the family,
including the tight bend and the tight helix.

**It does not replace the closed-form pre-checks**, and the distinction is the one this
repository keeps arriving at: a pre-check refuses with a number the repair loop can read
— "bends at radius 4 while the profile reaches 8 towards the centre of that bend" — and
this one can say only that it happens somewhere. The pre-checks name the mistake; this is
the backstop for what no closed form covers.

## What is refused, and it is refused rather than merely unbuilt

**A 3D spline.** Four points, and the kernel gives three different curves depending on a
parameterization the document does not carry (111.5688 / 113.2632 / 113.0538); the curve
leaves the box its own points define, reaching z = 24.974 where the highest stated point
is 20; and its swept volume agrees with Pappus to 1e-3 rather than 1e-12, against a
length that is not a closed form at all. A document whose part is not determined by its
own numbers defeats ADR-018's trade in a way no canonicalization repairs, and gives the
corpus nothing to state.

**An intersection or projected curve.** It is `until` under another name (ADR-039): a
number in the part that no document states and no expectation can check — and unlike
`until_face` there is no division in trusted code that reproduces it.

**Imported points.** The part would depend on bytes the document does not contain.
ADR-018 and boundary 5 of this project both apply, and they apply at once.

## The regression this found in ADR-040

CAD-IR 1.14 spliced `feature.sweep.helix` into the middle of the `elif` chain that
decides what a feature is, which broke the chain in two. Both consequences were silent: a
**helical cut** required `feature.sweep.helix` and then never reached `need(CUT_SWEEP)`,
so an operator who had switched swept cuts off would still have got one; and a plain
solid sweep stopped counting towards `solids_so_far`, so a boss landing on a swept body
no longer asked for `feature.boss.additive`.

Neither was visible to the corpus, because the one helical case it carries is a solid
sweep standing alone. The path kinds are now decided in their own block beside the other
per-input keys, and `test_capabilities.py` parametrises over both kinds of feature and
all three kinds of path — one example per type is what let the second one through in the
`ClaimLoop.Typed` defect, and it is the same lesson.

## What P4.3 leaves behind

A general 3D spline, and the guide curves and orientation modes of P4.1/P4.2 that would
have used one. Those are no longer blocked on a coordinate vocabulary — 1.15 has one.
They are blocked on ADR-029's three walls like everything else, plus the one this
investigation adds: **a curve the document does not determine is not a curve this service
can deliver.**

**The cycle cannot ask for a spatial path.** Points a reading stage would have to lift
off two views and reconcile, which is squarely ADR-029's vision wall. Like the shell,
like `until_face` and like the helix, it arrives as an operation the corpus builds and
the drawing cycle cannot yet reach.
