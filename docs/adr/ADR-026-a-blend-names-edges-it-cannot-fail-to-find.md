# ADR-026: a blend names edges it cannot fail to find

## Status

Accepted on 2026-07-31.

## Context

Fillet and chamfer are the first operations that build nothing.

Every operation before them takes a profile and makes material: an extrusion, a
revolve, a cut. Getting one wrong produces a solid of the wrong size, and
arithmetic catches it — the acceptance runs for POSTMVP-006 and ENGINE-MIG-006 are
mostly volumes compared against numbers derived from a drawing.

A blend takes the solid that already exists and modifies the edges a selector
names. Its failure mode is therefore new: **a part of exactly the right size with
the round in the wrong place.** The bounding box of a plate with rounded corners is
the bounding box of the plate. The body count is one either way. A hole count knows
nothing about corners. So every check the pipeline had passes on a plate whose
fillet landed on the wrong edge, or at the wrong radius, or nowhere at all.

That is the problem this ADR is about. The kernel call is one line —
`fillet(edges, radius)` — and everything that matters is on either side of it.

## Decision

### A blend may not declare a cardinality that permits zero matches

`Cardinality.ALL` and `ZERO_OR_ONE` are refused for an edge blend. They are the two
that look harmless, and they are the dangerous ones: both make a blend that matched
nothing a *successful* feature. The document validates, the build succeeds, every
expectation passes, and the drawing's rounded corners are square. Nothing
downstream can distinguish that from a document that never asked for a fillet.

So a blend declares `exactly_one`, `one_or_more` or `exactly_n`. "Round every
corner" is written `exactly_n: 4`, which is strictly better than `all`: it states
the count, so a part that grew a fifth corner is a contradiction rather than a
surprise. This is the argument `ExactlyN` was written for (ADR-019) and the first
operation that needs it.

### An asymmetric chamfer names the face its first distance is measured from

Two distances, or a distance and an angle, mean nothing until something says which
side of the edge the first one belongs to. build123d takes a `reference` face for
exactly this reason, and without one the kernel's answer to "which side?" is
whichever face it happened to visit first — the same class of non-determinism as a
face index.

So `measured_from` is a face selector, required for an asymmetric chamfer and
refused for a symmetric one (where it would have nothing to disambiguate). The
engine checks the face contains every edge being chamfered before the kernel is
asked, because the kernel's version of that check is a `ValueError` with nothing
about the document in it.

### A blend produces nothing

`produces` is empty, enforced. A blend modifies a body rather than making one, so a
result id would name something that was already there.

### Convexity is measured, and unevaluable predicates are refused outright

`EdgePredicates.convexity` has been in the contract since ADR-019 and until now the
resolver silently ignored it. That is worse than not having it: a selector stating
`convexity: convex` matched on its *other* predicates alone and quietly took the
concave edges too.

It is now measured. The test is the dihedral angle through the material, decided
from directions rather than by classifying a probe point as inside or outside — the
first attempt used a probe point and cannot work, because for both a convex and a
concave edge the outward normals sum to a direction pointing out of the solid.
What distinguishes them is where each face *goes* from the edge: `u1 · n2` is
negative when the faces fold away from each other and positive when they fold
towards each other.

Verified against known geometry rather than reasoned about alone. On the lever plate
all four answers occur at once: seven concave roots (six under the hexagonal hub,
one under the pin), four tangent edges where the stadium's end caps meet its
straight sides, three seams with no answer, and everything else convex — including
the rims of the two holes, which is the only surprise and is correct. A hole's rim
is a sharp outside corner; that is why chamfering one makes a countersink.

The predicate this engine still cannot evaluate is `produced_by`, which needs a
topology that remembers which feature made it, and OpenCascade's does not. It is now
`SELECTOR_UNSUPPORTED_PREDICATE` rather than a clause that does nothing.

### A seam is never a candidate

The resolver drops every edge that touches exactly one face, and traces the drop.
OpenCascade carries a seam on each closed cylindrical face where KOMPAS did not
(ADR-023) — it is where the surface closes on itself, not an edge of the part in any
sense a drawing would recognise.

Leaving them in the pool would make `exactly_n: 4` on the vertical edges of a plate
with a bore a count of something the part does not have, and the answer would differ
between kernels. CLAUDE.md already recorded the rule and the test for it; this is
where it becomes code.

### A blend is invisible to a shape claim, and that cost is stated

A fillet does not change the outline, the openings or the number of solids, so
`shape_claim.py` has nothing to say about one, and the bracket fixture is claimed
exactly as the plate it started as. Making a rounded corner contradict a
`rectangle` claim would be the claim describing the document rather than the part.

The consequence is real: **a fillet the drawing shows and the document omits is
invisible to the claim.** That is what the new expectation is for.

### A new expectation, because nothing else can see a blend

`surface_face_count` states how many faces of one surface kind the finished solid
has, optionally with the radius they must have. A fillet leaves four cylindrical
faces of radius 6 behind; a plate with square corners has none.

Stated by the document and measured off the reopened STEP, like every other
expectation and for the same reason (ADR-018): a count derived from the plan that
produced the geometry would agree with it about anything they both got wrong.

## Consequences

The blends and the convexity predicate are declared **experimental**, which the API
reads as not leasable. Two reasons, and the second is the one that matters: nothing
in the service can currently produce a document that uses them — a shape claim has
no word for a rounded corner, so the reading stage cannot state one and there would
be nothing to check the blend against.

`scripts/generate_output_profile.py` therefore does not offer them, and this is the
first operation excluded for *both* available reasons at once. The Codex dialect
requires every object to list all its properties as required, and an edge
selector's predicates are individually optional — so the model would be forced to
emit every one of them, and the canonical validator would then reject the result
because a straight edge has no radius.

Convexity carries a feature flag of its own, separate from the operations that use
it, because it is a measurement this engine makes with a dot product it wrote
itself. If that turns out to be wrong on some geometry, what has to stop is every
selector that trusts it, not every fillet.

One kernel behaviour was measured and is worth writing down: **chamfering an edge
that ends at a fillet makes OpenCascade add a conical transition face at each such
corner.** Chamfering the four top edges of a plate with four rounded corners
produces four cones nobody asked for, plus the chamfer's own planar faces. They are
correct geometry, and they mean a `surface_face_count` for cones on such a part
would have to know a kernel detail no drawing states. The fixture is shaped to
avoid it — the chamfers are on the bore, where nothing transitions — rather than the
expectation being written to accommodate it.

What is deliberately not here is the **tangent chain**, which P2.4 asks for: "this
edge and everything smoothly continuous with it". It is an implicit widening of a
selector, where the document states one edge and the kernel decides how many it
meant. Every rule above exists to stop that, so a chain has to arrive as something
the document counts.
