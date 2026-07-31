# POSTMVP-010: patterns and mirror — acceptance

**Date:** 2026-07-31 · **Result:** PASS, declared `experimental`.

Design decisions in `docs/adr/ADR-027-*`. What follows is what was run.

## What was run

`tests/fixtures/cad-ir/patterned-flange.v1_6.json`, through the real engine's real
command line. A 120 × 80 × 8 plate carrying **twelve openings written as three cuts and
four patterns**:

| | how the document says it | instances |
|---|---|---|
| mounting holes | one Ø8 cut, a linear pattern of 2 across, a linear pattern of that 2 along | 4 |
| bolt circle | one Ø6 cut, a circular pattern about `axis.z` at 60° | 6 |
| slots | one slot, mirrored about YZ | 2 |

```text
status COMPLETED · verified true
STEP 83 122 B · STL 108 384 B · 6 124 triangles
1 solid · 24 faces: 10 planar, 14 cylindrical
```

### The volume is arithmetic from the drawing

| | mm³ |
|---|---|
| 120 × 80 × 8 | 76 800 |
| − 4 × π × 4² × 8 — four Ø8 mounting holes | −1 608.4954 |
| − 6 × π × 3² × 8 — six Ø6 bolt holes | −1 357.1680 |
| − 2 × (π × 5² + 2 × 5 × 20) × 8 — two mirrored slots | −4 456.6371 |
| **expected** | **69 377.6995** |
| **measured** | **69 377.6995** |

### Every count checked independently

```text
solid_body_count expected 1, measured 1
surface_face_count[inv_mount_holes] expected 4 cylindrical faces of radius 4.0, measured 4
surface_face_count[inv_bolt_holes]  expected 6 cylindrical faces of radius 3.0, measured 6
surface_face_count[inv_slot_ends]   expected 4 cylindrical faces of radius 5.0, measured 4
bounding_box expected [120, 80, 8], measured [120, 80, 8]
through_hole_count expected 12, mesh-derived genus 12
closed_manifold_mesh 0 open edges · consistent_normals 0
mesh_matches_solid the mesh sits 0.0000 mm inside and 0.0000 mm outside
```

Where the instances actually went, measured rather than assumed:

- the grid: exactly `(±50, ±30)`, from two counts of two
- the bolt circle: six faces each 25.000000 mm from the axis, at 0/60/120/180/240/300°
- the mirror: slot end caps at x = −45 and x = +45, the original kept
- `skip: [3]`: five holes at 0/60/120/240/300° — the gap where the document said

## The failure only the shape claim can see

**Twelve instances 60° apart is six holes drilled twice.** The part is identical to the
correct one, so every measurement agrees with a document that asked for twice as many
holes as the drawing shows:

```text
volume 69 377.6995 · 6 cylindrical faces of radius 3 · genus 12 · report valid
```

The shape claim compares *stated* counts, and it is the only thing that notices:

```text
OPENING_COUNT  claimed 10 round · built 16 round
```

This is the clearest case so far for why a claim exists at all (ADR-025), and it is a
pattern-shaped failure: no earlier operation could be wrong in a way that leaves the
geometry right.

## What it refuses

| | where | code |
|---|---|---|
| a pattern of one | contract | count ≥ 2 |
| zero or negative spacing, a 0° or 360° step | contract, and again in the engine when a parameter resolves to it | `DIMENSION_OUT_OF_RANGE` |
| skipping instance 0 | contract | the original is the source's own position |
| skipping every repeat | contract | "repeats nothing" |
| skipping an instance beyond the count | contract | |
| a mirror with `skip` | contract | one reflection, nothing to skip |
| a pattern that produces a result | contract | `produces` is empty |
| a pattern of a feature nobody declared | validator | `FEATURE_DEPENDENCY_MISSING` |
| a pattern that does not depend on what it repeats | validator | `FEATURE_DEPENDENCY_MISSING` |
| a pattern of a **disabled** feature | validator | `FEATURE_DISABLED_SOURCE` |
| a pattern of a datum plane | validator | `UNSUPPORTED_FEATURE_SET` |
| a mirror about a datum plane | engine | `UNSUPPORTED_FEATURE`, "not built yet" |
| a pattern with nothing built yet | engine | `UNSUPPORTED_FEATURE_SET` |

A pattern of a disabled source is worth singling out. It **builds**: five instances land
at offsets from a position nothing occupies, and the result is a part with five holes
where the drawing shows six. Refusing it needs nothing but reading the document, so it is
refused there.

## A defect this found in the selector layer

`topology.py` filled a descriptor's `centroid` from build123d's `center()`, whose default
is `CenterOf.GEOMETRY` — the middle of the surface's own parameter domain. For a planar
face that is the centroid. For anything curved it is a point **on** the surface:

```text
a Ø8 hole centred at x = -50 read as x = -54
the circular edge round its mouth read as x = -54 too
```

Nothing failed, which is what made it worth finding: a document selecting "the face
centred on x = −50" did not match it, and one selecting x = −54 matched something no
drawing describes. Now the centre of mass, with a regression test in
`test_selectors.py`.

Found because a pattern test asked a descriptor *where* an instance went — the first
thing in the codebase to want a curved face's position rather than its extreme.

## Tests

| Suite | Count |
|---|---|
| `packages/build123d-adapter/tests/test_patterns.py` | 13 |
| `apps/api/tests/test_cad_ir_pattern.py` | 26 |
| `packages/build123d-adapter/tests/test_selectors.py` | 16 |

Full runs: `588 passed, 1 skipped` (Python), `6 + 30 + 31 + 39` (.NET), schemas
generated-and-checked, OpenAPI compatibility valid.

## Not done, and why

**Declared `experimental`.** Unlike the blends, what stands between a pattern and `beta`
is not a missing vocabulary — a shape claim can already carry "six round openings", so
the reading stage has something to say and something to check. What is missing is the
corpus the roadmap asks for (POSTMVP-013) and an output profile that offers the
operation.

**A pattern along a curve** (P2.5) needs a curve in the document that nothing else has a
use for yet.

**A mirror about a datum plane** is refused rather than half-supported. A mirror about
the wrong plane is a part nobody can tell apart from the right one by reading the
document.

**A grid has no `kind` of its own**, by design: it is a linear pattern of a linear
pattern, and the fixture builds one that way.
