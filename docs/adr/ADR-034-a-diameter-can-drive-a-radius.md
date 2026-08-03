# ADR-034: CAD-IR 1.11 — a scalar may be divided and negated

**Date:** 2026-08-03 · **Status:** accepted · **Supersedes in part:** ADR-018's
"there is no expression language"

## What happened

A customer's drawing went through the web path and came back as the wrong part,
with every check green.

The drawing says Ø44. The document declared `bushing_outer_radius: 44` — the
*diameter* value under a radius name — extruded a circle of that radius, and
restated 88 in its own expectation so the bounding-box check agreed. A Ø88 solid
cylinder: no bore, no flange, no taper, and seven of its nine parameters driving
nothing at all.

The reading was not at fault. Every number on the drawing — 44, 11.5, 40, 27,
3.3, 30, 4.5 — reached a parameter correctly. The geometry was, and not through
carelessness: **a canonical `Scalar` was `float | ParameterRef` with no
arithmetic**, so a diameter could not drive a radius. The model's only way to
write a radius was to write a number, and once it did, the drawing's number and
the building number were two copies with one author between them.

`lever-plate` had shown the same thing without a customer attached:
`param.cap_radius` = 15 cannot produce y = +15 *and* y = −15, so one side of a
symmetric outline had to be a literal.

## Decision

`Scalar` becomes `float | ParameterRef | ScalarQuotient | ScalarNegation`.

```json
{"divide": {"parameter": "param.outer_diameter"}, "by": 2}
{"negate": {"parameter": "param.cap_radius"}}
```

And `PARAMETER_DRIVES_NOTHING`: a document may not declare a `length` or `angle`
parameter that no feature references.

**These are one decision.** Arithmetic gives a document a way to reference the
drawing's number; the rule makes it do so. The rule was written, measured and
reverted earlier the same day precisely because the contract gave parameters
nowhere to go — enforcing it then would have forced documents to delete
dimensions read off the drawing with a citation.

### Structured nodes, not the string form

ADR-018 removed `{"expr": "param.width * 2"}` and the reasoning holds: a string
makes the trust boundary parse text a model wrote, and after that the schema
guarantees nothing about what is inside it. The evaluator that parsed those
strings still exists for 0.1.0 documents and is deliberately not reused.

A node is checked by the schema. There is no parser on the canonical path.

### Two operations, not four

Multiplication and addition were considered and left out. The cases that were
*measured* are exactly two — a diameter driving a radius, and a parameter driving
a symmetric pair — and every further operation is another thing to validate,
another line in the prompt, and another way for a document to state a relationship
nobody drew.

### The divisor is a constant

`by` is a number, never a parameter. One dimension divided by another is a
relationship the drawing did not state; a document that computes one is inventing
geometry rather than recording it. Zero and non-finite are refused by the model.

Nesting is bounded at three. The nodes recurse, a document is written by a model,
and nothing else stops a thousand-deep tower from being schema-valid.

## What it cost

Less than expected, because of two things that were already right.

`Parameters.resolve` is the only place in the engine where a `Scalar` becomes a
float, and it serves all twenty-four call sites. Two new branches there, and
nothing above changed.

The canonical JSON Schema is generated from the pydantic model, and the Codex
output profile refers to `scalar` by `$ref` in about twenty places — so the
profile grew by one `anyOf` member and two `$defs`. Two defs rather than one node
with an operator field, because negation takes one operand and division takes two
and rule 4 forbids an optional property: the same shape as `cut_extrusion` versus
`blind_cut_extrusion` in ADR-029.

Ten `isinstance(x, ParameterRef)` guards needed a third branch, and four fixtures
were rewritten rather than exempted — `lever-plate` is why `negate` exists.
`param.length` = 80 was deleted from it: an overall size belongs in the
expectation that compares it against the built part, where it already was.

## What it is measured by

- A Ø80 flange with six Ø6 holes on a Ø60 PCD, **with no dimensional literal in
  it** — every radius derived by division — builds to **38855.2179 mm³** against
  a closed form of 38855.2179. The same number POSTMVP-019's run 5 measured from
  a document full of literals.
- **The bushing document that shipped a Ø88 part is now refused**, with five
  `PARAMETER_DRIVES_NOTHING`.

## What the first real document found in the rule

The bushing drawing was re-run once 1.11 shipped, and the model did use the
arithmetic: `{"divide": {"parameter": "param.main_outer_diameter"}, "by": 2}`.
The bounding box came back **[44, 44, 44]** against yesterday's [88, 88, 44], and
the part gained the through bore it had silently lost. The reading stage improved
with it — two questions instead of one, both choices, the second asking whether
the central opening goes through.

And the document still passed while building almost nothing. Thirteen dimensions
declared, two used by the geometry, and the other ten referenced from **eight
construction circles that no constraint mentioned**. Every parameter technically
driving something; every one of the ten driving nothing.

So `PARAMETER_DRIVES_NOTHING` does not count construction. Construction exists to
be referenced by a constraint and builds nothing itself, and excluding it is
precise rather than blunt: no fixture in this repository has a parameter living
only there, while refusing *unreferenced construction* outright would refuse three
that legitimately carry an axis line nothing constrains.

That sharpening was found by a run and not by reasoning, which is the third time
this rule has been changed by measurement: written, reverted for want of
arithmetic, restored with it, and now narrowed.

## What it does not fix

The reading stage said `openings: []` for a bushing that is mostly bore. That is
vision, and the claim cannot catch it by construction: the claim catches
compilation disagreeing with reading, never reading disagreeing with the drawing.

Nor does it give the model trigonometry, so a bolt circle's hole centres are still
literals — only the first one, which lies on the axis, can be derived. Whether
that matters is a question for a run rather than for a contract.

## The claim lost a branch

A thickness or a wall "built from a literal" no longer reaches `shape_claim`: the
validator refuses such a document a step earlier, and says it of every dimension
rather than only of that one. What the claim still owns is a dimension built from
the **wrong** parameter — a document the validator is right to accept and only a
reader can contradict.
