# ADR-024: A revolve names its axis, in the sketch's own coordinates

## Status

Accepted on 2026-07-31.

## Context

Revolve is the first operation added after the engine changed (ADR-023), and the
first whose contract was designed without a COM probe in front of it. Under
KOMPAS an operation began by measuring which integers the kernel used for it,
because the type libraries export no enumerations; on OpenCascade a revolve is a
documented call with an axis and an angle. All the design effort therefore moves
from what the kernel will accept to what a *document* may say.

It was deliberately not built on KOMPAS. It was next in the plan when ADR-023 was
taken, and specifying it against COM constants would have been a week of work that
ENGINE-MIG-008 then deletes.

The roadmap (P2.2) asks for full and partial angles, one and two directions,
join and cut, an explicit axis reference, and *"automatic axis inference only at
high confidence"*.

## Decision

### The axis is always explicit; there is no inference, at any confidence

The contract has no field for an inferred axis, so the question of how confident
is confident enough never arises.

An inferred axis is a guess about the part that nothing downstream can check. The
profile is valid either way. The build succeeds either way. Every expectation the
document carries — bounding box, body count, hole count — can be satisfied by the
wrong axis, because the difference between a bush and a disc is only which line
the profile went round. Every other guess this service makes is caught by
something: a misread dimension fails the bounding box, a misread contour fails to
close, a constraint that contradicts its coordinates fails the gate. An inferred
axis is caught by nothing, which makes it the one guess that must not be made.

A document that cannot name its axis has not finished reading the drawing, and
saying so is more useful than a part that is plausible.

### The axis lives in sketch coordinates

Two points in the sketch's own plane, or the name of a construction line in the
same sketch — the centre line a drawing usually already has.

A world-space axis would have to be projected onto the sketch plane before it
could be used, and a document whose axis is off that plane would then be silently
corrected onto it rather than refused. Stating the axis where the profile is makes
that failure unrepresentable.

Two points rather than a point and a direction, because two points are what a
drawing gives and there is no normalisation for a reader to get wrong. Either
coordinate may be a parameter, like every other coordinate in a sketch.

### A named centre line is one statement, not two

When the axis is a construction line, the contract checks the name resolves to a
construction *line* of that same sketch. Not a segment of the profile — a drawing
revolving one of its own sides is a document that means something else — and not
a circle, which is construction geometry but not an axis.

The value of naming it is that moving the centre line moves the axis. Two points
copied out of it would be a second place for the same fact to live, and the two
would eventually disagree.

### A profile may touch its axis but never cross it

Touching is how a solid shaft is drawn. Crossing means the two halves sweep
through each other.

This one is geometry — it needs the parameters resolved — so like every other
geometric check it lives in the adapter, in front of the kernel, and not in the
contract. It is checked by sampling the profile's boundary rather than by reading
segment endpoints: an arc can begin and end on one side of the axis and bulge
across it in the middle, and a check on endpoints alone would pass that document.

Measured before deciding: every crossing profile tried — symmetric and offset, a
full turn and a quarter — comes back from OpenCascade as `StdFail_NotDone:
BRep_API: command not done`, raised from inside the kernel with no code, no stage
and no mention of the document. So the kernel does refuse, but not in a way any
caller can act on, and not in a way that survives the worker's typed-error
contract: it escapes as a crash rather than a `FAILED` status. The refusal has to
be ours, and it is `REVOLVE_PROFILE_CROSSES_AXIS`, naming the feature.

### `both_directions` turns the sweep back rather than sweeping twice

A symmetric partial revolve is built as one sweep of the stated angle, rotated
back by half of it. Two sweeps meeting at the profile leave a face between them
for `clean()` to find, and at exactly 180° each way they meet twice.

A full turn in both directions is refused by the contract. Half of 360 each way
is 360: accepting it would change nothing about the solid and everything about
what a reader believes the document says.

## Consequences

**CAD-IR is 1.4, and the addition is additive.** A 1.4 document that does not
revolve is a 1.3 document, so the migration from 1.3 is a relabelling and the
existing fixtures move over unchanged.

**The KOMPAS adapter consumes 1.4 and refuses a revolve by feature type.** It
cannot build one and, being replaced, never will. Refusing every 1.4 document over
an operation the document does not use would strand the only working engine for no
reason; refusing `solid.revolve` by name says what is actually wrong.

**Revolve is not offered to Codex.** The output profile stays where it was. The
drawing agent reads a rectangle and round holes, and a turned profile with its
centre line is not something it can extract — offering the operation would invite a
model to invent one. This is the same position auxiliary planes, face selectors and
constraints are in: reachable through the API, not through a scan.

**Revolve is not behind a per-operation feature flag.** ADR-021 requires one for
every operation, and the requirement is not waived — the build123d worker simply
has no flag surface yet, because flags, the capability manifest and the claim
protocol all belong to the service integration that is ENGINE-MIG-007. Until then
this operation cannot be rolled back without a release, and that is a debt with a
named owner rather than a decision.

## Alternatives rejected

**Infer the axis when confident.** Rejected above: nothing downstream can check
it, so "confident" would be a number nobody could ever calibrate against an
outcome.

**A world-space axis.** Simpler to build with and impossible to validate: it makes
an axis off the sketch plane representable, and the only two options for such a
document are to project it silently or to refuse it after the fact.

**Let the kernel refuse a crossing profile.** It does, with an untyped exception
from inside OpenCascade. A repair loop cannot react to prose, and a worker whose
contract is a typed status cannot honour it by crashing.

**A thin revolve, and up-to-face.** Both are in P2.2 and neither is here. A thin
revolve is a shell operation wearing a revolve's clothes, and "up to face" needs
the selector work that fillet and chamfer will need anyway. Each will arrive with
its own fixture rather than as a flag on this one.
