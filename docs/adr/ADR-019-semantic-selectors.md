# ADR-019: Geometry is named by meaning, and resolution refuses to guess

## Status

Accepted on 2026-07-30.

## Context

Every operation the roadmap adds after CAD-IR 1.1 — fillet, chamfer, shell,
rib, draft, a pattern on selected faces — has to say which faces or edges it
applies to. The obvious way is an index:

```json
{ "edge_index": 17 }
```

This is wrong in a way that does not announce itself. Change a width from 40 to
60, or add a hole ahead of the one being modified, and edge 17 is a different
edge. The document still validates, the build still succeeds, and the customer
receives a part that is quietly wrong. Nothing in the pipeline can tell.

Measured on this machine, KOMPAS v22, in the acceptance run below: drilling a
third hole in a two-hole plate moved the top face from collection index 0 to 1
and the +X side face from 3 to 6. An index-based document written against the
first model would have applied its fillet to a different face and reported
success.

## Decision

### A selector describes geometry, never its position in a collection

"The planar face whose normal points along +Z and which is furthest along Z" is
the top face of a plate, and stays the top face whatever the plate's dimensions
become. The predicate vocabulary is surface or curve type, normal direction,
radius, area, length, extreme or centred position along an axis, adjacency and
convexity — all of them properties a person could point at on the drawing.

The schema is closed, so a raw topology index has nowhere to go even for a
caller who wants one.

### Cardinality is declared, never inferred

A selector states how many results it expects: exactly one, zero or one, one or
more, all, or exactly *n*. Matching two faces where one was expected is an
error, not a coin toss. `exactly_n` lets a document say "these four mounting
holes"; a fifth is a mismatch worth stopping for, and the acceptance run
confirms that a third hole appearing turns a satisfied `exactly_n = 2` into
`SELECTOR_CARDINALITY_MISMATCH` rather than three quietly drilled features.

### Resolution filters; it does not score

There is no closest match and no confidence threshold. Predicates are applied
in a fixed order, each one recorded as a step, and position is applied last
with the extreme after the centre — an extreme is a ranking over the survivors,
so applying it earlier answers a different question.

When the predicates fail to narrow to the declared cardinality, the build stops
and hands over the trace. "Two candidates remained after the surface-type and
normal filters" tells a repair agent to add a position predicate;
`SELECTOR_NO_MATCH` alone tells it nothing.

### Nothing downstream holds a COM handle

The topology reader measures faces and edges into plain values and releases
everything. A COM pointer is not valid across a rebuild, a reopen or a new
KOMPAS process, so a selector is re-resolved every time rather than remembered,
and a resolved index is never written to a document.

The side effect is that the whole matching layer is testable on a machine
without KOMPAS, which is why 41 adapter tests run in CI.

### Topology is read through API5

KOMPAS API7's `IPart7` exposes no body, face or edge collection — only
`FindBody`, `GetBodyById`, `FindObject`, `FindObjectsByPoint` and
`DefaultObject`. API5 has the whole surface, and the adapter already uses API5
for STEP and STL export, so no new process or authentication path is involved.
`ksDocument3D.GetPart(-1)` returns the top part; the type library exports no
named constant for it, and 0, 1 and 2 return nothing.

### Selector resolution is a measured stage

`SELECTOR_RESOLUTION` is its own `ResourceStage`. On a large model the search
will dominate the feature it serves, and a cost that hides inside
`FEATURE_BUILD` can be neither priced nor optimised.

## Consequences

Adding an operation now means adding a selector to its inputs, not an index,
and the operation cannot be built until the selector resolves to the declared
count. That is slower to write and the failure modes are noisier — which is the
point: the noise arrives before the part is machined.

Two costs are real. Resolution is not free: 85–145 ms to read the topology of a
nine-face plate, and under 16 ms to filter it. And a selector can be
legitimately ambiguous on symmetric geometry, so some documents will need a
position predicate that a human would consider obvious.

## Alternatives rejected

**Persistent topology ids.** Some kernels offer them. KOMPAS `ksEdgeDefinition`
exposes none, and the ids that do exist elsewhere do not survive the
history-editing case this milestone tests.

**Scoring with a threshold.** Picking the best of several candidates is what
produces a plausible-looking wrong part. A build that stops is recoverable; one
that succeeds wrongly is not.

**Selectors resolved once and cached in the document.** The cached index is the
index problem again, one indirection later.
