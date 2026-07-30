# TASK-POSTMVP-005: semantic selectors

## Why this milestone exists

Every operation after CAD-IR 1.1 — fillet, chamfer, shell, rib, patterns on
selected faces — has to say which faces or edges it applies to. The obvious way
is an index:

```json
{ "edge_index": 17 }
```

and it is wrong in a way that does not announce itself. Change a width from 40
to 60, or add a hole before the one being modified, and edge 17 is a different
edge. The document still validates, the build still succeeds, and the part is
quietly wrong.

A selector describes the geometry instead. "The planar face whose normal points
along +Z and which is furthest along Z" is the top face of a plate, and stays
the top face whatever the plate's dimensions become.

## Contracts (done)

`packages/cad-ir/cad_ir/selectors.py`. Face and edge selectors, each carrying
a set of predicates and an explicitly declared cardinality.

Two rules make this safe rather than merely clever:

**Cardinality is declared, never inferred.** Matching two faces where one was
expected is an error, not a coin toss — picking one at random produces a
plausible-looking wrong part. `exactly_n` lets a document state "these four
mounting holes"; a fifth is a mismatch worth stopping for.

**Resolution filters, it does not score.** No closest match, no confidence
threshold. When the predicates fail to narrow to the declared cardinality, the
build stops and hands over a resolution trace. "Two candidates remained after
the surface-type and normal filters" tells a repair agent to add a position
predicate; "no match" alone tells it nothing.

The contract refuses what cannot mean anything: a selector with no predicates
(it matches every face on the body), a radius on a planar face, a normal
predicate on a curved one — a curved face has a different normal at every
point — a direction with no axis, half a position predicate. Tolerances are
required rather than defaulted, because comparing floating-point geometry for
equality is a bug waiting for a rebuild.

The schema is closed, so a raw topology index has nowhere to go even for a
caller who wants one.

## KOMPAS API evidence (done)

`scripts/probe_kompas_topology.py` reads the installed type library and prints
every member the resolver will call. Two findings shaped the design.

**API7 has no topology enumeration.** `IPart7` on KOMPAS v22 exposes
`FindBody`, `GetBodyById`, `FindObject`, `FindObjectsByPoint` and
`DefaultObject` — and no body, face or edge collection. Probed live against a
model this service built.

**API5 has all of it**, and the adapter already uses API5 for STEP and STL
export, so no new process or authentication path is involved.

| Selector predicate | KOMPAS API5 member |
|---|---|
| enumerate faces / edges | `ksPart.EntityCollection(objType)` `[18]`, `ksPart.BodyCollection()` `[33]`, `GetMainBody()` `[37]` |
| iterate a collection | `GetCount()` `[2]`, `GetByIndex(index)` `[7]` |
| `surface_type` | `ksFaceDefinition.IsPlanar` `[1]`, `IsCone` `[2]`, `IsCylinder` `[3]`, `IsTorus` `[13]`, `IsSphere` `[14]` |
| face `radius_mm` | `ksFaceDefinition.GetCylinderParam(out h, out r)` `[4]` |
| face `area_mm2` | `ksFaceDefinition.GetArea(bitVector)` `[19]` |
| face `normal` | `ksFaceDefinition.GetSurface()` `[6]` → `ksSurface.GetNormal(u, v, out x, y, z)` `[3]`, with `normalOrientation` `[8]` for sense |
| face `position` | `ksSurface.GetGabarit(out x1, y1, z1, x2, y2, z2)` `[1]` |
| face `adjacent` | `ksFaceDefinition.ConnectedFaceCollection()` `[10]`, `EdgeCollection()` `[11]` |
| `curve_type` | `ksEdgeDefinition.IsStraight` `[1]`, `IsLineSeg` `[19]`, `IsArc` `[8]`, `IsCircle` `[9]`, `IsEllipse` `[10]`, `IsNurbs` `[11]` |
| edge `length_mm` | `ksEdgeDefinition.GetLength(bitVector)` `[13]` |
| edge `adjacent` | `ksEdgeDefinition.GetAdjacentFace(facePlus)` `[4]` |
| edge geometry | `ksEdgeDefinition.GetCurve3D()` `[3]` → `ksCurve3D` |

Every predicate the contracts express has a member behind it. No invented
members, no gaps to fill in later.

## Resolver (done)

`packages/kompas-adapter/SelectorResolver.cs` is pure: it takes measured
descriptors, not COM objects, so the whole matching layer is testable on a
machine without KOMPAS. Predicates are applied in a fixed order and each one is
recorded as a trace step. Position is applied last, and the extreme after the
centre — an extreme is a ranking over the survivors, so applying it earlier
answers a different question.

`KompasTopologyReader.cs` is the COM half. It reads and releases; it hands back
values and keeps no handle, because a COM pointer is not valid across a
rebuild, a reopen or a new KOMPAS process. Edges are deduplicated
geometrically: every edge is shared by two faces and `ksEdgeDefinition` exposes
no stable id. A circle's radius is derived from its circumference, which is
exact rather than a guess.

## Stability (done)

`cad-worker resolve-selectors` and
`docs/acceptance/POSTMVP-005-selector-stability.md`. Six selectors resolved in
four phases on live KOMPAS v22: as built, after the plate is widened from 40 to
60 and rebuilt, after the M3D is reopened in a second KOMPAS process, and after
a third hole is drilled.

All six behaved as declared in all four phases. The third hole moved the top
face from collection index 0 to 1 and the +X side face from 3 to 6, and both
selectors still found what they meant — which is the claim the milestone
exists to make. `side_face_ambiguous` returned `SELECTOR_AMBIGUOUS` every time
rather than picking a side, and the three `exactly_n = 2` selectors reported
`SELECTOR_CARDINALITY_MISMATCH` once there were three holes.

The verdict is computed by `SelectorStabilityChecks`, a pure function over the
recorded phases, so the run cannot mark its own homework and the grading is
itself tested against the failures it must catch.

Two defects came out of the first real runs, both written up in the acceptance
document: the KOMPAS unit bit vector for `GetLength` and `GetArea` is 1 and not
0, and the API5 application object must be created once per session rather than
per read.

## Ledger (done)

`SELECTOR_RESOLUTION` is its own `ResourceStage` in both the API contracts and
the worker. Reading a nine-face plate's topology takes 85–145 ms; filtering it
takes under 16 ms. Nothing in the build pipeline resolves a selector yet, so
the events come from the diagnostic — the stage exists so that the first
operation to use a selector reports its cost separately from the feature.

## Constraint lifted

The constraint carried into this milestone — no fillet, chamfer, shell, rib,
draft, face-selected pattern, loft or sweep until the resolver and its
stability tests are done — is discharged. An operation may now be added, and
must name its geometry with a selector rather than an index.

What is still unmeasured: resolution on a model with several hundred faces. The
resolver is a linear scan per predicate, and nine faces prove nothing about
that.
