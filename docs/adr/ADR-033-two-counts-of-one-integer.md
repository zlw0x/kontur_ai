# ADR-033: two counts of one integer, and two ways an extrusion travels

## Status

Accepted on 2026-08-02. CAD-IR 1.10.

## Context

Every check in this service so far compares something the document **stated** against
something the delivered files **measure**: a bounding box, a body count, a hole count, a
face count of one surface kind. That is ADR-018's rule and it is a good one — but it has
a floor. A document that states nothing about a thing cannot have that thing checked, and
the reading stage's vocabulary is narrow.

Gate P4 asks for a *topology oracle*: something that checks the structure of the result
rather than its size. The interesting question is what it could compare against, given
that the drawing agent will never state a face count.

The answer turned out to need no document at all.

## Decision, part one: the genus, computed twice

Every build delivers two files written by two different exporters — a STEP holding a
B-rep and an STL holding triangles. The **genus** of a solid, how many handles it has,
can be computed from either:

- from the B-rep, by the Euler–Poincaré formula `V − E + F = 2(S − G) + (L − F)`;
- from the mesh, by Euler's formula over triangles, which the verifier has done since
  the multi-body work.

Neither number comes from the document. They must agree, and when they do not, something
is wrong that neither alone reveals. That check is now run on every build
(`topology_agrees_with_mesh`) and keyed as `validate.topology`.

**The `L` term is why this works, and a previous attempt missed it.** `_genus`'s own
docstring records trying the naive `V − E + F = 2 − 2G` on the B-rep and getting 0 for a
plate that plainly had a hole in it — a B-rep counts a full circle as one edge with one
vertex. The general formula counts *loops*, and the face carrying a hole has two. With
the loops counted the B-rep gives the right answer: measured before this was written, a
box is 0, one hole is 1, three holes are 3, a tube is 1, a shelled box is 0.

**What it catches** is the failure that looks like success, and the self-intersecting
sweep of ADR-031 is the specimen:

| | the STEP says | the STL says |
|---|---|---|
| a Ø16 pipe round a 4 mm bend | a tidy genus-0 solid, 4 faces, `is_valid` true | genus −45, 69 open edges |

Neither half is obviously wrong on its own. Plenty of correct parts are genus 0, and a
mesh fault normally reads as an exporter problem. It is the *mismatch* that says the
solid is not one.

The corpus also states `(faces, edges, vertices)` where the drawing settles them, and
that arithmetic is closed-form like the volume: a box is 6, 12, 8, and every round
through hole adds **one face, three edges and two vertices** — two circles and the seam
OpenCascade puts on a closed cylinder. That seam is the migration's own recorded cost
(ADR-023), and it is now a number a check reads rather than a note in a document.

## Decision, part two: how an extrusion travels

Two modes on `solid.extrude` and `cut.extrude`, both one kernel argument and both with
closed-form arithmetic.

**`both_directions` states the total.** Half each way. This is the reading a revolve's
`both_directions` has had since 1.4, and the alternative — the distance meaning "each
way" — would build a part twice as thick as the one described and make a claimed
thickness parameter name half of it. The volume is the same either way; only the position
says which happened.

**`taper_deg` narrows the extrusion as it travels along `direction`.** Positive narrows,
negative widens, and that is the only rule.

It is tempting to make it mean "draft", which is about withdrawal and therefore means
opposite things on a boss and in a cavity — a helpful translation that would have the
engine flip the sign for a cut. That is refused for the reason ADR-026 refused letting the
kernel pick which face a chamfer measures from: **the document should say what the
geometry does, and a sign the document cannot see is a sign somebody else chose.** A
moulded pocket writes a negative taper, explicitly.

The volume of a tapered extrusion is the prismatoid rule, `h/6 × (A_base + 4·A_mid +
A_top)`, exact for a linear taper — measured against the kernel at 3°, 5° and 10° to six
decimal places before it was written down.

### Two things a taper may not be combined with

A `through_all` cut may declare neither. It has no second side to reach, and its far end
is measured against the body it cuts — so a tapered one would be tapered over a length
the *engine* chose rather than the document. Both refused by the contract.

### A draft steep enough to close the section is refused after the fact

The measurement that earns the check: a 20 × 20 pad drafted 45° over 40 mm comes back as
a **pyramid 10 mm tall**. The section closes at 10, OpenCascade stops there, reports one
valid solid of five faces and a plausible volume, and says nothing. The document asked
for 40.

So the engine compares the built height along the plane's own normal against the stated
distance and refuses with `EXTRUDE_DRAFT_TOO_STEEP`. A pre-check would have to offset the
profile inward and ask whether anything is left, which is another kernel behaviour to
trust; the kernel is asked and then checked, as it is for a shell (ADR-030).

## Consequences

The engine declares **42 capabilities**, 41 beta. The corpus is **59 positive and 31
negative** cases, 16 of them stating their topology.

**Neither addition reaches the drawing cycle, and neither should yet.** `both_directions`
and `taper_deg` are modelling choices rather than things a drawing states in words the
reading stage has: a part is not drawn "symmetric about a plane", it is drawn with
dimensions, and a draft angle is a note the claim has no word for. Offering them would be
the trade ADR-029 forbids. The topology oracle needs no offer at all — it runs on every
build, including every build the cycle already produces.

**This is the third silent-wrong-part finding in three milestones**, and they are the same
shape every time: OpenCascade returns *something* valid rather than refusing, and only a
measurement of the result catches it. A shell with no room returns the original solid; a
sweep round too tight a bend returns a self-intersecting one; a draft past the closing
point returns a stump. Each is now a named code. The pattern is worth stating on its own:
**this kernel's failure mode is a plausible answer, so every operation that can be
over-driven gets a post-check comparing the result against what was asked.**

## Amendment, 2026-08-04: the claim gained the word

The sentence above — "a draft angle is a note the claim has no word for" — was true when
it was written and is the reason `taper_deg` was not offered to the drawing cycle. It is
now false: `ShapeClaim.draft` names the parameter holding the angle, checked as
`DRAFT_PARAMETER`, and it lands on the same terms `wall` did in ADR-030. **The claim's
word arrives before the offer, and that ordering is deliberate**: what the reading stage
can state is settled first, and the output profile follows when the rest of ADR-029's
walls come down.

The measurement that decides its shape is that a draft is *worse* hidden than a shell.
A 20 × 20 sketch extruded 10 mm:

| taper | volume | x span | z span |
|---|---|---|---|
| none | 4 000.000 | ±10.000 | 0 … 10 |
| +20° | 2 720.752 | **±10.000** | 0 … 10 |
| −20° | 5 632.513 | ±13.640 | 0 … 10 |

A narrowing draft — the one a cast part actually shows — keeps the sketch as the widest
section, so the outline, the openings, the solid count *and the bounding box* are all the
square part's. Only the volume knows, and the volume expectation is written by the same
stage that chose the taper. A shell at least differs in material and shows a face the
outside does not have; an omitted draft differs in nothing anything else measures.

**The claim says the name and not the direction, and that is measured rather than
assumed.** The kernel was asked which way a taper leans when the extrusion runs backwards:

```
amount=+10 taper=+20   x=[-10.000,+10.000]   far face 161.814 mm²
amount=-10 taper=+20   x=[-10.000,+10.000]   far face 161.814 mm²
```

A positive taper narrows **away from the sketch plane** in both cases, so `direction`
cannot flip the physical meaning. The sign lives in the parameter's value, and a canonical
`Scalar` is a float or a reference with no arithmetic between them — so the compilation
stage cannot negate an angle it was given. A claimed "narrows" could therefore only
disagree with the reading stage's own number, which is a stage checking itself and not a
check (ADR-018). One consequence is kept as a check anyway: a named angle that resolves to
**0°** is square walls with a name on them, and is refused.

What the claim still cannot see is *which* feature leans. A drawing that drafts a pocket
against a document that drafts the outer wall by the right parameter agrees here. That is
recorded rather than pretended away, and it is the same limit `wall` has — a claim of
kinds and counts cannot say where.
