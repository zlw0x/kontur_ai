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

## Not done yet

The resolver itself, and everything downstream of it:

- **Face and edge resolvers** in `packages/kompas-adapter`, walking the
  collections above and filtering by predicate.
- **Resolution traces** emitted as an audit record, and the six typed errors
  wired to real failures.
- **Stability tests**, which are the ones that matter and cannot be faked:
  resolve the top face, change the width from 40 to 60, rebuild, resolve again
  and get the same face; then save, close KOMPAS, reopen the M3D in a new
  process and resolve again. COM handles are not valid across any of those, so
  selectors must be re-resolved each time and must never be serialised.
- **Symmetric ambiguity**, which is the test that proves determinism: two
  identical side faces matched by "planar, parallel to YZ" must produce
  `SELECTOR_AMBIGUOUS`, not an arbitrary first match. Adding
  `extreme_along X = maximum` must then resolve exactly one.
- **Ledger instrumentation** for resolution time.

## Constraint carried forward

No fillet, chamfer, shell, rib, draft, face-selected pattern, loft or sweep
until the resolver and its stability tests are done. Adding one first is how
an adapter starts depending on face ordering, and that debt is paid by
rewriting every operation built on it.
