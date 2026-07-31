# ENGINE-MIG-006: revolve acceptance

**Date:** 2026-07-31 · **Result:** PASS. One new fixture, thirty-three new tests,
and one defect the first real fixture found that a unit test would not have.

The second half of ENGINE-MIG-006, and the first operation this service has that
never existed on KOMPAS. POSTMVP-008 was deliberately not built there (ADR-023);
it lands here instead, on a documented kernel call rather than on measured COM
constants. The design decisions are ADR-024.

There is no earlier run to compare against, so nothing in this record is a
transcription. Every expected number is arithmetic from the drawing: a revolved
annulus is π(R² − r²)h, and a partial one is that times the fraction of a turn.

## What was built

`tests/fixtures/cad-ir/bushing.v1_4.json` — a flanged bushing with a turned
external groove, through the real engine:

```bash
python -m cad_worker build --job .local/acceptance-revolve
```

| Feature | Exercises |
|---|---|
| `feature.bush` — the flanged section, 360° | `solid.revolve`, a six-segment `path` profile, axis named as a **construction line** |
| `feature.groove` — a relief groove, 360° | `cut.revolve`, axis stated as **two points**, `source_body` naming the body it cuts |

Both axis spellings in one document, and both feature types. The profile is drawn
in the XZ plane with u as radius and v as height, which is how a turned part is
dimensioned on a drawing.

## Result

```text
status COMPLETED · 1 body · 10 faces (5 planar, 5 cylindrical) · 15 edges
STEP 20 634 B · STL 126 084 B · genus 1
```

| Measurement | Built | What the drawing says |
|---|---|---|
| Volume | 10 005.9726 mm³ | π(18²−8²)·5 + π(12²−8²)·25 − π(12²−11²)·5 = 10 005.9726 |
| Bounding box | 36 × 36 × 30 | Ø36 flange, 30 tall |
| Face at z = 0 | 816.814 mm² | π(18²−8²) — the flange face |
| Face at z = 5 | 565.487 mm² | π(18²−12²) — the shoulder |
| Faces at z = 15, 20 | 72.257 mm² each | π(12²−11²) — the groove walls |
| Face at z = 30 | 251.327 mm² | π(12²−8²) — the top |

The volume agrees to four decimal places, which is the check no face count can
fake: a cut applied to the wrong side of the wall, or a sweep that went the wrong
way round, produces the right faces in the right places and the wrong solid.

Every check the independent verifier makes passes, and `through_hole_count` is
derived from the mesh's genus rather than from the document that asked for it.

### How far round

A plain tube, swept four different amounts, so the volume is a fraction of a turn
and nothing else:

| Angle | Built | π(12²−8²)·30 × angle/360 |
|---|---|---|
| 90° | 1 884.956 mm³ | 1 884.956 |
| 180° | 3 769.911 mm³ | 3 769.911 |
| 270° | 5 654.867 mm³ | 5 654.867 |
| 360° | 7 539.822 mm³ | 7 539.822 |

`both_directions` is checked twice over: the volume equals the one-way sweep, so
it did not sweep twice; and the solid reaches as far to −Y as to +Y, so it went
both ways rather than one way with an offset.

## The defect the arithmetic found

**The axis was read as literal numbers.** A sketch coordinate in CAD-IR is a
*scalar* — a number or a parameter reference — and the first version of
`axis_points` called `float()` on it. The bushing's centre line ends at
`{"parameter": "bush_height"}`, which is exactly what a parametric centre line
looks like, so the first real fixture failed on a `TypeError` before any geometry
was made.

Caught by the fixture rather than by a unit test, because a unit test written
alongside the code would have used the same literal coordinates the code assumed.
The axis now resolves through the same `Parameters` table as every other
coordinate, and `test_an_axis_may_be_parametric_like_any_other_coordinate` holds
it there.

## What the engine refuses, and why it has to

A profile that crosses its axis sweeps through itself. Measured before deciding
what to do about it: every crossing profile tried — symmetric and offset, a full
turn and a quarter — comes back from OpenCascade as

```text
StdFail_NotDone: BRep_API: command not done
```

raised from inside the kernel with no code, no stage, and nothing about the
document. The worker catches `CadEngineError` and reports a typed `FAILED`; this
escapes as an unhandled crash with no JSON at all. So the kernel does refuse, and
its refusal is unusable.

`REVOLVE_PROFILE_CROSSES_AXIS` is raised first, at stage `feature`, naming the
feature. It samples the profile's boundary rather than reading segment endpoints,
because an arc can begin and end on one side of the axis and bulge across it in
the middle — a case in the suite, and one a check on endpoints alone would pass.

Removing the check turns exactly those two tests from typed refusals into kernel
crashes, which is the demonstration that the check is what is doing the work.

The side of the axis a point falls on comes from a cross product, which scales
with the axis's length; it is divided by that length so the tolerance is a
distance in millimetres. Without the division the same profile would pass or fail
depending on how long a line the drawing happened to draw its centre line as — a
centre line is a line, and its length says nothing. Checked at three lengths a
million apart.

The other refusals, each with a test:

| Code | When |
|---|---|
| `REVOLVE_PROFILE_CROSSES_AXIS` | the profile lies on both sides of its axis |
| `REVOLVE_AXIS_INVALID` | two points that coincide once their parameters resolve |
| `DIMENSION_OUT_OF_RANGE` | an angle outside 0 < θ ≤ 360, named by a parameter so the contract could not see it |
| `UNSUPPORTED_FEATURE_SET` | a `cut.revolve` with nothing built for it to cut |

Touching the axis is allowed, and a solid Ø24 shaft drawn from the centre line
outwards builds to π·12²·30 exactly.

## The contract

CAD-IR is **1.4**. The addition is additive — a 1.4 document that does not revolve
is a 1.3 document — so the migration is a relabelling and the four existing
fixtures moved over with only their version string changed.

Refused by the contract, before any engine sees the document: an axis of two
identical points; an axis naming a segment of the profile, or a name that resolves
to nothing, or a construction circle; an angle of 0, a negative angle, or more
than a full turn; and a full turn declared `both_directions`.

The KOMPAS adapter consumes 1.4 and refuses `solid.revolve` by feature type. It
cannot build one and never will, but refusing every 1.4 document over an operation
the document does not use would strand the only working engine for no reason.
`WorkerCapabilities` still does not declare revolve, and a test still asserts it
does not — so the API will not schedule a revolve to a KOMPAS worker.

## What is not claimed

- **Revolve is not offered to Codex.** The output profile is unchanged. The
  drawing agent reads a rectangle and round holes; a turned profile and its centre
  line are not something it can extract, and offering the operation would invite a
  model to invent one.
- **Revolve is not behind a per-operation feature flag.** ADR-021 requires one and
  the requirement is not waived — the build123d worker has no flag surface yet,
  because flags, the capability manifest and the claim protocol belong to
  ENGINE-MIG-007. Until then this operation cannot be rolled back without a
  release. Recorded here as a debt, not as a decision.
- **No thin revolve and no up-to-face.** Both are in the roadmap's P2.2 and
  neither is built. Each will arrive with its own fixture.
- **This ran on Linux, not on the trusted Windows machine.** That is the point of
  ADR-023: there is no licence, no GUI and no COM in this path, so the acceptance
  run and CI are the same run.
