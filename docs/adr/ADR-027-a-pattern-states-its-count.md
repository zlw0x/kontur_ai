# ADR-027: a pattern states its count, and a grid is a pattern of a pattern

## Status

Accepted on 2026-07-31.

## Context

Six holes on a bolt circle have always been expressible: six circle contours with six
sets of coordinates. So the first question a pattern has to answer is what it is
*for*.

The answer is not fewer tokens. It is that **the count becomes something the document
states.** Six coordinates are six chances to get a number wrong and nothing to compare
them against; "six, 60° apart, about this axis" is one intent, and a shape claim that
read six holes off a drawing can be compared against it (ADR-025).

That makes a pattern the first operation since the shape claim landed that the reading
stage can actually ask for. "Six round openings" is something a drawing shows and a
claim already carries, unlike a rounded corner — which is why fillet and chamfer are
`experimental` with nothing able to request them, and why this one is not in the same
position.

## Decision

### A pattern names a feature, not a result

`of` is a feature id. What repeats is the *operation* — a cut stays a cut, an added
boss stays added — and a result id would name the body the source happened to leave
behind rather than the thing being repeated.

The engine re-derives the source's solid through the same function the source feature
itself used (`_tool_of`), which is why `_extrude_feature` and `_revolve_feature` were
split into a tool-maker and a combine. A pattern that rebuilt the geometry its own way
would be a second implementation of every operation it can repeat.

### Instance zero is the source's own position

A pattern of six adds five, because the sixth is already in the part. The alternative
— a pattern that also rebuilds the original — makes a document where disabling the
source silently changes how many instances exist.

Which is why a pattern of a **disabled** source is refused by the canonical validator
rather than left to the engine. It builds: five instances land at offsets from a
position nothing occupies, the part has five holes where the drawing shows six, and
every check passes.

### The step is stated, never divided

`step_deg` is the angle between consecutive instances. A `total_angle` field has two
defensible readings for a closed circle — six instances 60° apart, or six spanning 360°
with the last on top of the first — and a document meaning one and read as the other
builds a plausible wrong part. The arithmetic that turns "six equally spaced" into 60
belongs to whoever read the drawing, which is the same argument ADR-024 makes about an
inferred axis.

### A skipped instance is named by its ordinal, and that is not an index

ADR-019 forbids naming a *face* by position because the kernel decides the order. A
pattern's instances are numbered by the document itself — direction, step, count — so
ordinal 3 is the same instance after any parameter change.

Skipping zero is refused (a document that wants no original should disable the
feature), and skipping *every* repeat is refused for the reason ADR-026 gives about a
blend that matches nothing: a feature that adds no instance is valid, builds, and is
indistinguishable from a document that never asked for one.

### A grid is a pattern of a pattern

`of` may name another pattern, and the outer one copies everything the inner one
produced — the original included. Two crossed linear patterns are a grid, so there is
no third operation with one test to its name. The roadmap's "grid" (P2.5) is therefore
delivered without a `grid` kind.

### A patterned opening counts in a shape claim

`shape_claim.py` now multiplies. Six holes on a bolt circle are six openings to whoever
read the drawing, whether the document spells out six circles or one and a pattern of
six, and four bosses made by patterning one are four lumps of material.

The multiplier is computed by walking the features in the document's own order, the way
the engine builds them, rather than from a formula: two patterns of one source each add
their instances to what is already there, while an outer pattern multiplies everything
the inner one produced. A closed form for that is a second model of the build to get
wrong.

## Consequences

**Something a measurement cannot catch, and the claim can.** Twelve instances 60°
apart is six holes drilled twice. The part is identical to the correct one — the
volume, the face counts and the mesh genus all agree — so a document asking for twice
as many holes as the drawing shows passes every check the verifier has. The shape claim
is the only thing that compares stated counts, and it is the only thing that notices.
That is the clearest example so far of why a claim is worth having at all.

**A defect in the selector layer came out of this.** `topology.py` filled a
descriptor's `centroid` from build123d's `center()`, which defaults to
`CenterOf.GEOMETRY` — the middle of the surface's own parameter domain. For a planar
face that is the centroid; for anything curved it is a point *on* the surface, so the
centre of a Ø8 hole at x = −50 read as x = −54, and the circular edge round its mouth
read the same way. Nothing failed, which is what made it dangerous: a document
selecting "the face centred on x = −50" did not match it, and one selecting x = −54
matched something no drawing describes. It is now the centre of mass, with a test.

Found because a pattern test asserted where the instances went — the first thing in the
codebase to ask a descriptor for a curved face's position rather than for its extreme.

**Re-deriving a tool re-resolves its selectors.** A pattern of a feature whose sketch
sits on a face named by a selector resolves that selector again, against the part as it
is when the pattern runs. That is the rule ADR-019 sets for every selector, and it means
such a pattern fails with a selector error if the face has since become ambiguous,
rather than guessing.

**Left out:** a pattern along a curve (P2.5), which needs a curve in the document that
nothing else has a use for yet, and a mirror about a datum plane, which is refused with
`UNSUPPORTED_FEATURE` rather than quietly reflected about a base plane instead — a
mirror about the wrong plane is a part nobody can tell apart from the right one by
reading the document.

All three kinds are declared `experimental`. Unlike the blends, what stands between
them and `beta` is not a missing vocabulary: it is the corpus the roadmap asks for and
an output profile that offers the operation.
