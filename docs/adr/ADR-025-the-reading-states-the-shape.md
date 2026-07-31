# ADR-025: the stage that reads the drawing states the shape, and trusted code checks the document against it

## Status

Accepted on 2026-07-31.

## Context

Every check the pipeline has is a check of the document against itself.

The canonical validator says the CAD-IR is well formed. The capability gate says
this engine can build it. The geometric checks in front of the kernel say the
contours close and the islands lie inside the outline. The expectations say the
built solid measures what the document declared. All of them pass on a document
that is internally perfect and is not the part on the drawing.

That failure has a shape. The reading stage sees a lever plate — a stadium
outline, two holes, a pin — and the compilation stage writes a rectangle with two
holes. The rectangle's bounding box matches the one the document declares,
because the document declared it. Two holes are found, because two were drilled.
The STEP file is exact, manifold, and wrong. Nothing in the pipeline can say so,
and nothing could, because every statement it has to compare was written by the
same stage that wrote the geometry.

Before this, the contract between the two AI stages carried only numbers:
`parameters`, `questions`, a prose `summary`. The shape first existed inside
CAD-IR. So the reading stage could not be wrong about the shape in any way a
machine could see, and could not ask about it either — a drawing whose outline was
genuinely ambiguous produced a confident guess, because the only thing the schema
let it be unsure about was a dimension.

## Decision

### The reading stage says what the part is, before any geometry exists

`drawing-analysis.schema.json` gains a required `shape`: the outline as one of
five kinds, the openings grouped by kind and counted, how many solid bodies, and
the id of the parameter holding the thickness. That is a **shape claim** — a
statement of what the part *is*.

It is not a second document and not an instruction. It says a rectangle; it does
not say where the corners are.

### A claim carries kinds and counts, and never a coordinate

This is the line that makes the claim worth having. A claim that carried
dimensions would be derived from the same reading of the same numbers the
parameters already carry, and comparing it with the document would compare the
document with itself again — the thing that does not work.

So doubling every dimension in a document leaves its shape claim satisfied. A
size is checked by the bounding-box expectation, against a number the drawing
stated. The claim checks the one thing no measurement can: that this is the right
part.

### Trusted code does the comparing

`packages/cad-ir/cad_ir/shape_claim.py` is a pure function of a validated
document and a claim, returning a list of disagreements. No AI is asked whether
the document matches the claim, because a stage that could be wrong about the
shape can be wrong about whether it was wrong about the shape.

It is in `cad-ir` rather than in the engine: it compares two statements and
touches no kernel. The engine's command line exposes it —
`cad_worker validate --claim FILE` — because the repair loop needs the answer from
the process that would do the accepting.

### A disagreement is typed, and names both sides

`PROFILE_KIND`, `SOLID_COUNT`, `OPENING_COUNT`, `THICKNESS_PARAMETER`, `NO_SOLID`,
each with what was claimed and what the document builds:

```text
the drawing was read as a rectangle outline, which is 4 straight segment(s) and
0 arc(s); feature.plate spells out 2 and 2
```

A repair prompt reacts to the code; a person reads the detail. A single boolean
would send the loop after the wrong thing.

### The claim is a statement about the part, not about how to write CAD-IR

The first version of the check required a rectangle to be written as a
`RectangleContour`, and immediately contradicted `constrained-plate`, which spells
its rectangle out as four named segments because its constraints reference the
sides. That is a correct document, and refusing it would make the claim a style
rule.

So a named kind accepts either its own contour type or a path, and where the
signature is unambiguous the path is checked: a rectangle is four straight
segments, a slot is two segments and two arcs. Which is exactly what still catches
the stadium claimed as a rectangle.

The same reasoning applies to holes. `plate-with-hole` cuts its hole and
`constrained-plate` uses an island in the base sketch; both are two holes on a
drawing, and both count.

### An absent claim checks nothing

Nothing but a drawing produces a claim. A document written by hand, a fixture, an
analysis artifact from before this existed — all validate exactly as they did.
Making `shape` a reason nothing builds would turn a field that did not exist last
week into an outage.

### Only the claim crosses to the engine

The worker extracts `result.shape` into `output/shape-claim.json` and mounts that
file, read-only, at its own path inside the container. The engine is never handed
the drawing analysis: the confidences, the page references, the summary and the
questions are about a drawing it does not read, and the text in them came off an
untrusted scan.

## Consequences

A misread outline is now a refusal with a code, at the same point in the pipeline
as a schema violation, before a build is paid for. The repair loop gets it as one
more typed failure and reacts to it the way it reacts to the others.

The reading stage can now be unsure about shape. A question with
`parameter_id: "shape"` asks about the outline or the openings, and the job stops
for the user like any other unanswered question, instead of guessing.

Both prompts stop naming one shape class. Before, the analysis prompt asked for
"one centered rectangle and zero or more circular through-holes" — the MVP's
geometry written into the instruction. The engine has built contour profiles,
slots, polygons, arcs, islands, bosses and revolves for several milestones; the
prompt was the narrowest part of the system. What the drawing agent can actually
recognise off a scan is still narrower than the schema now allows, and that is a
vision problem — but the contract no longer caps it.

The claim can be wrong. A reading that says rectangle about a stadium and a
compilation that faithfully builds the rectangle will now disagree with each
other and the job will fail — correctly, because one of the two is wrong and
neither can be trusted to say which. What the claim buys is that the failure is
visible; it does not buy knowing which stage misread. That is what the questions
are for.

Two costs are real. The check is only as good as its vocabulary: five profile
kinds and five opening kinds, and anything else is `closed_profile`, about which
the check says nothing but the solid count and the thickness. And every new
operation has to decide what it means for a claim — a fillet does not change what
the part is, a pattern changes how many openings there are.
