# ADR-039: CAD-IR 1.13 — an extrusion may name the face it stops at

**Date:** 2026-08-10 · **Status:** accepted ·
**Investigation:** `docs/TASK-POSTMVP-P3-2-up-to-a-face.md` (2026-08-04)

## The fork, and why it closed this way

Two ways to let a document say how far an extrusion goes when the drawing gives no
number:

- `ScalarDifference` — arithmetic in the contract, with a rule separating a
  difference the drawing states from one the model invented;
- `extrude(until_face=<selector>)` — the document names a face and **trusted code
  computes the distance**.

The second, and the reason is that only one of them has measurements behind it.

`ScalarDifference` is an idea. `until_face` was designed against the kernel over
sixteen cases and reproduces the kernel's own answer to `0.000e+00` where the
kernel is right. Between a contract change nobody has run and one whose arithmetic
was checked against the thing it replaces, the corpus rule this repository already
follows decides it: **a capability is promoted by cases.**

`ScalarDifference` is not refused, it is unbuilt. If a drawing turns up whose reach
genuinely is the difference of two stated dimensions and no face expresses it, that
is the evidence for it, and this ADR is not in its way.

## The kernel's own answer is not used anywhere

`Solid.extrude_until` is not called from this repository, and the investigation is
why. Sixteen cases against a 40 × 40 × 10 block: two correct, three raising, three
**succeeding and returning the wrong part**.

The worst of the three is the one that decided it. A profile inside the material,
extruded `+Z` "until the next face", should stop 5 mm away at the top. It returns
one valid solid of 21 244.56 mm³ reaching **z = 62.45** — which is
`5 + √(40² + 40² + 10²)`, the trial extrusion's own length, and has nothing to do
with the drawing. A cut "to the next surface" can remove **nothing** and report
success.

That is the fourth instance of the rule ADR-033 states: *this kernel's failure mode
is a plausible answer.*

### And no post-check could have caught them

Every over-driven operation before this is caught by comparing the result against a
number the document stated — `SHELL_NO_CAVITY` compares volume before and after,
`SWEEP_BEND_TIGHTER_THAN_PROFILE` compares a radius against the profile's reach,
`EXTRUDE_DRAFT_TOO_STEEP` compares the built height against the stated distance.

**`until` states no number at all.** That is its entire appeal — the drawing says
"up to the web" rather than "17.5 mm" — and it is exactly why the pattern that
caught the last three defects has nothing to compare with. A document using it
cannot be checked, by construction.

## Decision

```
until_face: FaceSelector    # on solid.extrude and cut.extrude
```

and one division in trusted code:

```
reach = ((p − o) · n) / (d · n)
```

Then the engine extrudes by `reach` — the operation it has performed since
ENGINE-MIG-003, with its existing post-checks and its existing determinism.

**What this buys is a number.** The reach is something the manifest can record, the
corpus can state in closed form, and an expectation can measure against. `until`
never could, because the distance was the kernel's secret.

A **mode** on the extrusions that exist, not a new feature type — the reason
POSTMVP-011 refused `feature.hole`: another type is another thing to validate saying
what the contract already says.

### The refusals, and what each one is instead of

Five, and every one is a measured case rather than a defensive check.

**Exactly one face** (`UNTIL_FACE_NOT_ONE`). Sharper than ADR-026's blend rule: a
blend that matched nothing silently did not happen, and **two faces here are two
different reaches** — the engine would compute one and build a part whose length
nobody chose.

**Planar only** (`UNTIL_FACE_NOT_PLANAR`). A cylinder's normal depends where on it
you ask, so "the distance to it" is a length the drawing did not state.

**Not parallel to the travel** (`UNTIL_FACE_PARALLEL`). There is no intersection to
compute. The kernel's answer is a null-shape `ValueError`, which reads like a broken
document rather than an impossible one.

**A positive reach** (`UNTIL_FACE_BEHIND`). The kernel's answer to a face behind the
profile is to reverse, which is a second way to state a direction the document
already states. Refusing keeps `direction` meaning what it says.

**A reach that is not zero** (`UNTIL_FACE_COINCIDENT`). The profile is already on the
face. This is the single geometry that made the original investigation think
`extrude_until` was broken in general — it is one document, and now it is one
refusal.

And two mutual exclusions in the contract itself: an extrusion states **a distance
or a face, never both** (the contract already refuses `through_all` beside a distance
for the same reason), and an extrusion up to a face carries **no taper and no
`both_directions`** — the first because a drafted extrusion's far end would then be a
width at a length nobody stated (ADR-033's argument), the second because half a reach
in each direction is not a thing a drawing says.

## What is deliberately not caught

A named plane is infinite, so the arithmetic always answers. What it cannot know is
whether the extrusion actually **lands** on the face rather than passing beside it.

It does not need to: the part comes back in two pieces, and `body_count` — an
expectation documents already carry — sees it. Measured in the investigation: 2
solids, x reaching 105 on a 40 mm block.

That is the same division of labour as everywhere else here. Trusted code refuses
what it can decide; an expectation catches what only the built part can show.

## What it is measured by

The golden corpus gains one positive and three negatives:

- `cut-until-underside` — a bore driven from the base plane to the plate's own top
  face. The reach is the plate's thickness, so the volume is
  `60 × 40 × 8 − π × 7² × 8`, closed-form, and matched on the real kernel.
- `until-face-coincident` — the geometry that raises `Extrusion is None` in the
  kernel, refused here with a code.
- `until-face-two-faces` — `one_or_more`, refused by the contract.
- `until-face-and-a-distance` — both, refused by the contract.

A contract-level refusal arrives as `SCHEMA_INVALID` with the rule in the message,
which is this repository's existing convention (the shell's cardinality refusal is
the same). The code is written into the message as well, because the loop decides on
the code and the compiling agent reads the text.

`feature.extrude.until_face` is declared **`experimental`**, not `beta`. The corpus
rule promotes an operation by cases, and this one has the cases written here and no
run behind it.

## What it unblocks, and what it does not

**Rib (P3.2)** becomes an ordinary extrusion of a web profile up to a named face,
with the rib thickness as `both_directions` on a different axis — which the contract
has done since 1.10. Only the reach was missing.

**Up-to-face extrusion (P2.1)** is the same feature under its other name; they were
listed separately and are one contract change.

**The claim needs nothing new.** A boss up to a face is a lump of material, counted
as one solid exactly as today.

**The cycle cannot ask for it**, and that ordering is deliberate. A face selector is
dialect-legal since ADR-032 only as a *named selection written in this repository*,
and "the face this rib lands on" is not a constant. So this arrives the way the shell
did: an operation the corpus builds and the drawing cycle cannot yet reach.
