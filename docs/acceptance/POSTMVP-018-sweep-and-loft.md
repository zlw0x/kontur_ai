# POSTMVP-018: sweep and loft — acceptance

**Date:** 2026-08-02 · **Result:** PASS. CAD-IR 1.9, four capabilities at `beta`, 55
positive and 27 negative corpus cases, 789 Python tests passing.

`docs/adr/ADR-031-a-profile-that-travels.md` is the decision. This is what was built and
what each part of it is checked by.

## What they are

Two operations, one version, because they are one question asked twice: given a profile,
what carries it? A path, or the next profile along.

```json
{"type": "solid.sweep",
 "inputs": {"sketch": {…},
            "path": {"id": "path.spine", "plane": "XZ",
                     "segments": [{"type": "line",  "start": [0, 0],  "end": [0, 50]},
                                  {"type": "arc", "start": [0, 50], "end": [30, 80],
                                   "center": [30, 50], "sweep": "cw"}]}}}

{"type": "solid.loft",
 "inputs": {"ruled": false, "sections": [{…}, {…}]}}
```

Both have `cut.` forms. Neither has a `distance`: a sweep's is the path's own length and
a loft's is where its sections stand, each said once.

## The five measurements that decided the contract

Every one is a document OpenCascade builds without complaint, and four of the five come
back as valid solids of plausible volume. All are kept as tests in
`packages/build123d-adapter/tests/test_sweeps.py`.

| what the document says | what the kernel does |
|---|---|
| a path starting at (30, 0, 0), profile at the origin | builds the part **at the origin** — the path's position is ignored entirely |
| a Ø16 circle along a 45° line of length 56.57 | 8 042 mm³ = π·8²·**40**: it swept the profile's *projection*, 1/√2 of the section drawn |
| a Ø16 pipe round a 4 mm bend | builds; `is_valid` is `True`; volume matches Pappus to the last bit; the STL has **69 open edges** |
| two loft sections in the same plane | one closed solid, volume **0.0** |
| a square lofted into a circle | a solid, plausible volume, correspondence chosen by the kernel and never stated |

Each has a rule and a code:

| rule | code |
|---|---|
| the path is stated from the profile, so it starts at its plane's origin | `SWEEP_PATH_NOT_AT_ORIGIN` |
| the path crosses the profile at a right angle | `SWEEP_PROFILE_NOT_PERPENDICULAR` |
| no bend turns tighter than the profile reaches into it | `SWEEP_BEND_TIGHTER_THAN_PROFILE` |
| sections stand in different planes | `LOFT_SECTIONS_COPLANAR` |
| sections are the same kind of contour with the same vertex count | refused by the contract |
| the path is connected, open, and tangent-continuous | `SWEEP_PATH_DISCONNECTED`, `SWEEP_PATH_CLOSED`, `SWEEP_PATH_NOT_TANGENT` |

### The bend check is directional, and that matters

A profile 40 wide sitting 15 mm off the path reaches 35 mm one way and 5 mm the other. A
10 mm bend *away* from the bulk is a correct document; the same bend towards it is not.
A single "does the profile fit inside the bend radius" test would have refused both —
one of them wrongly, which is a correct drawing turned away.

The direction that matters points at the centre of the bend: perpendicular to the path
and in the path's plane, so it lies in the profile's plane too. The reach along it is an
optimal bounding box in a frame where that direction is an axis, which OpenCascade
computes exactly — a circle of radius 8 measures 8, not 8.0001. Both sides are measured
and each arc is checked against its own.

## Why these two could be added at all: the arithmetic is closed-form

**Pappus** for a sweep: `area × path length`, and it is exact including round the bends,
because the profile's centroid sits on the path — so the distance the centroid travels
*is* the path length. Measured difference on the elbow case: 0.0.

**The prismatoid rule** for a loft: `h/3 × (A₁ + √(A₁A₂) + A₂)` between similar sections,
exact for a linear transition. A three-section `ruled` loft is two of them end to end; a
three-section smooth loft is not — 37 632 mm³ against 49 920 — which is why `ruled` is
stated rather than defaulted at the kernel.

| corpus case | arithmetic |
|---|---|
| `sweep-straight` | `π·8²·60` — a sweep along a line is an extrusion |
| `sweep-elbow` | `π·8²·(50 + 30·π/2)` |
| `sweep-rectangular-section` | `20·10 × (40 + 25·π/2)` |
| `sweep-cut-groove` | plate − ½·π·3²·100, a half-round channel across the top face |
| `loft-truncated-cone` | `30/3 × (π20² + √(π20²·π8²) + π8²)` |
| `loft-truncated-pyramid` | `30/3 × (40² + 40·16 + 16²)` |
| `loft-three-sections-ruled` | 2 × the truncated pyramid |
| `loft-cut-tapered-pocket` | plate − `15/3 × (10² + 10·30 + 30²)` |

Seven negatives cover every code above. `sweep-elbow` and `loft-truncated-cone` join the
determinism set: built twice, byte-identical STL, STEP differing only in its timestamp.

Four keys — `solid.sweep`, `cut.sweep`, `solid.loft`, `cut.loft` — at `beta` on arrival,
by the POSTMVP-013/014 criterion that the corpus varies what the operation decides. The
engine now declares **39 capabilities, 38 beta and 1 experimental**.

## The fixture

`tests/fixtures/cad-ir/transition-duct.v1_9.json` — a square mouth lofted down to a
throat, and the throat carried up and round a bend. Both operations in one document, and
they fuse without a boolean: the sweep names no body, so it joins the one being built,
which is what a drawing of a duct means.

```
transition   40/3 × (60² + 60·30 + 30²)   =  74 000.0000
riser        30² × (50 + 25·π/2)          =  90 342.9174
total                                       164 342.9174
built                                       164 342.9174   (Δ 0.0)
```

One solid after `clean()`, bounding box 60 × 60 × 130, and the reopened STEP and STL
verify — worth asserting on this part in particular, because a sweep round a bend is
where a torn mesh comes from and a fused loft-and-sweep is where a body count of two
would come from.

## What they mean for the claim

A swept or lofted solid is a lump of material; a swept or lofted cut is an opening. That
is all the claim has ever counted, and both lists are now named in one place
(`_MAKES_MATERIAL`, `_REMOVES_MATERIAL`) instead of being spelled out at each use — an
operation missing from them is one the claim silently stops counting, and a document with
two swept bosses would have satisfied a claim of one solid.

A loft's outline is the kind every one of its sections is, which is only true *because*
mixed sections are refused. Had they been allowed, a claim of `circle` would have been
satisfied by a solid that ends as a square.

Neither has an extrusion distance, so a claim naming a `thickness` for one is
contradicted rather than ignored.

## Tests

| suite | result |
|---|---|
| Python | **789 passed, 1 skipped** |
| .NET | 6 + 30 + 41 + 31 (4 container tests skipped — no `CAD_ENGINE_IMAGE` here) |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

## What this is not

**The cycle cannot ask for either, and will not soon.** Both are behind ADR-029's *claim*
and *vision* walls rather than its dialect one — a sweep is perfectly expressible in the
Codex dialect, and recognising a centre line with bend radii on an elevation is a vision
problem. What is delivered is the contract, the engine and the evidence.

**A 3D path is not in.** P4.3 — helices, 3D splines, projected curves — needs a way to say
where a point is in space that CAD-IR does not have. A planar path is what a drawing
gives: a centre line in an elevation with the bend radii dimensioned on it.

**Guide curves and twist control are not in** (P4.1), and neither is vertex-level
correspondence (P4.2). Both are how the refused cases come back, and both are things the
*document* would have to state.

**A rotational correspondence between like sections is still the kernel's.** A square
lofted into a square rotated 45° has two equally near vertices; OpenCascade picks one
deterministically. The contract's rule removes the ambiguity that produces a fold, not
this one, which produces a twist that is a real part. Recorded rather than solved, and no
corpus case relies on it.

**It is not Gate P4**, which asks for a topology oracle on loft and sweep. What is here is
the arithmetic oracle — volume from closed form — and the correspondence rule that Gate P4
names. A topology oracle would check the face and edge structure of the result, and that
is the next thing this operation needs.
