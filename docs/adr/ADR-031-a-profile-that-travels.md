# ADR-031: a profile that travels, and the material between sections

## Status

Accepted on 2026-08-02. CAD-IR 1.9.

## Context

Sweep and loft are one question asked twice: given a profile, what carries it? A path,
or the next profile along. They land in one version for the same reason the two blends
did — the decisions are the same shape, and the second is cheap once the first is made.

Both have a property the operations before them did not. An extrude, a revolve, a
pattern and a shell each fail *loudly* when the document is wrong about them. These two
do not. Every measurement below is a document OpenCascade builds without complaint, and
in four of the five cases reports as a valid solid of plausible volume.

## What was measured

build123d 0.11.1 on OpenCascade 7.9.3.1.1. All five are kept as tests
(`packages/build123d-adapter/tests/test_sweeps.py`), because a justification that lives
only in an ADR stops being checked.

| what the document says | what the kernel does |
|---|---|
| a path starting at (30, 0, 0), profile at the origin | builds the part **at the origin** — the path's position is ignored |
| a Ø16 circle along a 45° line of length 56.57 | 8 042 mm³ = π·8²·**40** — it swept the profile's *projection* |
| a Ø16 pipe round a 4 mm bend | builds, `is_valid` is `True`, volume matches Pappus exactly; the exported mesh has **69 open edges** |
| two loft sections in the same plane | one closed solid, volume **0.0** |
| a square lofted into a circle | a solid, of plausible volume, with a correspondence the kernel chose and never stated |

## Decision

### A path is stated from the profile

Its first point is the origin of the plane it is drawn in. The kernel anchors the sweep
at the profile whatever the path's coordinates say, so an absolute position in the
document would be a number that means nothing until it means something wrong. Made
relative, there is no position left to disagree with — and `SWEEP_PATH_NOT_AT_ORIGIN`
refuses the document that tries.

There is no `distance` on a sweep. How far the material goes is the path's own length,
said once.

### A path is open, tangent-continuous, and crosses the profile

- **Open.** A closed path meets itself at a seam the document does not describe. A
  profile taken all the way round is a revolve, which states its axis (ADR-024).
- **Tangent-continuous.** A sharp corner is not a part: real bends have a radius and the
  drawing dimensions it. A kernel asked to handle the transition picks one of three
  answers, and an invented radius is exactly what ADR-026 refuses to let a blend do. So
  the corner is refused and the document states the arc.
- **Perpendicular to the profile.** This is the one that costs a number: at 45° the
  swept solid has 1/√2 of the cross-section the drawing dimensions, and the document
  says nothing about it.

### A bend must clear the profile, measured on the side it turns towards

`SWEEP_BEND_TIGHTER_THAN_PROFILE`, checked before the kernel, because the kernel's own
answer is a self-intersecting solid that calls itself valid. The mesh check does catch
it — as a torn STL, which is the document's mistake reported as a geometry fault.

The check is **directional**, not a circumradius. A profile 40 wide sitting 15 mm off
the path reaches 35 mm one way and 5 mm the other; a 10 mm bend away from the bulk is a
correct document, and a single "does the profile fit in the bend radius" test would have
refused it. The direction pointing at the centre of a bend is perpendicular to the path
and lies in the path's plane, so it lies in the profile's plane too — and the reach along
it is an optimal bounding box in a frame where that direction is an axis, which
OpenCascade computes exactly (a circle of radius 8 measures 8, not 8.0001).

### A loft's sections are the same kind of contour with the same number of vertices

This is the operation's whole content. The correspondence — which point of one section
becomes which of the next — is something the kernel always decides and never states, so
a square lofted into a rotated square is either a twist or a fold depending on which
corner it matched. Gate P4 phrases the requirement the other way round: *ambiguous
section correspondence is rejected.*

Same kind, same count, and correspondence follows from the shapes. A hexagon into an
octagon is refused; a hexagon into a hexagon is not.

Two consequences worth stating.

**A round-to-square transition is refused, and it is a real part.** It comes back when
the document can *state* the correspondence — a list of which vertex meets which —
because that is the thing the drawing knows and the kernel does not.

**The shape claim needs nothing new.** Its `profile` is the kind of contour the part is
made of, and with every section the same kind, one word covers all of them. Had mixed
sections been allowed, a claim of `circle` would have been satisfied by a solid that
ends as a square — the claim saying something true about half a part.

Islands are refused in a loft section for the same family of reasons: a hole is a second
correspondence, and nothing says which hole pairs with which.

**Coplanar sections are refused by the engine**, not the contract, because where a datum
plane ends up is only known once the build has run.

### What both mean for the claim

A swept or lofted solid is a lump of material and a swept or lofted cut is an opening,
which is all the claim has ever counted. The two lists it counts them with are now named
(`_MAKES_MATERIAL`, `_REMOVES_MATERIAL`) rather than spelled out at each use: an
operation missing from them is one the claim silently stops counting, and a document
with two swept bosses would satisfy a claim of one solid.

Neither has an extrusion distance, so a claim naming a `thickness` for one is contradicted
rather than ignored — a part with no extrusion has no dimension that word refers to.

## Consequences

**The cycle cannot ask for either, and will not soon.** Both are behind the claim wall
and the vision wall of ADR-029, not the dialect one: a sweep is perfectly expressible in
Codex's structured-output dialect, and a drawing agent recognising a centre line with
bend radii on an elevation is a vision problem. What is delivered is the contract, the
engine and the evidence; the reading stage catches up when it can see one.

**Eight corpus cases and seven refusals**, and both operations have closed-form
arithmetic, which is why they could be added at all:

- **Pappus** for a sweep — `area × path length`, exact including round the bends,
  because the profile's centroid sits on the path so the distance it travels *is* the
  path length;
- the **prismatoid rule** for a loft — `h/3 × (A₁ + √(A₁A₂) + A₂)` between similar
  sections, exact for a linear transition, and a three-section `ruled` loft is two of
  them end to end. A three-section smooth loft is not, and that is a case of its own —
  which is why `ruled` is stated rather than defaulted at the kernel.

Four keys — `solid.sweep`, `cut.sweep`, `solid.loft`, `cut.loft` — at `beta` on arrival,
by the criterion POSTMVP-013/014 set: the corpus varies what each of them decides.

**A rotational correspondence between like sections was left to the kernel, and is not
any more.** The contract's kind-and-count rule removes the ambiguity that produces a
*fold*; the one it left was the symmetry — and measuring it showed the cost is not a
twist chosen at random but a rotation silently discarded. A 40 × 40 square lofted to
another turned 90° builds a prism: 48 000.0000 mm³, the same digits as the un-rotated
case. `_require_unambiguous_rotation` now refuses a rotation of a whole symmetry or more,
because at that point the sections record a different angle from the one the document
states. `docs/GATE-P4-ANALYSIS.md` has the four measured angles and the reasoning; a
drawing that means a quarter-turn twist has to say so as a twist, which is P4.1's
`controlled twist` and a different input.
