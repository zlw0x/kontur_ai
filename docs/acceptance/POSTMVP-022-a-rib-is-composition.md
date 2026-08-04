# P3.2, the rib: an operation the contract does not need

**Date:** 2026-08-03 · **Result:** no new operation, and `extrude(until=…)` is
worse than the note said rather than better.

The roadmap lists a rib next, with a note that `extrude(until=…)` "fails on the
first attempt". Both halves of that turned out to be wrong, and the probe is
`scripts/probe_build123d_rib.py`, run inside the engine image where build123d
imports.

## `extrude(until=…)` does not fail. It answers.

```text
Until members: ['NEXT', 'LAST', 'PREVIOUS', 'FIRST']

until=Until.NEXT, builder mode : volume 44274.9359, solids 1
until=Until.LAST, builder mode : volume 29440.0000, solids 1
algebra mode, explicit target  : ok
algebra mode, no target        : ValueError: A target object must be provided
```

The L-bracket it started from is **29440.0000 mm³**. So:

- `Until.NEXT` added 14834.94 mm³ — not a rib, a slab, and the number is not
  closed-form from anything. It is whatever the kernel found on the way.
- `Until.LAST` added **nothing at all**, silently, and reported one valid solid.

That second line is the fifth instance of the shape this project keeps meeting:
**the kernel's failure mode is a plausible answer.** A shell with no room returns
the original solid, a sweep round too tight a bend returns a self-intersecting
one, a draft past the closing point returns a stump — and now an extrusion told to
stop at the last face stops before it starts. Each reports success.

The only thing that actually failed is a missing `target` in algebra mode, and it
failed loudly with a clear message, which is the one case needing no help.

## But the deeper objection is that a rib should not ask

`until` answers a question **the drawing has already answered**. A rib on a
drawing is dimensioned: a thickness and a reach, or a thickness and an angle. Ask
the kernel where to stop and the number that ends up in the part is one no
document states, no parameter carries and no expectation can check — the same
trade POSTMVP-020 refused when it insisted every over-drivable operation compare
its result against what was asked.

So the question for P3.2 is not whether `until` works. It is whether a rib needs
it.

## It does not: CAD-IR 1.10 builds one already

A triangle in the corner, given a thickness that spreads either side of the
plane it is drawn on. Every piece of that has been in the contract for a while: a
closed path contour of lines since 1.2, base planes since 1.2, and
`both_directions` since 1.10.

```json
{"id": "feature.rib", "type": "solid.extrude",
 "depends_on": ["feature.wall"],
 "inputs": {
   "sketch": {"id": "sketch.rib", "plane": {"on": "base", "plane": "XZ"},
              "outer": {"type": "path", "segments": [
                {"type": "line", "start": [4.0, 8.0],  "end": [30.0, 8.0]},
                {"type": "line", "start": [30.0, 8.0], "end": [4.0, 34.0]},
                {"type": "line", "start": [4.0, 34.0], "end": [4.0, 8.0]}]}},
   "direction": "+Y",
   "distance": {"parameter": "rib_thickness"},
   "both_directions": true}}
```

The canonical validator accepts it unchanged, and the engine builds it:

| | |
|---|---|
| volume | 60×40×8 + 8×40×32 + 26×26/2×6 = 19200 + 10240 + 2028 = **31468 mm³**, measured **31468.0000** |
| bounding box | expected [60, 40, 40], measured [60, 40, 40] |
| solid_body_count | expected 1, measured 1 |
| through_hole_count | expected 0, genus 0 |
| closed_manifold_mesh | 0 edges without exactly two incident triangles |
| topology_agrees_with_mesh | B-rep genus 0, mesh genus 0 |

Closed-form to four decimal places, and it is the *rib's* term that carries the
information: 2028 mm³ is a 26 × 26 triangle 6 thick and nothing else.

**This is POSTMVP-011's argument again.** That milestone refused `feature.hole`
because a through hole is a `cut.extrude` with `through_all`, a countersink is a
chamfer of the rim, and a second way to say what CAD-IR already says is another
thing to validate. A rib is a closed contour extruded both ways. Adding
`feature.rib` would buy nothing but a new type to check, a new capability key, a
new failure mode and a new line in every prompt.

## The check caught the first attempt, and it was mine

The rib was written running from x = 4 to x = 34 while the base ends at x = 30, so
the wedge hung 4 mm off the end. The build refused:

```text
GEOMETRY_VALIDATION_FAILED
  bounding_box: expected [60.0, 40.0, 40.0], measured [64.0, 40.0, 40.0].
```

Worth recording because it is the expectation doing exactly what it is for, on an
author's arithmetic slip rather than on a kernel fault — and because it is the
failure `until` would have hidden. Told to stop at the next face, the kernel would
have trimmed the rib to the base and returned a part that looked right, with no
number anywhere admitting that the document had asked for something else.

## What is actually missing

Not geometry. The same two walls as everything else:

- **The claim.** `ShapeClaim` has no word for a rib. A bracket with a rib and one
  without agree on the profile, the openings, the solid count and — unless the rib
  reaches the bounding box, which a rib does not — the bounding box too. They
  differ in volume and in face count. `surface_face_count` can see it (14 faces
  here against 10 without), the way it sees a blend, but nothing in the claim
  *states* that a rib was read.
- **Vision.** Whether the reading stage recognises a gusset on a scan, and whether
  it can state the two numbers that dimension one, is not settled by any code
  here. It is the same question runs 7 to 9 answered for blends and a wall, and it
  wants the same treatment: a drawing, a run, and a record.

So P3.2 closes as **no contract change**, with a run owed. The next widening is a
word in the claim, not an operation in the engine.
