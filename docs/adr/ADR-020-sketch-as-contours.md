# ADR-020: A sketch is contours, and the geometry gate lives in front of COM

## Status

Accepted on 2026-07-30.

## Context

CAD-IR 1.1 expressed two sketch shapes — a centred rectangle and a circle — on
one plane. Every part the service could build was therefore a rectangular plate
with round holes. That was the right bounded MVP and it is not a service.

Widening the sketch raises a question 1.1 never had to answer. A rectangle and a
circle are closed by construction; a list of lines and arcs is not. So the
moment general contours exist, something has to decide whether a profile closes,
whether it crosses itself, and whether an island is really inside it — and
whatever decides has to do it before KOMPAS is asked to build anything.

## Decision

### One outer contour and its islands, nested one level

A sketch is `outer`, `inner` and `construction`. Islands two levels deep are not
rejected by a rule — they cannot be written down, because a contour has nowhere
to put a contour. The geometric case is checked too, since two islands can
contain one another without the document saying so.

### Contours, and shapes that expand into them

`path` is the general form: an ordered list of line and arc segments. `circle`,
`rectangle`, `slot` and `regular_polygon` are whole contours that expand into a
path deterministically, once, in the trusted parser. The adapter draws lines,
arcs and circles and does not know what a slot is — which is the only reason
there is one implementation of that arithmetic rather than one in the validator
and another in the builder.

### An arc carries its endpoints, its centre and a sweep direction

Endpoints over centre-radius-angles because it is the form that makes a contour
*verifiable*: the previous segment's end must equal this segment's start, and
with angles that is an inference rather than a comparison. The two distances
from the centre must agree, or no arc anybody meant exists and KOMPAS builds
whichever one its arithmetic settles on.

The direction is not redundant with the endpoints. Two arcs share every endpoint
and centre and differ only in which way round they go, and they bound different
regions — measured, not argued: reversing both end caps of the acceptance part
turned an 80 mm profile into a 61 mm one that still built and still validated.

### Construction geometry is separate, and carries a separate style

Points, lines, arcs and circles that exist to be measured or constrained against
live in their own list. No rule has to guess whether a stray line was meant to
close a contour, because a line in `construction` never was.

In KOMPAS this is not cosmetic. A centre line drawn at profile style inside a
closed contour makes the extrusion fail. Style is what separates profile
geometry from geometry that is merely present, so construction geometry is drawn
at the construction style.

### Explicit coordinates only, in this version

No constraint solver, and nothing infers a dimension. A value is a number or a
named parameter, as everywhere else. Constraints are POSTMVP-007, and a
half-solver that resolves some sketches and quietly mis-resolves others is worse
than none.

### A sketch plane may be a base plane, an auxiliary plane, or a face

The auxiliary plane is a *feature* rather than a `reference_geometry` entry,
because it depends on other features and other features depend on it, and the
dependency graph is the one place that is already stated and checked.

The face is named by a POSTMVP-005 selector — never an index, for the reasons in
ADR-019 — and the selector must declare `exactly_one`. A sketch sits on one
face; "one or more" would leave the build picking.

### The face bridge verifies rather than trusts

API7 has no face collection, so topology is measured through API5 and a selector
resolves to a *measurement*, not a handle. A sketch needs an API7 object. The
bridge between them is a point: `FindObjectsByPoint` answers with whatever is at
a coordinate, and the measurement can supply a point on the face.

But a point derived from a face is only *probably* on it — a bounding-box centre
lies inside every planar face this build produces and not inside an L-shaped
one. So the face KOMPAS returns is checked: it must be planar, and its area must
match the area the selector measured, to a part in ten thousand. Otherwise the
build stops. Sketching on the wrong face produces a part that looks plausible,
and that is the failure this whole line of work exists to remove.

### Geometric validation lives in the adapter, in C#

The AI path runs Codex on the worker and hands its CAD-IR straight to the
adapter; the API's Python validator never sees it. A closure check that only
existed in Python would not protect the machine that runs KOMPAS.

So the split is: Python owns the document — its shape, its feature graph, its
version — and C# owns closure, degeneracy, duplication, self-intersection,
containment and nesting. This is the division already in place for the same
reason: the schema says what the version can express, the adapter says what it
can build.

### Nothing is repaired

A gap smaller than the tolerance is not closed, a self-intersection is not
trimmed, a reversed island is not flipped. Each is a guess about what the
document meant, and a guess that builds is worse than a refusal that says where
the gap was and how big it is.

### 1.2, and 1.1 becomes migratable

The additions are additive, but 1.1 moves from *supported* to *migratable* so
that one shape reaches the adapter. A 1.1 document using a 1.2 entity is then
rejected for free by the 1.1 parser, which matters because a document lying
about its version is the start of a compatibility problem rather than the end of
one.

### The output profile is generated, and narrower than 1.2

The structured-output dialect has one rule with teeth — every object lists all
of its properties as required — and keeping that true by hand across a nested
schema is how a full AI run gets spent rediscovering it. So the profile is
generated from a script that applies the rule by construction.

It offers base-plane sketches only. A selector's predicates are individually
optional, and a dialect without optional properties would force the model to
emit predicates the trusted validator rejects. Auxiliary planes and face
selectors reach the adapter through the manual API instead.

## Consequences

The buildable surface is much larger, and so is the number of ways a generated
document can be geometrically wrong while still passing the schema. That is what
the C# gate is for, and its error codes are specific enough to repair against:
`SKETCH_CONTOUR_OPEN` says how big the gap is and between which segments.

Two costs are real. Contour validation is O(n²) in segments for the
self-intersection test, which is fine for the hundreds a profile has and would
not be for the tens of thousands an imported outline might. And the arc
tessellation used for containment is an approximation — capped at a thousandth
of the radius, three orders of magnitude below any drawing tolerance, but an
approximation.

One consequence surfaced only in the real run and is worth recording: the
independent verifier measures the bounding box from an STL, and an STL of a
curved surface is inscribed. The comparison is therefore asymmetric — a mesh
short by up to the export chord tolerance is the tessellation, a mesh wider than
expected is a real error. A flat-sided prism tessellates exactly, which is why
five milestones went by before this mattered.

## Alternatives rejected

**A constraint solver now.** It is the honest way to express a drawing, and it
is POSTMVP-007. Shipping half of one would mean sketches that resolve
differently depending on which constraints happened to be stated.

**Validating geometry in Python only.** It is the wrong side of the boundary:
the AI path never passes through it.

**Auto-healing micro-gaps.** The roadmap allows it below a configurable
tolerance. Deferred deliberately: a healed gap is a change to the part that no
one asked for, and this milestone has no way to record that it happened. When
assumptions are recorded, healing can be reconsidered.

**Letting the sketch be a flat entity list, as 1.1 had.** Then something has to
infer which contour is the profile and which are islands. Order is not that
information, and containment alone cannot express a document's intent to have
exactly one profile.
