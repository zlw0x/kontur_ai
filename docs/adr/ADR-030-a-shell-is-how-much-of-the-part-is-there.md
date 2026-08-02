# ADR-030: a shell is how much of the part is there

## Status

Accepted on 2026-08-02. CAD-IR 1.8.

## Context

Every operation in the contract so far answers the same question: what shape is the
part? An extrude states an outline, a cut states an opening, a pattern states a count,
a blend states an edge treatment. A shape claim (ADR-025) is built to check exactly
that question, and it does.

A shell answers a different one. Hollow a 100 × 60 × 40 enclosure with a 3 mm wall and
compare it against the solid block it came from:

| | solid | shelled |
|---|---|---|
| outline | rectangle | rectangle |
| openings | none | none |
| solids | 1 | 1 |
| bounding box | 100 × 60 × 40 | 100 × 60 × 40 |
| through holes | 0 | 0 |
| **volume** | **240 000 mm³** | **52 188 mm³** |

Every check the document can carry agrees. The parts differ by a factor of four in
material, and one of them is not the drawing. That is the whole reason this ADR exists
and it shapes every decision in it.

## Decision

### The operation

`feature.shell` names the faces it **removes**, a wall thickness, and a direction.

```json
{"type": "feature.shell",
 "inputs": {"faces": {"kind": "face", "cardinality": "exactly_one", "where": {…}},
            "thickness": {"parameter": "p_wall"},
            "direction": "inward"}}
```

The faces named are the ones the part is *open* at, not the ones it keeps. A drawing of
an enclosure says "open at the top"; listing the other five sides would be five more
chances to name one wrong.

### A shell may not declare a cardinality that opens nothing

`all` and `zero_or_one` are refused, as they are for an edge blend since ADR-026 — and
the reason here is stronger than the blend's. A blend of zero edges is a feature that
silently does not happen. A shell of zero faces is a **different operation**:

```
offset(box, -3, openings=[top])   52 188 mm³, bounding box unchanged     a hollow box
offset(box, -3, openings=[])     172 584 mm³ = 94 × 54 × 34              a smaller solid
```

Both measured on build123d 0.11.1, and kept as a test rather than a comment
(`test_an_offset_that_opens_nothing_shrinks_the_solid_instead_of_hollowing_it`). A
document whose selector matched no faces does not get the part it asked for minus one
step; it gets a solid one, 6 mm smaller in every direction, which nothing but a bounding
box catches.

### A wall that leaves no cavity is refused after the fact

The second measured surprise, and the reason this operation checks its own result:

```
offset(box, -30, openings=[top])   240 000 mm³ — the original solid, and no error
```

OpenCascade does not refuse a wall thicker than the material has room for. It returns
the body it was given, whole. Bounding box, body count, hole count and manifold checks
all pass, and the delivered part is a billet.

So the engine compares the volume before and after and refuses with `SHELL_NO_CAVITY`.
It is a check on the *result*, not a rule about the input, because a pre-check would
have to guess: 25 mm walls in a 40 mm-deep box are fine when the top is open (the cavity
is 15 mm deep) and not fine when it is closed. The kernel is the only thing that knows,
so the kernel is asked and then checked.

### The direction is stated

`inward` keeps the drawing's outside size and eats into the part. `outward` keeps the
inside and grows past the original surface — the same faces, the same thickness, and a
part 6 mm bigger in x and y. The kernel's own way of saying this is the sign of a
number, and a sign is not something a document should be able to leave out.

Two capability keys, `feature.shell.inward` and `feature.shell.outward`, for the same
reason the two chamfer forms have two: an operator who has seen a part come out too big
in every direction wants to stop that one alone.

### What is not offered, and why

- **A wall straddling the surface** ("both", in the roadmap's words). OpenCascade's solid
  offset has no such mode, and composing one out of two offsets would put a size in the
  document that no drawing states — a 3 mm wall centred on the outline is a 1.5 mm change
  to a dimension somebody measured.
- **A choice of transition.** `Kind.INTERSECTION` is fixed: the walls are extended until
  they meet, which is what a shell means in every CAD system. The alternative, `Kind.ARC`,
  rounds every inner corner at a radius the document never stated — and an unstated radius
  is precisely what ADR-026 refuses to let a blend invent.

### The claim gains one word: `wall`

`ShapeClaim.wall` is the id of the parameter holding the wall thickness, or nothing.

It is the claim's first statement about *how much of the part is there* rather than what
shape it is, and it is here because nothing else can catch a document that forgot to
shell. The naming rule from ADR-025 is unchanged: the claim carries the parameter's
**name**, never its value. A size is checked by an expectation against a number the
drawing stated; what the claim adds is that the dimension has a name at all, and that
the part is hollow.

Three things it catches, in order of what they cost: a document with no shell at all, a
wall built from a literal (the dimension lost its name), and a wall built from the wrong
parameter (it moves when something else is edited).

**Silence is still not a claim**, the rule POSTMVP-016 set for `OpeningClaim.through`. A
reader who did not see a wall says nothing, and a document that shells anyway is not
contradicted. The check exists for the drawing that plainly gives a wall thickness
against a document that ignored it — not to punish a reader for what a section view did
not show.

Everything else the claim counts is deliberately blind to a shell: the outline, the
openings and the solid count are the same before and after, and stating otherwise would
make a correct document wrong.

### A pattern cannot repeat a shell

A pattern re-runs the operation that made material, at an offset. A shell made none — it
modified the body that was already there — so there is no copy of it to place, and
applying it again to the same solid is either a no-op or nonsense depending on how the
kernel felt.

This was already half-decided: the validator refused a pattern of a *datum plane* by
name, and left a pattern of a blend to fail later in the engine as an unsupported tool.
It is now one rule — a pattern repeats an extrude, a revolve, a cut or a pattern — which
covers the shell and fixes the blend at the same time.

## Consequences

**The cycle cannot ask for a shell yet, and that is the expected order.** A shell's input
is a face selector, so it is behind the dialect wall ADR-029 named: Codex structured
output has no optional properties, and a selector's predicates are individually optional.
The claim grows first and the output profile follows when the dialect allows — which is
the ordering ADR-029 argued for, applied. Until then a shell reaches the engine through
the manual API and `validate --claim`.

**Both keys are `beta` on arrival.** POSTMVP-013/014 decided that the corpus is what
promotes an operation, and the criterion is whether the corpus varies what the operation
decides: five positive cases across two shapes, two thicknesses, one and two open faces
and both directions, four negatives with named codes, and one case built twice for
determinism. `feature.chamfer.asymmetric` stays experimental for the opposite reason —
nothing varies the only thing it decides.

**Two version defects surfaced on the way**, both of the same kind — a fact written down
twice and allowed to disagree.

`MIGRATABLE_VERSIONS` listed 1.6 and the normalizer's branch did not, so a 1.6 document
was told by the validator to normalise first and then refused by the normalizer as
unsupported, by the same build on the same run. It had been that way since 1.7 landed.
The relabel-only set is now derived from the migratable list, and a test walks every
version in it.

`generate_output_profile.py` hard-coded the CAD-IR version it constrains the model to
emit. A profile pinned to a version the contract has moved past would make every
compilation produce a document the validator refuses — total rather than partial
failure. It reads `CAD_IR_VERSION` now.
