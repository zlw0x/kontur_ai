# ADR-040: CAD-IR 1.14 — a sweep may follow a helix

**Date:** 2026-08-10 · **Status:** accepted ·
**Investigation:** `docs/TASK-POSTMVP-P4-3-a-helix-is-not-a-3d-curve.md` ·
**Probe:** `scripts/probe_build123d_helix.py`

## What was believed

`docs/GATE-P4-ANALYSIS.md` put the whole of P4.4 behind P4.3:

> | P4.3 3D curves | out | a new coordinate vocabulary in CAD-IR; the largest single
> piece of P4 |
> | P4.4 templates (spring, auger, helical groove, real thread) | out | all four need a
> helix, so all four need P4.3 |

That sentence was inherited rather than measured. The probe says a helix is `pitch`,
`height`, `radius`, a hand and an axis — **five numbers and a direction, not one of
them a point in space** — and CAD-IR states every one of them already.

This is the third time a wall in this repository turned out to be lower than the
document describing it. ADR-032 was the first, `until_face` the second, and all three
were found the same way: by asking the kernel instead of re-reading the table.

## Decision

A second path kind beside the planar chain of lines and arcs:

```
{ id, plane, pitch, height, radius, hand }
```

The **plane's normal is the axis** and its x direction is where the first turn
starts, which is build123d's own convention and the same move `SweepPath` already
makes — a path says which plane it is drawn on and the plane supplies the frame.

### No discriminator field, and that is not laziness

`SweepPath` and `HelicalPath` have disjoint required properties and both forbid
extras, so exactly one of them validates any payload: the spelling is unique without
a tag. A required `kind` would have been tidier to read and would have invalidated
every document written before 1.14 the moment the normalizer relabelled it — and the
normalizer is **relabel-only** by design (`MIGRATABLE_VERSIONS` derives
`RELABEL_ONLY`). A tag that breaks every migration to buy legibility is a bad trade.

### `hand` is required

Every other property of a part in this contract can be checked against the built
solid. This one cannot. Measured:

```text
lefthand=True    594.8702 mm³   3/3/2   valid
lefthand=False   594.8702 mm³   3/3/2   valid
```

Same volume, same topology, same bounding box — they are mirror images, so nothing
this service measures can tell them apart. A default would have made the one
uncheckable property the one a document is allowed to leave out. It has to be read
off the drawing, and only a person can catch it being wrong.

### The section's plane comes from the path, not from the document

`SketchOnPathStart` — `{"on": "path_start"}` — is new, and it exists because a helix
removes a freedom the planar path has.

For a planar path the profile's plane is a real choice the drawing shows, so 1.9 makes
the document state it and the engine checks that it is perpendicular. A helix's
tangent at its start leans by the lead angle `atan(pitch / 2πr)`, so there is exactly
**one** plane the section may stand on and the path has already stated the numbers
that fix it. Stating it again would be a second place for one truth to live.

That matters because getting it wrong is not a small error:

```text
section on the path's normal    4752.3867 mm³
section left on its own plane    376.9902 mm³   one valid solid, no error
```

An order of magnitude. The kernel sweeps the section's *projection* — the same
mechanism ADR-031 measured on a 45° path, made dramatic by a helix's lean.

### `HELIX_PITCH_TIGHTER_THAN_SECTION`

The one new refusal, and the fifth instance of ADR-033's rule.

```text
pitch 10.0  (turns touch at 4.0)   3168.2583   valid   Pappus agrees
pitch  4.0                         3159.8737   valid   Pappus agrees
pitch  2.0                         3158.6740   valid   Pappus agrees
```

A 2 mm wire on a 2 mm pitch overlaps its neighbour by half a diameter. The kernel
returns one solid, calls it valid, and its volume **matches Pappus** — because the
material counted twice is exactly the material the formula counts twice. Volume is
blind to it.

The genus cross-check of POSTMVP-020 does catch it afterwards, by disagreeing with
itself across two exporters. But the condition is closed-form and knowable
beforehand — turns touch when the section's extent along the axis reaches the pitch —
so it is refused with a number in it, the way `SWEEP_BEND_TIGHTER_THAN_PROFILE` is. A
refusal a repair loop can read beats a genus that came out wrong.

## What it is measured by

`helix-spring` in the golden corpus: a 2 mm wire on a Ø40 helix of 10 mm pitch over
30 mm, volume by Pappus over a path length of `(height/pitch)·√((2πr)² + pitch²)`,
matched on the real kernel. Its topology is `3/3/2` — a helix is **one edge** however
many turns it has, so a helical sweep is the `n = 1` row of the sweep table
`GATE-P4-ANALYSIS.md` already derived.

`helix-pitch-tighter-than-its-wire` is the negative, carrying the code it must fail
with.

`feature.sweep.helix` is declared **`experimental`**: the corpus rule promotes an
operation by cases, and this has the one written here.

## What it unblocks, and what it does not

A spring, an auger and a helical groove are now expressible, and so is a **profiled
thread** — a V or a trapezoid swept along a helix, which is a contour CAD-IR already
spells out. Three of P4.4's four templates.

**P4.3 is unchanged.** A general 3D spline still needs a coordinate vocabulary and is
still the largest single piece of the stage. What moved is what was queued behind it.

**Whether a thread should be modelled at all is not decided here.** POSTMVP-011 found
that what the contract lacks is a thread *callout* — a manufacturing note — rather
than geometry, and a modelled thread is expensive to build, slow to mesh and rarely
what a customer wants in a STEP file. This makes it possible; that is not the same as
right.

**The cycle cannot ask for it.** Five numbers a reading stage would have to lift off a
drawing, behind ADR-029's same three walls. Like the shell and like `until_face`, it
arrives as an operation the corpus builds and the drawing cycle cannot yet reach.
