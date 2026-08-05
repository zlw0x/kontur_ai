# ADR-035: a draft names the walls, and the face it is measured from

**Status:** accepted · **Date:** 2026-08-04 · **CAD-IR:** 1.12

## Context

`taper_deg` has drafted an extrusion since CAD-IR 1.10 (ADR-033), and POSTMVP-024
measured that for a plain boss it is not merely close to a face-draft but identical: a
40 × 40 square drawn in 10° over 20 mm is **26 689.1761 mm³** whether the extrusion
tapers or the walls are drafted afterwards.

That measurement is why this operation was refused when it was first proposed, and the
refusal was the third of its kind:

| | asked for | answer at the time |
|---|---|---|
| POSTMVP-011 | hole families | composition — a through hole is a cut with `through_all` |
| POSTMVP-022 | rib | composition — a closed contour extruded both ways |
| POSTMVP-024 | draft | `taper_deg` for the common case |

Those three arrived at a rule this decision has to answer to: **an operation earns its
place in CAD-IR only when it says something composition cannot.**

## Decision

`feature.draft` is added, because two things were then measured that composition cannot
reach — and the second is the sharper one.

**Some walls and not others.** A taper draws in every wall its extrusion makes. Drafting
the pair of walls facing x on that same block, and leaving the pair facing y standing,
gives **29 178.7680 mm³** — closed form `a·h·(a − h·tanθ)`, exact — with the bounding box
unchanged, because the undrafted pair is still where the drawing put it. No sequence of
extrusions produces it: a second extrusion adds material, and this takes it off two sides
of one lump.

**A body no extrusion made.** Draft the outer wall of a turned tube, Ø20 bore, Ø40
outside, 20 tall: **18 849.5559 mm³ becomes 14 678.4446**, the frustum less the bore,
exact to the last digit the kernel prints. `taper_deg` cannot reach a revolved body at
all, and a boolean's result even less.

### The faces are named by selector, with a cardinality that cannot match nothing

ADR-019's rule, and ADR-026's. Third operation to carry the second one, and the reason is
unchanged: a draft that treated no faces is a successful feature that did not happen, and
**nothing downstream sees it.** A draft changes no face count (six before, six after,
measured), no body count, and — on the walls it does not touch — no bounding box.

### The neutral face is named too, and its normal is turned inward

The kernel takes a *plane*: the section lying in it keeps its size and everything else
moves. Which plane decides the part — the same block drafted +10° about its base is
26 689.1761 mm³ and about its top 37 974.1029, both valid solids of the right height. A
drawing says which end holds the dimension, so the document names the face, exactly as an
asymmetric chamfer names the face its first distance is measured from.

Then one thing had to be decided rather than passed through. `Plane(face)` takes the
face's **outward** normal, and a base face looks down and out of the part, so a positive
angle read straight off it narrows the part *downwards* — the opposite of what a drawing
dimensioning the base means. Measured both ways:

| neutral face | normal as-is | normal turned inward |
|---|---|---|
| the base | 37 974.1029 | **26 689.1761** |
| the top | 37 974.1029 | **26 689.1761** |

Turned inward, the named face holds its size and the part narrows away from it — and it
is *the same number whichever end the document names*. That is what makes the rule
stateable at all, and it is why the engine turns the normal rather than the document
choosing a sign for each face.

### The sign means what `taper_deg`'s means

Positive draws the walls in as they leave the neutral face; negative lets them out. Not
"draft", which means opposite things on a boss and in a cavity — ADR-033's rule, kept
deliberately, so the two operations cannot disagree about the same drawing.

### The engine tries and then checks

The contract refuses a zero angle (a feature that does nothing wearing the name of one
that does) and anything at or past 89°. Everything between is the kernel's to judge,
because how steep is too steep depends on how far the walls reach. Measured on the block,
whose section closes at 45°:

| angle | what comes back |
|---|---|
| 40° | 12 659.0858 mm³, a valid solid — smaller, and correct |
| **45°** | 10 666.6667 mm³, the pyramid, **reporting `is_valid` false** |
| 60° and past | `Standard_ConstructionError`, **with an empty message** |

Two firsts in one operation. It is the first time this kernel has volunteered that its
own answer is wrong rather than returning something plausible — every earlier finding
(the shell with no room, the tight sweep, the over-steep taper, the `until` spike) came
back claiming validity. And the bare throw carries *no text at all*, which is the shape
ENGINE-MIG-006 recorded for the revolve's `StdFail_NotDone`: without a wrap it escapes
the worker's typed-error contract as a crash. Both become `DRAFT_TOO_STEEP`.

`DRAFT_MOVED_NOTHING` is the fifth instance of the older pattern, and is there because
the shell needed it: a result identical to the input is a feature the delivered part does
not have.

## Consequences

The engine declares **43 capabilities**. `feature.draft` is `experimental`, not `beta`:
the corpus has the two shapes that earned it and no more, and a status is a claim about
coverage rather than about confidence.

**The claim needed nothing new, and that is worth saying.** `ShapeClaim.draft` names the
parameter holding the angle (ADR-033's amendment), and it now reads either operation —
because a drawing marks an angle on a wall, and which of the two the compilation reached
for is not something the drawing says. A document that drafts by the *negation* of the
claimed parameter is caught on the new operation exactly as on `taper_deg`.

**The cycle cannot ask for one yet**, and the ordering is the same as the shell's: the
contract can build it, the corpus checks it, and the output profile stays where it is
until a run says whether an agent reads a draft angle off a scan. The upright-wall
selection POSTMVP-024 asked for is what the offer would need, and it now has an operation
to be handed to — which it did not before this.

**What is still not expressible**: a neutral plane the part does not have a face in. That
would be a coordinate, and a drawing that means one says so with a dimension to a datum
the reading stage has no word for.
