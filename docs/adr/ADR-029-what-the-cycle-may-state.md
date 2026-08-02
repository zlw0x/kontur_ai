# ADR-029: what the cycle may state, and why the profile grew by exactly this much

## Status

Accepted on 2026-08-02.

## Context

The engine declares 33 capabilities. The cycle — a drawing in, a model out — could ask
for two of them: a plate on XY and holes straight through it. Everything else built since
the migration (revolve, blends, patterns, named bodies, booleans) is reachable only
through the manual API.

That gap is not an oversight, and it is not one thing. Three different walls hold
different operations back, and until they are told apart the temptation is to widen the
profile until something breaks.

**The dialect.** The Codex structured-output schema has no optional properties: every
object must list all of them as required. An operation whose input has genuinely optional
parts cannot be offered, because the model would be forced to emit them and the canonical
validator would then refuse the result — a planar face has no radius, a straight edge has
no radius either.

**The claim.** A shape claim says what the part *is*. If the reading stage cannot state a
thing, the compilation stage building it is unchecked: there is nothing for
`disagreements` to compare. Offering an operation the claim is blind to trades a
narrow-but-checked cycle for a wide-but-unchecked one.

**Vision.** Whether a drawing agent can actually see the feature on a scan. This is the
only one of the three that cannot be settled by writing code here.

## Decision

### The profile grows to what the claim can already check

Four shapes are added, and they have one thing in common: every field of each is
mandatory, so the dialect states them without forcing an invention.

- **A blind cut** — `through_all: false` with a distance. Its own branch rather than an
  optional depth, because the contract refuses a cut that states both and the dialect
  cannot make one optional. Two branches satisfy both rules at once.
- **A datum plane and a boss on it** — a plane offset from XY, and a solid extrude whose
  sketch sits on it. This is the shape of every plate with a pad on it, and the claim has
  counted lumps of material since ADR-025.
- **A linear pattern and a circular one** — the count a drawing states, which the claim
  compares against (ADR-027).

The geometry is not new: every one of these is already built by cases in the golden
corpus. What is new is that the *cycle* may ask for them.

### An opening now says how deep it goes

`OpeningClaim.through` is `true`, `false` or nothing.

This is not decoration; it is the check that has to arrive *with* blind cuts. Until now
every opening the cycle could produce went through, so a depth could not be got wrong.
The moment a document may stop a hole inside the material, a misread depth becomes a
document that is valid, builds, and measures exactly what it declares — including its own
`through_hole_count`, which the compilation stage wrote to match the depth it chose. The
drawing is the only thing that says which was meant.

**Nothing is not false.** A reader that could not settle the depth says nothing, and a
claim that says nothing agrees with either. The check exists for the drawing that plainly
shows a pocket against a document that drills through — not to punish a reader for
admitting the section view did not settle it. The same rule holds on the other side: a
subtracted tool body's depth is geometry rather than a word in the document, so the
document says nothing about it either.

### What still stays out, and which wall each one is behind

- **Fillet and chamfer** — the dialect *and* the claim. A blend's input is an edge
  selector whose predicates are individually optional, and a claim has no word for a
  rounded corner. Both walls; either alone would be enough.
- **Revolve** — the claim and vision. It is expressible in the dialect, and a turned
  profile with its centre line is not something the reading stage produces, and
  `closed_profile` is all a claim could say about the result.
- **Booleans and named bodies** — expressible, and nothing a drawing reader would emit. A
  drawing shows a hole; it does not show a tool body subtracted from a target.
- **Face selectors** — the dialect, as before.
- **XZ and YZ base planes** — this profile extrudes +Z from XY, and a second orientation
  is a second thing to get wrong for a part that can always be drawn the first way.

## Consequences

A drawing showing a pocket, a pad or a bolt circle can now be compiled, and each of those
is checked by something that did not write it: the pocket by the claim's depth, the pad by
the claim's solid count, the bolt circle by the claim's opening count.

The prompts grew with the profile, and one of them found a defect while doing it. The
compilation prompt is a C# raw string literal that spells out nested JSON, so `}}` occurs
in its text and it needs `$$$` where the others need `$$`. Getting that wrong does not
fail to compile — it renders `{1.7}` where `1.7` was meant, or the literal characters
`{{CadIrVersion}}`. Both are invisible until an AI run reads the nonsense, which is the
most expensive place to find out, so a test now renders every prompt through the pipeline
and asserts no placeholder survives.

**This ADR is a contract, and a contract is not a run.** Whether the model actually
produces a pattern when it sees a bolt circle is a question only a real Codex run can
answer, and those happen on the machine that is signed in. What is delivered here is: the
schema it will be constrained by, the prompt that tells it these shapes exist, the claim
that will check the answer, and tests for all three. The run, and what it teaches, belong
to that machine.
