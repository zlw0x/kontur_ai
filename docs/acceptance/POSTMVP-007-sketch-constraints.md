# POSTMVP-007: sketch constraints acceptance

**Date:** 2026-07-30 · **Result:** PASS for constraints and driving dimensions,
with two parts of the milestone explicitly not done and recorded below.

No new geometry. The milestone makes the delivered model editable and makes a
misread drawing catchable.

## What was run

`tests/fixtures/cad-ir/constrained-plate.v1_3.json`, through the real adapter on
live KOMPAS v22:

```bash
dotnet run --project apps/local-worker -- run-job .local/acceptance-007
```

A 60 × 30 × 8 plate, its outline spelled out as four named edges, two Ø8 holes,
two construction axes, **ten constraints** and **three driving dimensions**:

| Constraint | Kind |
|---|---|
| `c.top_horizontal`, `c.bottom_horizontal` | horizontal |
| `c.left_vertical`, `c.right_vertical` | vertical |
| `c.sides_equal`, `c.spans_equal` | equal length |
| `c.holes_equal` | equal radius |
| `c.holes_symmetric` | symmetric about `axis.vertical` |
| `c.holes_aligned` | horizontally aligned points |
| `c.corner_bottom_left` | coincident, `edge.left.start` to `edge.bottom.end` |

Dimensions: `base_width` 60, `base_height` 30, `hole_radius` 4 — the stable names
the roadmap asks for.

## Result

```text
status COMPLETED · 1 body · 372 triangles
M3D 61 581 B · STEP · STL
```

| Check | Result |
|---|---|
| `solid_body_count` | expected 1, measured 1 |
| `bounding_box` | expected [60, 30, 8], measured [60, 30, 8] |
| `through_hole_count` | expected 2, topology-derived genus 2 |
| `closed_manifold_mesh` | 0 edges without exactly two incident triangles |

Exact, not within tolerance — the geometry was never solved for, so there is
nothing for the kernel to have rounded.

### The delivered model is parametric

Read back out of the saved M3D, in a fresh KOMPAS process:

```text
variables in the delivered sketch: 3
  base_width = 60.0
  base_height = 30.0
  hole_radius = 4.0
```

The same words appear in the document, in the file the customer receives, and in
any later diff. That is what the milestone was for.

### A misread drawing is refused before COM

Adding one constraint that the coordinates contradict — the top edge declared
parallel to the left one:

```text
CONSTRAINT_NOT_SATISFIED: Constraint c.misread states edge.top parallel
edge.left, and the coordinates the document gives do not. A constraint is a
statement about the geometry, not an instruction to change it.
```

Zero KOMPAS processes started. This is the class of error the milestone exists to
catch: an extraction that says two edges are parallel while the coordinates it
also extracted say otherwise has misread one of the two, and nothing could tell
before.

## Defects the real run found

**A construction line was invisible to constraints.** The axis of the symmetry
resolved to nothing, because the name override applied only to circular
construction entities and a construction line is a one-segment path. Caught by
the first run, on `c.holes_symmetric`.

**A dimension must be updated before it can be associated.** Without
`IDrawingObject.Update()`, `Associate()` returns false — which reads like a
refusal rather than an unfinished object, and cost a run to distinguish.

**`IView.Variables` works for exactly one dimension and then stops.** It answers
with a single variable object when there is one and with something else when
there are several, so the second dimension threw a cast failure that surfaced as
a generic `SKETCH_INVALID`. Narrowed by feature flag — turning
`sketch.driving_dimensions` off proved the constraints were fine — and then by
running each dimension kind alone. The fix is `Variable(name)`: the index is a
VARIANT and takes a name, which is the only unambiguous handle.

That third one is worth noting as the first time the feature flags paid for
themselves: bisecting a COM failure by turning half of it off took one command.

## What is not done

**Point constraints are verified but not applied.**
`IParametriticConstraint` carries `Index` and `PartnerIndex`, and which values
select which endpoint is unmeasured. Applying `coincident` with the defaults would
pin whichever pair KOMPAS chose — for a corner of a contour, the wrong pair — so
the delivered model would carry a constraint the document did not state.

Six kinds are affected: coincident, midpoint, point-on-curve, both alignments,
and collinear. All six are still *checked* against the coordinates, which is
where the value is; they simply do not travel into the file. The acceptance part
has one of each side of that line, so the run exercises both paths.

**No driving dimension actually drives.** The variable reports what KOMPAS
measured, which is what the confirmatory design needs, and setting it does not
move the geometry. Four ways of trying are recorded in
`docs/TASK-POSTMVP-007-sketch-constraints.md`. This is a limit of what was
established, not a limit of the design: the document carries the coordinates, so
nothing needs the solver to be authoritative — but a customer editing the
delivered file in the KOMPAS UI can drive it there.

**Angular dimensions do not exist.** `IAngleDimensions.Add` answers with nothing
for every type tried, so the vocabulary has length, radius and diameter only.

**Degrees of freedom are reported, never enforced.** A document with explicit
coordinates is normally under-constrained and that is correct.

## Reproducing

```bash
python -m pytest -q
dotnet test CadAi.sln --nologo
```

```bash
dotnet run --project apps/local-worker -- run-job .local/acceptance-007
```

The last needs KOMPAS v22 and `tests/fixtures/cad-ir/constrained-plate.v1_3.json`
copied in as `cad-ir.json`.
