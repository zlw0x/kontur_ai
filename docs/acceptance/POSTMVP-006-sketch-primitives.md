# POSTMVP-006: sketch primitives acceptance

**Date:** 2026-07-30 · **Result:** PASS, after five defects the real run found
and unit tests could not have.

This is the first milestone that widens what the service can build. Before it,
every part was a rectangular plate with round holes; after it, a profile can be
any closed contour of lines and arcs, with islands, on a base plane, an
auxiliary plane, or a face named by a semantic selector.

## What was built

`tests/fixtures/cad-ir/lever-plate.v1_2.json`, through the real adapter on live
KOMPAS v22:

```bash
dotnet run --project apps/local-worker -- run-job .local/acceptance-006
```

| Feature | Exercises |
|---|---|
| `feature.plate` — stadium profile, 8 mm thick | a `path` contour of two lines and two arcs, two circular islands, and construction geometry |
| `feature.hub_plane` — XY offset by 8 mm | `datum.plane.offset` producing a plane another feature sits on |
| `feature.hub` — hexagon, 4 mm | `regular_polygon`, sketched on the auxiliary plane |
| `feature.pin` — Ø8 boss, 3 mm | a sketch plane named by a **POSTMVP-005 selector**: planar, +Z, furthest along Z |

The pin is the first thing in this service to consume a semantic selector. It
had to land on the hexagon's top face, which no document names and no index
could have identified before the hexagon existed.

## Result

```text
status COMPLETED · 1 body · 17 faces (12 planar, 5 cylindrical)
M3D 77 362 B · STEP 26 393 B · STL 152 720 B (836 triangles)
```

Every check the independent verifier makes:

| Check | Result |
|---|---|
| `m3d_nonempty` | 77 362 bytes |
| `step_header` | ISO-10303-21 found |
| `stl_structure` | 836 complete triangles |
| `finite_non_degenerate_triangles` | 0 degenerate |
| `closed_manifold_mesh` | 0 edges without exactly two incident triangles |
| `solid_body_count` | expected 1, measured 1 |
| `bounding_box` | expected [80, 30, 15], measured [79.980, 30, 15] |
| `through_hole_count` | expected 2, topology-derived genus 2 |

### The geometry is right, not merely plausible

Every horizontal face's area, read back from the saved model through API5,
matches what the document asks for to three decimals:

| z | measured area | what it should be |
|---|---|---|
| 0 | 2167.588 mm² | 50 × 30 + π·15² − 2·π·2.5² = 2167.588 |
| 8 | 1907.781 mm² | 2167.588 − hexagon 1.5√3·10² = 1907.781 |
| 12 | 209.542 mm² | 259.808 − π·4² = 209.543 |
| 15 | 50.265 mm² | π·4² = 50.265 |

The face at z = 12 is the hexagon's top with the pin's footprint removed — which
is the selector having resolved correctly, stated as a number rather than as a
claim.

Five cylindrical faces: the two stadium end caps, the two hole walls and the
pin. Twelve planar: bottom, plate top, two straight flanks, six hexagon sides,
hub top and pin top.

## Defects the real run found

Each one built or exported *successfully* while being wrong, which is exactly
why the synthetic tests are silent about them.

**Construction geometry needs the construction style, not just to be drawn
last.** The first run failed at `feature.plate` outright. A centre line drawn at
profile style inside a closed contour makes the extrusion fail. Measured: with a
stray line at style 1 the extrusion fails, and at every style from 2 to 8 it
succeeds — so the style is not decoration, it is what separates profile geometry
from geometry that is merely present. The fixture's centre line is what a real
drawing would have carried, so this would have hit the first customer.

**`IArc.Direction` 0 sweeps anticlockwise; 1 and −1 both sweep clockwise.** The
adapter used 1, so every end cap bulged inward and an 80 mm part came out 61 mm
wide. Measured by extruding a half-disc bounded by its chord and reading which
side of the chord the material landed on — the earlier slot probe could not
discriminate, because a slot with both caps reversed is still a closed contour.

**A base extrusion always makes a new body, whatever it touches.** The hub and
pin arrived as three separate solids stacked on one another: `solid_body_count`
expected 1, measured 5 in the mesh. Measured: a second base extrusion over the
first leaves two bodies at every `OperationResult` value, and only extrusion
type 25 leaves one. The first solid extrusion is now the base and every later
one is a boss.

**One API5 application object per build, not one per use.** With a face selector
in the plan, the build resolved the face and then failed at export. Activating
API5 again while the first instance is serving API7 starts a *second* KOMPAS
process, and that one has no document open. This is the second time the same
defect has been found the hard way — POSTMVP-005 hit it between two topology
reads — so it now has a class of its own with the history written on it.

**The bounding box is measured from a mesh, and a mesh of a curved surface is
inscribed.** With the arcs finally built correctly the part measured 79.898
against an expected 80 at a stated tolerance of 0.05, and failed. Nothing was
wrong with the model: the STL export was configured for a 0.05 mm chord sag, so
each end cap fell 0.051 mm short. Two changes: the comparison is now
asymmetric — short by up to the chord tolerance is the tessellation, wider than
expected is a real dimensional error held to the stated tolerance alone — and
the export sag is tightened to 0.01 mm so the mesh can prove what a drawing
actually asks. A flat-sided prism tessellates exactly, which is why five
milestones went by without this surfacing.

## What this does not prove

**The drawing agent still extracts a rectangle and round holes.** The IR, the
validator and the adapter handle much more, and the output profile offers the
full contour vocabulary, but reading an arbitrary outline off a scan is a vision
problem rather than a geometry one. This run went through the manual path.

**Auxiliary planes and face selectors are not offered to Codex.** A selector's
predicates are individually optional and the structured-output dialect has no
optional properties, so constraining the model to that schema would force it to
emit predicates the trusted validator rejects — a planar face has no radius.
Both reach the adapter through the manual API.

**Only the offset auxiliary plane exists.** A plane at an angle or through three
points is `Planes3D.Add(15)` and `Add(16)`, both confirmed present, neither
built.

**Arc–arc intersection is approximated.** The validator tessellates for its
containment and crossing tests. The chord error is capped at a thousandth of the
radius, three orders of magnitude below any tolerance a drawing states, but it
is an approximation and not a proof.

## Reproducing

```bash
python -m pytest -q
dotnet test CadAi.sln --nologo
```

```bash
dotnet run --project apps/local-worker -- run-job .local/acceptance-006
```

The last needs KOMPAS v22 and a `cad-ir.json` in that directory; copy
`tests/fixtures/cad-ir/lever-plate.v1_2.json` into it. `.local/` is ignored by
git.
