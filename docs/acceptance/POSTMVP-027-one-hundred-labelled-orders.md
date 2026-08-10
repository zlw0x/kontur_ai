# A hundred labelled orders

**Date:** 2026-08-09/10 · **Machine:** the one Codex is signed in on ·
**Corpus:** `scripts/make_labelled_drawings.py`, seed 20260809 ·
**Harness:** `scripts/run_labelled_orders.py`, scored by `scripts/score_labelled_orders.py`

Everything before this milestone was about the service not breaking. This is about
whether it works, and there was no other way to find out.

A hundred drawings across four families, each with what it must produce written down
before the model saw it, put through the real service — quarantine, sanitizer,
reading, compilation, build, verification — with clarification questions answered
from the drawing's own dimensions. Three hours of wall clock, 107 questions, and a
median of 86 seconds an order.

## The three numbers

| | |
|---|---|
| delivered a STEP and an STL | **91 / 100** |
| measured what the drawing says | **89 / 91** |
| wrong, and nothing said so | **2** |

By family:

| family | n | delivered | correct | wrong |
|---|---|---|---|---|
| `plate` — a row of through holes | 25 | 22 | **22** | 0 |
| `pocket` — a blind pocket | 25 | 23 | **23** | 0 |
| `flange` — a bore and a bolt circle | 25 | 25 | **25** | 0 |
| `pad` — a plate with a boss | 25 | 21 | 19 | **2** |

Every expected number is closed-form from the sheet — `w·h·t − n·π·r²·t` for a
plate, `π(R² − r²)t − k·π·ρ²·t` for a flange — and every measured number comes from
reopening the exported files. Nothing here is the engine agreeing with itself.

## What the corpus found in the service

### The claim could not add up two groups of one kind

The largest finding, and it was invisible to nine earlier acceptance runs because
none of them built a part with two hole sizes.

Every flange was refused, 25 of 25, with the same two clauses:

```text
the drawing was read as 1 round opening(s) and the document builds 5;
the drawing was read as 4 round opening(s) and the document builds 5
```

Both compare a declared group against the same total. The reading was right — a bore
and a bolt circle are two groups because that is how a reader names them. The
document was right: 1 + 4 = 5. `_opening_disagreements` matched each declared group
against **every** built opening of its kind rather than against its share, so a
reading that splits openings of one kind into two groups could never be satisfied.

Any flange, any plate with two hole sizes, any bracket with mounting holes and a
cable hole. A quarter of this corpus, failing a hundred percent of the time.

Fixed by grouping on kind **and** depth before comparing — not kind alone, because a
hole that goes through and one that stops are a different part. Re-run afterwards:

```text
flange   before the fix    2 / 25 delivered
flange   after the fix    25 / 25 delivered, 25 / 25 correct
```

### Every refusal named its reason

Nine orders were not delivered and **all nine said why** — there is no silent
non-delivery in this corpus at all.

| | |
|---|---|
| `CAD_IR_INVALID`, all six citing `PARAMETER_DRIVES_NOTHING` | 6 |
| `SHAPE_CLAIM_CONTRADICTED` | 3 |

`PARAMETER_DRIVES_NOTHING` is ADR-034's rule doing exactly what it was written for:
the model declared dimensions and drove nothing with them. `SHAPE_CLAIM_CONTRADICTED`
on three non-flange orders is the claim catching a real disagreement between the
reading and the compilation.

### Two silent wrong parts, and both are one shape

| | |
|---|---|
| `pad-002` | 90 × 40 × **20** against 90 × 40 × 15; volume 56000 against 38000 |
| `pad-062` | outline **92 × 52** against 90 × 50, **volume exact** |

`pad-062` is the more interesting: the material is right to the milligram and it is
in the wrong place — a boss hanging over the edge of its plate.

Both are the same mechanism, and it is the one this repository has described and not
previously measured on a corpus: **the claim compares compilation against reading and
never reading against the drawing.** The reading said what the compilation built, so
nothing disagreed with anything.

Two out of a hundred, and both in the one family whose part is made of two pieces.

### The compiler never reaches for `new_body`

Twenty-one times a plate with a boss came back as **one** body rather than two.

That is not a defect — `solids` (what a reader counts) and `body_count` (what the
file contains) are different questions on purpose, and ADR-028's bracket fixture
declares two bodies while satisfying a claim of three solids. A plate and its boss
fused into one body is the same part.

What it is, is a ratio of 21 out of 21: the compiler does not use `new_body` when a
drawing shows two lumps of material, ever. This is the fourth wall from POSTMVP-016
again — an operation can be offered, readable and **unnecessary** — and it is now
measured on a family rather than noticed once on a bolt circle.

### The reading asks answerable questions

**107 questions, none unanswerable from the sheet.** The harness matches a question
to a dimension the drawing states and counts the ones it cannot match; that count is
zero. Sixty-six orders needed one clarification round and thirty-four needed none.

This was the number most likely to embarrass the service and it is the cleanest one
in the run.

## What the corpus found in itself

Twice, and both times before anything was published — which is the reason the runner
records the geometry it measured rather than only a verdict. A wrong rule can be
corrected and everything rescored without spending a single model call.

**`solid_count` is not `solids`.** The first scorer compared what a reader counts on
a drawing against how many bodies the delivered file contains. Four pad cases whose
bounding box and volume were exact to the last digit were scored WRONG for being one
body instead of two. Under the corrected rule the silent-wrong count for the first
twenty-one cases went from five to one.

**A mesh bounding box is a faceted approximation.** The second scorer flagged a
flange for measuring 79.9751 across an 80 mm disc — 0.025 mm, which is tessellation.
`verify.py` has carried `MESH_CHORD_TOLERANCE_MM = 0.05` since the KOMPAS acceptance
runs, with the note *"an 80 mm part measured 79.898 in its mesh"*. The harness now
uses the engine's constant rather than one of its own, so the two cannot drift.

Both corrections moved the headline number, and neither was found by reading the
harness. They were found by looking at cases the harness called failures and asking
whether the part was actually wrong.

## What this says about the pilot

**Three of the four shapes work.** `plate`, `pocket` and — after the fix — `flange`
delivered 70 of 75 and were correct 70 of 70. A blind pocket reading `through: false`
correctly, 23 times out of 23, is the result that was least safe to assume: a misread
depth produces a document that is valid, builds, and measures exactly what it
declares.

**The failure mode that matters is narrow and it is real.** Two parts in a hundred
were wrong with nothing said, both in the family whose part is two pieces. That is
what the moderation queue is for, and it is the measurement that justifies keeping
`automatic_acceptance` off: an operator looking at 100 orders would have caught both,
and no automatic check in the service would have.

**Nothing failed quietly.** Ninety-eight of a hundred orders either delivered a
correct part or said what was wrong with a typed code. For a pilot behind an operator
queue that is a service that can be used.

## What is not measured here

Four families of prismatic part, drawn by one generator in one style. Nothing here
says how the reading behaves on a photographed sheet, a hand sketch, a drawing with a
title block, or a part outside these four shapes — and the fourth wall above is a
statement about *this* corpus's drawings.

The two `pad` failures are two samples. They agree with each other about the
mechanism and they are not enough to say how often that mechanism fires.
