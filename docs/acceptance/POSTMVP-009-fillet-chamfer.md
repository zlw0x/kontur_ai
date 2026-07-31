# POSTMVP-009: fillet and chamfer — acceptance

**Date:** 2026-07-31 · **Result:** PASS, with the operations declared
`experimental` and the reason recorded below.

The first operations that build nothing. The design decisions are
`docs/adr/ADR-026-*`; what follows is what was run.

## What was run

`tests/fixtures/cad-ir/blended-bracket.v1_5.json`, through the real engine's real
command line:

```bash
python -m cad_worker build --job <job>
```

A 60 × 40 × 10 plate with a Ø10 bore, **four R6 corner fillets**, a **2 mm
equal-distance chamfer** on the bottom rim of the bore and a **1.5 × 3 asymmetric
countersink** on its mouth, measured from the top face the document names.

```text
status COMPLETED · verified true
STEP 40 449 B · STL 108 384 B · 2 166 triangles
1 solid · 13 faces: 6 planar, 5 cylindrical, 2 conical
```

### The volume is arithmetic from the drawing

Not from a previous run, and not from this engine:

| | mm³ |
|---|---|
| 60 × 40 × 10 | 24 000 |
| − 4 × (1 − π/4) × 6² × 10 — four R6 corners | −309.0266 |
| − π × 5² × 10 — the Ø10 bore | −785.3982 |
| − π × 24.75 — the countersink | −77.7544 |
| − π × 68/3 — the 2 mm deburr | −71.2094 |
| **expected** | **22 756.6114** |
| **measured** | **22 756.6113** |

### Every check in the report

```text
step_readable · step_has_solid · step_shape_valid · positive_volume
no_degenerate_solids · solid_body_count expected 1, measured 1
surface_face_count[inv_corner_fillets] expected 4 cylindrical faces of radius 6.0, measured 4
surface_face_count[inv_bore_chamfers]  expected 2 conical faces, measured 2
bounding_box expected [60, 40, 10], measured [60, 40, 10]
stl_structure · stl_triangle_count · finite_non_degenerate_triangles
closed_manifold_mesh 0 open edges · consistent_normals 0
through_hole_count expected 1, mesh-derived genus 1
mesh_matches_solid the mesh sits 0.0000 mm inside and 0.0000 mm outside
```

### The blend is the one thing the old checks could not see

Turning the fillet off — a legitimate document, since a disabled feature is a
document saying "not this one" (ADR-021) — leaves a plate with square corners whose
bounding box, body count and hole count are **all still exactly what the document
declares**. One check fails:

```text
surface_face_count[inv_corner_fillets]: expected 4 cylindrical faces of radius 6.0, measured 0
```

The same with the radius changed from 6 to 4: every other check passes, and that one
fails. This is the reason a fourth expectation type was worth adding rather than
reusing what was there.

### Convexity, measured against known geometry

The lever plate has all four answers at once, which is why it is the fixture this
was checked on rather than a box:

| | count | what they are |
|---|---|---|
| concave | 7 | six roots under the hexagonal hub, one under the pin |
| tangent | 4 | where the stadium's end caps meet its straight sides |
| none | 3 | the seams |
| convex | 25 | everything outside, **including both hole rims** |

A hole rim being convex is the only surprise and it is right: it is a sharp outside
corner, which is why chamfering one makes a countersink. The predicate was in the
contract since ADR-019 and the resolver ignored it until now — a selector stating
`convexity` was matching on its other clauses and quietly taking both kinds.

### The asymmetric chamfer is measured from the face the document names

1.5 mm across the top face and 3 mm down the bore, not the other way round: the
countersink's cone measures Ø13 at the mouth and 3 mm deep. Taken the other way
round it would be Ø16 and three times as deep, and both are valid solids — only the
document says which one the drawing meant.

Checked a second way, against itself: a 45° chamfer measured 3 mm across the face is
the same cone as 3 mm and 3 mm, and the two spellings reach different kernel
arguments. Equal volumes to 1e-6.

## What it refuses

| | code |
|---|---|
| a selector that could match no edges (`all`, `zero_or_one`, `exactly_n: 0`) | refused by the contract, before a document exists |
| a 25 mm round on a 40 mm plate | `BLEND_FAILED`, carrying the kernel's own reason |
| a negative radius resolved from a parameter | `DIMENSION_OUT_OF_RANGE` |
| four edges matched where the document said three | `SELECTOR_AMBIGUOUS` |
| a predicate that eliminated everything | `SELECTOR_NO_MATCH`, with the narrowing |
| `produced_by`, which this kernel cannot answer | `SELECTOR_UNSUPPORTED_PREDICATE` |
| a document asking for the bore's straight edge — a seam | `SELECTOR_NO_MATCH` |
| an asymmetric chamfer with no `measured_from` | refused by the contract |
| a reference face that does not contain the edges | `SELECTOR_NO_MATCH`, naming the selector |
| a blend with the base extrusion disabled | `UNSUPPORTED_FEATURE_SET` |
| a selector naming a body no feature produces | `FEATURE_RESULT_UNAVAILABLE` |

The narrowing is worth quoting, because it is what a repair agent reads:

```text
Narrowing: not a seam 27 -> 26; curve_type 26 -> 10; convexity 10 -> 10;
radius_mm 10 -> 10; minimum position on z 10 -> 5
```

## Tests

| Suite | Count |
|---|---|
| `packages/build123d-adapter/tests/test_blends.py` | 16 |
| `apps/api/tests/test_cad_ir_blend.py` | 24 |
| `packages/build123d-adapter/tests/test_capabilities.py` | 24 |

Full runs: `545 passed, 1 skipped` (Python), `6 + 31 + 30 + 39` (.NET), schemas
generated-and-checked, OpenAPI compatibility valid, web typecheck clean.

## A kernel behaviour worth writing down

**Chamfering an edge that ends at a fillet makes OpenCascade add a conical
transition face at each such corner.** The first version of the fixture chamfered
the four top edges of the plate and came back with five cones where the document
expected one: four transitions plus the countersink.

They are correct geometry. What they mean is that a face-count expectation on such a
part would have to know a kernel detail no drawing states, so the fixture was
reshaped to put the chamfers on the bore — where nothing transitions — rather than
the expectation being widened to accommodate it. Recorded here because the next
operation to meet it will be patterns.

## Not done, and why

**Both operations are `experimental`**, which the API reads as not leasable at all.
The service cannot currently produce a document that uses them: a shape claim has no
word for a rounded corner (ADR-025), so the reading stage cannot state one and there
would be nothing to check the blend against. The output profile does not offer them
either, and for a second independent reason — the Codex dialect forces every property
of an object to be required, and an edge selector's predicates are individually
optional.

Both are the same gap the revolve has had since ENGINE-MIG-006, and it is a vision
problem rather than a geometry one.

**Tangent chains** (P2.4) are left out deliberately, not deferred for time. A chain
is the document naming one edge and the kernel deciding how many it meant, which is
the inference every rule in ADR-026 exists to prevent.

**Two-distance and distance-angle chamfers are in**, both requiring a reference
face. What is not in is a chamfer whose two distances are measured from *different*
faces per edge, because one selector names one face.
