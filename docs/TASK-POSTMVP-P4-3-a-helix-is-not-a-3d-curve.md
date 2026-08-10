# P4.3: a helix does not need a 3D curve — the investigation

**Date:** 2026-08-10 · **Status:** investigated, not built. Nothing here changes CAD-IR.
**Probe:** `scripts/probe_build123d_helix.py`, build123d 0.11.1 / OpenCascade 7.9.3.1.1

`docs/GATE-P4-ANALYSIS.md` puts the whole of the rest of stage P4 behind one wall:

> | P4.3 3D curves | out | a new coordinate vocabulary in CAD-IR; the largest single
> piece of P4 |
> | P4.4 templates (spring, auger, helical groove, real thread) | out | all four need a
> helix, so all four need P4.3 |

This investigation was done with the kernel rather than from that table, and it ends
somewhere else: **a helix is describable in five numbers and a direction, none of which
is a point in space.** P4.4 does not need P4.3. It needs one path kind.

That is the same shape of finding as ADR-032's — "the dialect wall was lower than it
looked" — and it arrives the same way, by measuring instead of inheriting a sentence.

## What a helix is, to this kernel

```text
pitch  10.0  turns 1   length   126.0610   closed form   126.0610   diff 2.191e-10   edges 1
pitch  10.0  turns 3   length   378.1829   closed form   378.1829   diff 4.798e-10   edges 1
pitch   4.0  turns 3   length   377.1821   closed form   377.1821   diff 4.813e-10   edges 1
```

`n · √((2πr)² + p²)` — the hypotenuse of the unrolled turn — to ten decimal places. And
**one edge** however many turns it has, which matters because the topology formulas in
`GATE-P4-ANALYSIS.md` count faces per path *segment*: a helical sweep is the `n = 1` row
of a table that already exists.

Swept with a circular section, Pappus holds:

```text
spring, 1 turn    1584.1292   3/3/2   valid   closed form 1584.1288
spring, 2 turns   3168.2583   3/3/2   valid   closed form 3168.2576
spring, 3 turns   4752.3867   3/3/2   valid   closed form 4752.3864
```

So a spring is checkable in closed form, which is the property the corpus needs before
an operation can be promoted at all.

## What the kernel lies about

Two of the three findings are ones this repository already has a rule for. The third is
new and is the reason a pre-check is worth writing.

### The section must be on the path's own normal, and being wrong is silent

```text
section on the path's normal    4752.3867   3/3/2   valid
section left on the XY plane     376.9902   3/3/2   valid
```

An order of magnitude, one valid solid, no error. The kernel sweeps the section's
*projection* onto the plane perpendicular to the path — the same mechanism ADR-031
measured on a 45° path, where a Ø16 tube came back with 1/√2 of the section drawn, here
made dramatic because a helix's tangent leans hard.

**Already refused.** CAD-IR 1.9 requires the path to start at the profile plane's origin
and cross the profile at a right angle. A helical path would inherit that rule unchanged,
and the measurement says how much it is worth: the difference between a spring and a
tenth of one.

### A spring wound tighter than its own wire reports a plausible volume

```text
pitch 10.0  (turns touch at 4.0)   3168.2583   3/3/2   valid   Pappus agrees
pitch  4.0                         3159.8737   3/3/2   valid   Pappus agrees
pitch  3.9                         3159.7947   3/3/2   valid   Pappus agrees
pitch  2.0                         3158.6740   3/3/2   valid   Pappus agrees
```

At pitch 2.0 with a 2 mm wire the turns overlap by half their diameter. The kernel
returns one solid, calls it valid, and its volume **still matches Pappus** — because the
material counted twice is exactly the material the formula counts twice. Nothing in the
volume can see it.

This is the fifth instance of the rule ADR-033 states, and it is the same failure as the
too-tight sweep bend of POSTMVP-018: a self-intersecting solid that reports itself sound.
The genus cross-check from POSTMVP-020 is what catches it — the STL and the STEP disagree
about how many handles the thing has — and that check already runs on every build.

But the condition is **closed-form and knowable before the kernel is asked**:

```text
turns touch when   pitch ≤ 2 · section_radius
```

which is the same shape as `SWEEP_BEND_TIGHTER_THAN_PROFILE`: a bend tighter than the
profile's reach, refused by arithmetic rather than discovered in a mesh. A helical sweep
should carry `HELIX_PITCH_TIGHTER_THAN_SECTION` for the same reason — a refusal with a
number in it is worth more to a repair loop than a genus that came out wrong.

### Handedness is invisible to every number the service measures

```text
lefthand=True    594.8702   3/3/2   valid
lefthand=False   594.8702   3/3/2   valid
```

Identical volume, identical topology. A left-hand thread and a right-hand thread are
mirror images, so no measurement this service takes can tell them apart — not volume, not
the bounding box, not the genus, not the face count.

That is worth stating plainly because it decides something: **handedness cannot be checked
after the fact, so it has to be right in the document.** It is a word the reading stage
would have to lift off the drawing (`LH` beside a thread callout) and carry, and the only
thing that can catch it being wrong is a person. For a threaded part that is the
difference between a fastener that assembles and one that does not.

## What a document would have to say

```text
start   (20.0, 0.0, 0.0)
end     (20.0, -0.0, 30.0)
tangent (0.0, 0.9968, 0.0793)
```

None of that is what a drawing states. What a drawing states is:

```text
pitch, height (or turns), radius, hand, and the axis it winds about
```

Five numbers and a direction. **CAD-IR already has every one of them**: lengths are
parameters, an axis is what `solid.revolve` has named since 1.4 (ADR-024), and hand is an
enum of two values. There is no point in space anywhere in it.

So the shape of the change is a third `SweepPath` kind beside the planar chain of lines
and arcs — not a coordinate vocabulary, not a curve library, and not P4.3:

```
path: { kind: "helix", axis: …, pitch: Scalar, height: Scalar,
        radius: Scalar, hand: "right" | "left" }
```

with the section rule 1.9 already carries, and one new refusal for the pitch.

## What this changes about the plan

`GATE-P4-ANALYSIS.md`'s table says four P4.4 templates are behind P4.3. Measured, three
of the four are behind **a helical path** and nothing else:

| template | what it actually needs |
|---|---|
| spring | a helical sweep of a circular section — closed-form by Pappus |
| auger / helical groove | a helical sweep used as a cut — measured working, 9/21/14 valid |
| **real modelled thread** | a helical sweep of a **profiled** section (a V or a trapezoid), which is a contour CAD-IR already spells out |
| anything on a general 3D spline | genuinely P4.3 |

The groove was measured end to end: a Ø20 cylinder minus a helical tool of 594.87 mm³
removed 281.51 mm³ — less than the tool, because half of it lies outside the blank — and
came back 9/21/14 and valid. The subtraction is well-formed.

**P4.3 remains the wall for a general 3D curve**, and nothing here shortens it. What it
does is take three of the four things that were queued behind it out of the queue.

## What is not decided here

Whether a *thread* should be modelled at all. POSTMVP-011 already found that what is
missing from the contract is a thread **callout** — a manufacturing note — rather than
geometry, and a modelled thread is expensive to build, slow to mesh and rarely what a
customer wants in a STEP file. A helical sweep makes it *possible*; it does not make it
right, and that is a product decision rather than a contract one.

Nor is anything here reachable by the drawing cycle. A helical path is five parameters the
reading stage would have to lift off a drawing, and the same three walls apply as
everywhere else — dialect, claim, vision. Like the shell and like `until_face`, it would
arrive as an operation the corpus builds and the cycle cannot yet ask for.

## Reproducing

```bash
.venv-cad/Scripts/python.exe scripts/probe_build123d_helix.py
```

The probe is committed, unlike P3.2's, because its numbers are the argument and a reader
should be able to disagree with them. One caution repeated from that investigation:
`Shape.is_valid` is a **property** in build123d 0.11.1, not a method, and calling it
raises `TypeError: 'bool' object is not callable` — which looks like a geometry failure
and is not.
