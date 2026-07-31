# ADR-028: a body is a thing the document names

## Status

Accepted on 2026-07-31.

## Context

`source_body` has been in CAD-IR since 1.1. The engine ignored it, and nothing broke —
because there was only ever one body. Every additive feature fused into whatever had
been built and every cut removed from it, so a field pointing at "the body" always
pointed at the right one.

Three things were waiting on that changing.

**`from_result` on a selector was decorative.** A face or edge selector says which
body's geometry it means, and with one body the answer could not be wrong. ADR-019's
whole argument is that geometry must be named by what it means — and the body was the
one part of that name nothing checked.

**Fusing was implicit.** Fine for a boss on a plate. Not fine for "subtract this tool
from that body and keep the tool", which is a statement about two named things and
cannot be spelled as an ordering of features.

**`body_count` could only ever be 1.** The expectation existed, the verifier counted
solids in the STEP, and no document could make the number anything else.

## Decision

### A body is created by name, targeted by name, combined by name

`Bodies` (`cad_engine_build123d/bodies.py`) replaces the single running solid: a list of
bodies, the names each answers to, and which one is active.

- A solid feature with `new_body: true` starts a separate lump, and **must** name it
  through a `produces` entry. A body nothing can name is a body no selector and no
  boolean can reach; it would arrive in the delivered STEP as a lump with no history.
- A feature with `source_body` joins or cuts the body it names.
- A feature with neither targets **the active body** — the last one created or modified.

That last rule is the one that matters most, because it is what makes this change
invisible: it is exactly what every document written before 1.7 means, and what the
drawing pipeline emits. The alternative — every solid feature making its own body —
would silently turn every existing multi-feature part into a multi-body one.

### A boolean modifies its target and consumes its tools

`feature.boolean` carries an op (`union`, `subtract`, `intersect`), a target body, one or
more tool bodies, and `keep_tools`. It produces nothing: the result *is* the target
body, under the name it already had. A boolean that produced a new body id would leave a
document naming three bodies where a person sees one, and every later selector would
have to know which of the three the part is now made of.

A name is never reused. A consumed tool's body is removed along with its names, so a
later selector naming it fails — rather than falling through to whatever took its place,
which is how a fillet lands on the wrong lump of metal.

### An empty boolean is a refusal

An intersection of two bodies that do not touch comes back from the kernel as an empty
shape rather than as an error, and a subtraction can remove everything. Either would
leave a body of no volume in the part, which passes `body_count` and fails nothing. Both
are `BOOLEAN_EMPTY`.

### The delivered file carries the bodies the document left

Several bodies export as a compound, not as a fused solid. Bodies that were never
combined are separate on purpose, and fusing them at export time would be the engine
overruling the document. STEP carries several solids, the verifier counts them, and
`body_count` finally has something to check.

### A shape claim has to know what a boolean did

This is the milestone's claim decision (ADR-025 requires every operation to make one),
and it is the largest so far: **with booleans, what the part *is* can no longer be read
off feature types alone.**

A block extruded and then subtracted from the plate is a *hole* on the drawing. Before
this it was counted as a lump of material and its opening was not counted at all — so a
document that drilled its hole with a boolean disagreed with an honest claim in two
directions at once.

So: a tool that is subtracted contributes an opening of its outline's kind and stops
being a lump; a tool that is intersected is neither; a tool the document keeps is both.
A `union` changes nothing, because a rib welded on by a boolean is the same thing to a
reader as a boss fused implicitly, and the claim has counted that as its own lump since
ADR-025.

`solids` and `body_count` stay different questions, and the bracket is the fixture that
proves they must: it declares **two bodies** and satisfies a claim of **three solids**.
One is measured off the delivered file; the other is what somebody counted on a drawing.

## Consequences

A defect fell out of this before any fixture used it. `_genus` in the verifier assumed
Euler's formula for a *single* closed surface — `V − E + F = 2 − 2g`. For two bodies the
right form is `2c − 2g`, so a part of two lumps with one through hole read as genus 0,
and two lumps with no holes at all would have read as **−1**: a negative number of
holes. The component count is now computed by union-find over the mesh, which is also
the first thing in the verifier that had to know a part can be more than one thing.

`FEATURE_RESULT_UNAVAILABLE` is now the answer where `UNSUPPORTED_FEATURE_SET` used to
be, for a blend or a boolean naming a body nothing built. It is a more precise failure —
"that body does not exist, and here is what does" — and the message lists the bodies so
far, which is what a repair prompt needs.

Everything here is `experimental`. What stands between it and `beta` is the corpus
(POSTMVP-013): a boolean is exactly the kind of operation where the kernel's answer on
tangential or coincident faces needs a body of evidence rather than one fixture.

**What this does not add** is an *active-body statement*. P2.6 lists "active body" as a
feature; here it is a rule rather than a field, because a document that says which body
is active is a document with a second way to say `source_body`, and the two could
disagree.
