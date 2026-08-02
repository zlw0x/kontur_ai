# ADR-032: the dialect wall was lower than it looked

## Status

Accepted on 2026-08-02. Supersedes the dialect half of ADR-029.

## Context

ADR-029 named three walls holding operations out of the drawing cycle: the **dialect**
(Codex structured output has no optional properties), the **claim** (an operation the
reading stage cannot state is an operation nothing checks), and **vision** (whether the
agent can see the feature on a scan).

The dialect wall was described like this:

> A blend's input is an edge selector whose predicates are individually optional, so
> rule 4 would force the model to emit all of them, and the canonical validator then
> rejects the result because a straight edge has no radius.

That is true of offering the **predicate vocabulary**. It is not true of offering a
selector, and the difference was never tested.

Rule 4 says every object lists *its own* properties as required. It says nothing about
which properties a schema has to declare. A profile that declares three predicates and
requires all three is dialect-legal; the predicates it leaves out are optional in the
canonical model, so the result is canonically valid too. Both halves hold at once:

```json
{"where": {"curve_type": "line", "direction_parallel_to": "axis.z",
           "convexity": "convex"}}
```

Every property required. Nothing invented. Canonically valid. The wall was a
misreading, and three operations sat behind it for a milestone.

## Decision

### The profile offers named selections, not selectors

Three of them, each a fixed predicate set with nothing to choose but a count:

| selection | what it names | how |
|---|---|---|
| `outer_corner_edges` | the upright corners of the outline | line, parallel to Z, **convex** — which is what excludes the inside of a hole |
| `bore_rim_edges` | the rims where holes break out of the top | circle, topmost along Z — the far side is not among them |
| `top_face` | the face a hollow part is open at | planar, normal +Z |

`from_result` is the constant `body.main`: the profile builds exactly one body, so
naming it is not a choice. Every predicate is a constant. The model composes nothing.

That last point is the decision, not a side effect. A selection is written **here**,
against the topology this engine builds, and is exercised by the golden corpus. A model
free to compose predicates would be free to write a selector nobody has ever resolved
against a real part — and a selector that resolves to the wrong edges produces a part of
exactly the right size with the round in the wrong place (ADR-026).

### Four operations follow

`feature.fillet` and `feature.chamfer` on the corners, `feature.chamfer` on a bore rim,
and `feature.shell` opening the top face. The engine has built all four since
POSTMVP-009 and POSTMVP-017; what is new is that the cycle may ask.

Two constants are worth naming:

- **A blend's cardinality is `exactly_n` and nothing else.** Two rules meet there: a
  blend may not declare a cardinality that permits zero matches (ADR-026), and a count
  in the document is what a shape claim can disagree with. `exactly_n` is the only
  cardinality that satisfies both.
- **A shell is `inward` only.** An outward wall changes the part's overall size, and the
  reading stage has no word for that (ADR-030). Offering it would be a size the drawing
  states and the claim cannot check.

### The claim grows to match, because otherwise this trade is the bad one

ADR-029's rule stands: offering an operation the claim is blind to trades a
narrow-but-checked cycle for a wide-but-unchecked one. So two words arrive with the
four operations.

**`ShapeClaim.blends`** — kind (`fillet` or `chamfer`) and count. A blend changes nothing
else the claim counts: a plate with square corners where the drawing shows R5 has the
same outline, the same openings, the same one solid and the same bounding box. Until now
`surface_face_count` was the only thing that could see a blend, and the compilation stage
writes that expectation itself, so it agrees with whatever that stage chose.

A count, never a radius — ADR-025's rule holds. How big the round is is a size, and a
size is checked by an expectation against a number the drawing stated.

The count is comparable only because the profile emits `exactly_n`. A hand-written
document saying `one_or_more` has not stated a number, and a claim cannot disagree with a
number nobody wrote — so that agrees with either, the same silence rule as
`OpeningClaim.through` and `ShapeClaim.wall`.

**`wall_parameter` reaches the reading stage.** `ShapeClaim.wall` has existed since
ADR-030 and nothing emitted it, because the cycle could not build a shell. It can now, so
the drawing-analysis schema and the reading prompt ask for it, and `WriteShapeClaim`
carries it — only when the reader named one, because a `null` arriving as a wall would
claim the part is hollow on behalf of somebody who did not say so.

## Consequences

The cycle now reaches **ten** of the engine's 39 capabilities, up from six: a plate, a
through hole, a blind pocket, a datum plane, a boss, two patterns, a fillet, a chamfer
and a shell. Everything the claim can check is now on offer, which was the standard
ADR-029 set.

**What is left behind each wall has changed shape.**

- *Dialect*: constraints and driving dimensions, and only these. A constraint's `to` and
  `axis` are optional in a way no fixed choice resolves — pinning them would make every
  constraint binary and axial, which is a different contract rather than a subset of one.
- *Claim*: nothing, for the operations now offered. Revolve, sweep, loft and the booleans
  remain unstatable, but they are behind vision as well.
- *Vision*: revolve, sweep, loft, named bodies and booleans. Whether an agent can read a
  turned section and its centre line, or a path with bend radii on an elevation, off a
  scan. **This is now the only wall that matters**, and no code here settles it.

**A contract is still not a run**, and this ADR does not change that. Whether the model
emits a fillet with the right count when it sees "R5 (4×)" needs real Codex on the
trusted machine. What is added to the list of owed runs
(`docs/acceptance/POSTMVP-016-*.md`) is: a plate with rounded corners, a bore with a
chamfer note, and a housing with a wall thickness — three drawings, three claim fields
that either fire or do not.

**The prompt found the same defect again, one level deeper.** Spelling a selection out
verbatim puts `}}}` in the compilation prompt, which at `$$$` is the interpolation
terminator — it does not compile. Raising to `$$$$` would work and would make the next
nested object break it again, so the JSON examples are formatted with their closing
braces on separate lines instead. The prompt-rendering test from POSTMVP-016 is what
makes that safe to do by hand.
