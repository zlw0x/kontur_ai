# Runs 7 to 9: the three POSTMVP-019 owed

**Date:** 2026-08-03 · **Machine:** the one Codex is signed in on

`POSTMVP-019-named-selections.md` ends by naming three runs. It opened selections
to the drawing cycle — the upright convex corners, the topmost circular rims, the
planar +Z face — and grew the claim to match, with `ShapeClaim.blends` and
`wall_parameter`. What it could not settle is whether the reading stage *uses* any
of it on a real scan. These are those runs.

What makes all three different from runs 2–6 is that the failure they look for is
**silent**. A blend builds nothing: a plate with square corners where the drawing
shows R5 agrees on the outline, the openings, the solid count and the bounding
box. A chamfer on the wrong edge is a correctly-sized part with the break in the
wrong place. And a housing built solid agrees on everything and weighs four times
what it should.

---

## Run 7 — four R5 corners

**Drawing:** 80 × 50 × 10 plate, "4 × R5" against one corner.

The only run of the nine with **no clarification question at all**: read,
compiled and built on the first pass.

```json
{"profile": "closed_profile", "openings": [], "solids": 1,
 "thickness": "thickness",
 "blends": [{"kind": "fillet", "count": 4}],
 "note": "Rectangular plate outline with four rounded R5 corners."}
```

`blends` came back with the kind and the count, which is the whole of what
POSTMVP-019 asked. `profile` is `closed_profile` rather than `rectangle`, and that
is right rather than a near miss — a rounded rectangle is not a rectangle, and the
claim says so.

The compilation used the corner selection as written:

```json
{"id": "feature.corner_fillet", "type": "feature.fillet",
 "inputs": {"edges": {"id": "selector.corners", "kind": "edge",
                      "from_result": "body.main",
                      "cardinality": {"type": "exactly_n", "value": 4},
                      "where": {"curve_type": "line",
                                "direction_parallel_to": "axis.z",
                                "convexity": "convex"}},
            "radius": {"parameter": "corner_radius"}}}
```

`exactly_n: 4` — the only cardinality ADR-026 allows for a blend, and the one that
makes the count comparable. The radius is a **parameter reference**, not a
literal.

### The build

| | |
|---|---|
| volume | (80 × 50 − (4 − π) × 5²) × 10 = **39785.3982 mm³**, measured **39785.3982** |
| bounding box | expected [80, 50, 10], measured [80, 50, 10] |
| face_count | **10** — six for the box, four for the fillets |
| topology_agrees_with_mesh | B-rep genus 0, mesh genus 0 |

The face count is the point. Every other number here is identical for a plate with
square corners; 10 against 6 is the only thing that can tell them apart, which is
why `surface_face_count` exists.

### And a note on the parameter finding from run 5

All four of this document's parameters — `overall_length`, `overall_width`,
`corner_radius`, `thickness` — are referenced by geometry. None is a literal.

That confirms the diagnosis rather than contradicting it: the flange's unused
parameters were unused **where arithmetic was needed** (a diameter driving a
radius, a PCD driving a centre). Where the drawing's number is the number the
contour takes, the model uses the parameter.

**Run 7: PASS.**

---

## Run 8 — a 2 × 45° break on a bore rim

**Drawing:** 70 × 70 × 14 plate, one Ø30 through bore, the chamfer note leading to
the bore's top rim on the section.

No questions either. The selection is the one that decides everything:

```json
{"id": "feature.bore-chamfer", "type": "feature.chamfer",
 "inputs": {"edges": {"id": "selector.rims", "kind": "edge",
                      "from_result": "body.main",
                      "cardinality": {"type": "exactly_n", "value": 1},
                      "where": {"curve_type": "circle",
                                "position": {"extreme_along": "axis.z",
                                             "extreme": "maximum"}}},
            "distance": {"parameter": "bore_chamfer_size"}}}
```

A **circular** edge, topmost along Z — the rim selection, not the corner one. The
claim agrees: `blends: [{"kind": "chamfer", "count": 1}]`, one round opening,
`through: true`.

### The build, and why its volume is a proof of *position*

| | |
|---|---|
| volume | 70×70×14 − π×15²×14 − 2π × 15.6667 × 2 = 68600 − 9896.0169 − 196.8731 = **58507.1100 mm³**, measured **58507.1100** |
| bounding box | expected [70, 70, 14], measured [70, 70, 14] |
| through_hole_count | expected 1, mesh-derived genus 1 |
| face_count | 8 — six for the box, the bore cylinder, the chamfer cone |

The third term is Pappus on the chamfer's 2 × 2 triangle, and its centroid radius
of 15.667 mm belongs to **the bore and to nothing else**. A chamfer taken on the
plate's outline would remove a different volume entirely — four straight runs and
four corners at radius 35, not a ring at 15.667. So the agreement to four decimal
places is not a size check that happened to pass; it is evidence that the break is
where the drawing put it.

That matters because this was the run's stated risk: picking the wrong selection
produces a part that builds, is manifold, and measures the right bounding box.

**Run 8: PASS.**

---

## Run 9 — a housing with a 3 mm wall

**Drawing:** 100 × 60 × 40 open-topped box, "t = 3" leading to the wall on the
section.

One question, and a good one:

```json
{"id": "q_wall_and_bottom_thickness", "parameter_id": "wall_thickness",
 "text": "What are the uniform wall thickness and the bottom thickness (mm)?"}
```

The drawing calls out the wall and says nothing about the floor. A shell has one
thickness, so the two must agree before the document can be written, and the
reading stage asked rather than assuming. Answered: both 3.

### `wall` reached the claim

```json
{"profile": "rectangle",
 "openings": [{"kind": "rectangular", "count": 1, "through": false}],
 "solids": 1, "thickness": "overall_height", "wall": "wall_thickness"}
```

That is POSTMVP-017's word arriving where it was meant to. `wall` is a **name,
never a number** — ADR-025's rule holds — and it is the first thing a claim says
about how much of the part is there rather than what shape it is. The cavity is
also stated as a blind rectangular opening, which is what it is.

The shell used the +Z face selection and the parameter:

```json
{"id": "feature.shell", "type": "feature.shell",
 "inputs": {"faces": {"id": "selector.top", "kind": "face",
                      "from_result": "body.main",
                      "cardinality": "exactly_one",
                      "where": {"surface_type": "planar",
                                "normal": {"parallel_to": "axis.z",
                                           "direction": "positive"}}},
            "thickness": {"parameter": "wall_thickness"},
            "direction": "inward"}}
```

`exactly_one`, not `all` — the rule ADR-030 sharpened, because with no face open
`offset` stops hollowing and starts shrinking the solid instead.

### The build

| | |
|---|---|
| volume | 100×60×40 − 94×54×37 = 240000 − 187812 = **52188 mm³**, measured **52188.0000** |
| bounding box | expected [100, 60, 40], measured [100, 60, 40] |
| solid_body_count | expected 1, measured 1 |
| through_hole_count | expected 0, genus 0 |
| face_count | 11 |
| closed_manifold_mesh | 0 edges without exactly two incident triangles |

**52188 is the number ADR-030 recorded** when it measured `offset` directly on the
kernel to decide what the contract should say. It was got there by probing the
engine; here the cycle arrives at it from a drawing.

And the number beside it is the whole reason `ShapeClaim.wall` exists. A document
that built this solid would come back at **240000 mm³** — 4.6 times the material —
while agreeing with the drawing on the outline, the openings, the solid count, the
bounding box and the hole count. Nothing except the wall would notice.

**Run 9: PASS.**

---

## All nine

| run | what it asked | result |
|---|---|---|
| 1 | (POSTMVP-016) the thickness parameter | FAIL → found the claim refusing a correct part; fixed |
| 2 | `through: false` on a blind pocket | PASS |
| 3 | what happens when something is unknowable | PASS — asks for a number, stays silent about a view |
| 4 | a pad: `solids: 2` and a datum plane | PASS |
| 5 | a bolt circle: pattern or contours | PASS on the part, **no** on the pattern |
| 6 | does the claim catch a miscount | PASS, both directions |
| 7 | four R5 corners | PASS, and the only run with no questions |
| 8 | a chamfer on a bore rim, not the outline | PASS, proved by volume rather than by size |
| 9 | a wall the claim can name | PASS |

Eight of nine parts built; every number closed-form from the drawing and matching
to four decimal places. What the runs changed is that the sentence "the cycle
reaches ten of the engine's capabilities" stopped being a statement about
contracts and became a statement about behaviour — with one correction, that the
pattern among those ten is offered and not taken.
