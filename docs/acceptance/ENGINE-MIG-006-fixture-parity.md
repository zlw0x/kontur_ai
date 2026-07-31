# ENGINE-MIG-006: fixture parity acceptance

**Date:** 2026-07-31 · **Result:** PASS on all four fixtures, with one deliberate
divergence recorded rather than hidden.

The first half of ENGINE-MIG-006. ADR-023 claims the engine underneath CAD-IR can
be replaced without changing the part a customer receives. This is the run that
checks the claim: every fixture the KOMPAS engine was accepted on is built again
on build123d and measured against the numbers those acceptance runs recorded.

The second half — revolve, the first operation that never existed on KOMPAS — is
a separate piece of work with a separate record.

## What was run

```bash
pytest -q packages/build123d-adapter/tests/test_fixture_parity.py
28 passed
```

`packages/build123d-adapter/tests/test_fixture_parity.py`, in CI, on a Linux
runner with no licence, no GUI and no Windows. Four fixtures, seven checks each:
body count, faces by surface type, edge count, bounding box, volume, the area of
every horizontal face, and the whole export–reopen–verify path.

The expected numbers are transcribed from `docs/acceptance/` or derived by
arithmetic from the drawing. None of them is computed by the engine under test:
a table the engine generated would agree with it about anything it got wrong,
which is the argument ADR-018 makes about expectations and the one `verify.py`
makes about reading a mesh back as a file rather than through the CAD library.

## Result

| Fixture | Bodies | Faces | Edges | Volume mm³ | Bounding box |
|---|---|---|---|---|---|
| `plate.v1_4` | 1 | 6 planar | 12 | 8 000.0000 | [40, 20, 10] |
| `plate-with-hole.v1_4` | 1 | 6 planar, 1 cylindrical | 15 | 7 717.2567 | [40, 20, 10] |
| `constrained-plate.v1_4` | 1 | 6 planar, 2 cylindrical | 18 | 13 595.7523 | [60, 30, 8] |
| `lever-plate.v1_4` | 1 | 12 planar, 5 cylindrical | 39 | 18 530.7344 | [80, 30, 15] |

Face counts, body counts and bounding boxes match what KOMPAS reported for the
same documents. Edge counts do not, for one reason, below.

### The lever plate, face by face

The hardest fixture, and the one POSTMVP-006 measured in most detail: a stadium
profile with two islands, an auxiliary plane, a hexagonal hub and a boss on a
face named by a selector. Every horizontal face's area, on both engines:

| z | KOMPAS, through API5 | build123d | what it should be |
|---|---|---|---|
| 0 | 2167.588 mm² | 2167.588 mm² | 50 × 30 + π·15² − 2·π·2.5² |
| 8 | 1907.781 mm² | 1907.781 mm² | 2167.588 − hexagon 1.5√3·10² |
| 12 | 209.542 mm² | 209.542 mm² | 259.808 − π·4² |
| 15 | 50.265 mm² | 50.265 mm² | π·4² |

Four heights, four areas, to the three decimals the KOMPAS table was written to.
The two kernels agree on the part.

No acceptance run measured the lever plate's volume, so the volume above is
arithmetic rather than a transcription: the stadium plate less its two Ø5 holes,
plus the hexagonal hub, plus the Ø8 pin — 18 530.734 mm³, which is what the
kernel reports.

### The two files, reopened

Each fixture is also built through `cad_worker build`, so the parity claim covers
what is delivered rather than a solid in memory. Every check passes on every
fixture.

| Fixture | STEP | STL | Triangles | Genus | Mesh against solid |
|---|---|---|---|---|---|
| `plate` | 15 435 B | 684 B | 12 | 0 | 0.0000 mm inside |
| `plate-with-hole` | 19 036 B | 26 084 B | 520 | 1 | 0.0000 mm inside |
| `constrained-plate` | 24 892 B | 51 484 B | 1 028 | 2 | 0.0000 mm inside |
| `lever-plate` | 51 226 B | 102 684 B | 2 052 | 2 | 0.0093 mm inside |

`through_hole_count` is derived from the mesh's genus and matches the document on
each of the three fixtures that declare one. The lever plate's mesh sits 0.0093 mm
inside its solid, which is the sagitta of the coarsest chord at the 0.01 mm export
tolerance — inside is tessellation, outside would be a defect, and the comparison
is asymmetric for exactly that reason.

## The one divergence: OpenCascade carries a seam

POSTMVP-005 recorded **8 faces and 16 edges** for a 60 × 30 × 8 plate with two
through holes. build123d builds the same part with 8 faces and **18** edges.

A closed cylindrical face in OpenCascade is parameterised over a period, and the
period has to start somewhere: the surface carries a seam edge along the line
where its parameterisation wraps. KOMPAS's cylindrical face has no such edge. So
a through hole is three edges here — two circles and a seam — and two there.

Measured, not assumed. Each extra edge on the constrained plate is a straight
line of length 8 — the plate's thickness — lying on a hole wall, and it touches
**exactly one face**. Every other edge of a closed solid touches two.

Two consequences, both recorded here so the next operation does not rediscover
them:

- The difference is one per *closed* cylinder, not one per cylindrical face. The
  lever plate has five cylindrical faces and three seams: the stadium's two end
  caps are half cylinders and close nothing.
- A seam is identifiable by that adjacency of one, so an edge selector — the
  first thing fillet and chamfer will need — can exclude seams deliberately
  rather than being surprised by them. This is the "different topology model"
  ADR-023 listed as a cost of the migration, and it now has a shape.

Nothing else differs. No face, area, volume, body count or bounding box.

## What this run also fixed

**The engine's own tests were not running in CI.** The `api` job runs `pytest`
from `apps/api`, and pytest applies `testpaths` only when it is invoked from the
rootdir — so the 53 tests under `packages/build123d-adapter/tests` had never run
on a runner. They passed locally and in no other place. A `cad-worker` job now
installs the worker's own pinned requirements and runs them, which is also what
makes real geometry in CI possible at all.

The parity suite skips itself when the CAD library is absent, so the property
ENGINE-MIG-002 set up — the suite runs on a machine with no engine — is kept.

## What is not claimed

- **Not a claim that the two engines agree on every part**, only on the four the
  KOMPAS engine was accepted on. That is what "parity on the existing fixtures"
  means and it is the bar ADR-023 set before KOMPAS may be removed.
- **Not a claim about M3D.** It leaves the product with KOMPAS; nothing here
  produces or compares one.
- **Not a claim about constraints in the delivered file.** A STEP file cannot
  carry them. The gate that checks a sketch's constraints hold still runs, and
  `constrained-plate` passes it, but the delivered model is exact rather than
  editable-by-dimension — the cost ADR-023 recorded in advance.
