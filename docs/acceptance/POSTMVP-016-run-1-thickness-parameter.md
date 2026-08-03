# Run 1 of the nine: the claim refuses a correct part

**Date:** 2026-08-03 · **Result:** FAIL, and the failure is in the check rather
than in the part.

The first of the runs POSTMVP-016 says are owed, on the machine that is signed
in. It did not get as far as the question it was meant to answer, because it
found something larger on the way: **the shape claim contradicts a document that
is right.**

## What was run

`scripts/make_acceptance_drawing.py` — the 60 × 30 × 8 plate with two Ø5 through
holes, the same drawing every acceptance run has used.

```bash
dotnet run --project apps/local-worker -- analyze-drawing .local/run-016-1
```

## The reading stage did its job

It asked one clarification — where the hole centres sit — and stated the shape:

```json
{"profile": "rectangle",
 "openings": [{"kind": "round", "count": 2, "through": true}],
 "solids": 1, "thickness_parameter": "plate_thickness",
 "wall_parameter": null, "blends": []}
```

That is correct, and it answers half of scenario 6 in the affirmative: on a
drawing whose holes go through, the reader writes `through: true` rather than
staying silent. `wall_parameter` and `blends` are empty, so the words the claim
gained in POSTMVP-017 and 019 are not invented where nothing calls for them.

## Then the claim refused the compilation

```text
SHAPE_CLAIM_CONTRADICTED
  code      THICKNESS_PARAMETER
  claimed   plate_thickness
  built     param.thickness
```

Both name the 8 mm thickness. The document is otherwise exactly the part the
drawing shows: a 60 × 30 × 8 plate, two Ø5 holes 30 apart, 15 from each edge.
Nothing about the geometry is wrong.

**The two names were chosen independently by two different model calls.** The
reading stage invents an id for the thickness while describing the drawing; the
compilation stage invents its own while writing the document. Nothing makes them
agree, and nothing ever did — so the check fires on correct work, which is the
most expensive way for a check to be wrong. A false refusal does not cost a
rebuild; it costs an order that should have shipped.

### Why no test caught it

Every fixture in the corpus is hand-written, and a hand-written fixture carries a
claim and a document written by the same hand in the same sitting. They agree by
construction. The disagreement needs two independent authors, which is exactly
what a real run has and no fixture does.

This is the second time in this project that a check was correct in every test
and wrong on the first real run. It is worth stating as a pattern: a test whose
two sides come from one author cannot find a disagreement between two authors.

## Then the repairs made it worse

The loop reacted as designed — twice — and both attempts came back with a
*different* and worse failure:

```text
CAD_IR_INVALID  FEATURE_DEPENDENCY_MISSING@$.features[2].inputs.source_body
```

Told that a parameter had the wrong name, the agent restructured the features and
broke the dependency graph, then repeated the same mistake on the second attempt.
Both candidates are in `.local/run-016-1/output/` as `cad-ir-repair-1.json` and
`cad-ir-repair-2.json`.

That is worth noticing on its own: a repair prompt that names a small, local
disagreement can provoke a large, non-local rewrite. The loop bounded it at two,
which is the bound doing its job — but the first repair should not have needed
bounding.

## What to do about it

The claim is right to name the thickness and right not to name a number:
ADR-025's rule holds, and doubling every dimension must still satisfy the claim.
What is missing is that the two stages have no shared vocabulary.

The compilation stage **already receives the analysis**, and the analysis
**already contains `shape.thickness_parameter`**. So the cheapest fix is also the
one that makes the check mean more rather than less: tell the compilation to use
the id the reading gave. The check then asks "did you use the name you were
given", which is answerable, and a document that ignores it is genuinely
suspicious rather than merely differently spelt.

Two alternatives were considered and are worse. Comparing the parameter's *value*
instead of its name breaks ADR-025 on purpose — the claim would then be satisfied
by a part of the wrong size. Dropping `thickness_parameter` from the claim
removes the only thing that ties the reading's idea of thickness to the
document's.

## What this run did not answer

Nothing about scenarios 1 to 5. They need drawings that do not exist yet — a
blind pocket, an ambiguous depth, a pad, a bolt circle, and a bolt circle read
wrongly — and running them against a cycle that refuses a correct plate would
measure the wrong thing.

The order that follows from this run: fix the vocabulary, re-run this drawing,
and only then generate the other five.
