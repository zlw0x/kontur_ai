# POSTMVP-016: what the cycle may state — acceptance

**Date:** 2026-08-02 · **Result:** PASS for the contract. **The AI runs are owed**, and
the list of them is at the bottom of this document.

The engine declares 33 capabilities. Before this change the drawing cycle could reach two
of them: a plate on XY and holes straight through it. Everything the migration and the
post-MVP operations added — revolve, fillet, chamfer, patterns, mirror, named bodies,
booleans — was reachable only by hand-writing CAD-IR.

`docs/adr/ADR-029-what-the-cycle-may-state.md` is the decision. This is what was built
and what was checked.

## The three walls, told apart

The gap is not one thing, and until the reasons are separated the temptation is to widen
the profile until something breaks.

| wall | what it blocks | can code here settle it? |
|---|---|---|
| **the dialect** | anything whose input has genuinely optional parts — Codex structured output makes every property required | yes, by restructuring |
| **the claim** | anything the reading stage cannot state, because then nothing checks the compilation | yes, by extending the claim |
| **vision** | whether the agent can see the feature on a scan | **no** — only a real run |

## What the profile grew by

`scripts/generate_output_profile.py`, four shapes, every field of each mandatory:

| shape | how it is expressed | why it fits the dialect |
|---|---|---|
| **a blind cut** | `cut.extrude` with `through_all: false` **and** a `distance` | its own branch, not an optional depth: the canonical validator refuses a cut that states both, and the dialect cannot make one optional. Two branches satisfy both rules. |
| **a datum plane** | `datum.plane.offset`, `base: "XY"`, `offset_mm`, `flip` | three inputs, all mandatory |
| **a boss on it** | `solid.extrude` whose sketch is `{"on":"datum","plane":{"result":…}}` | the sketch shape is the existing one with a different plane node |
| **a linear / circular pattern** | `feature.pattern`, `of`, `kind`, spacing-or-step, `count`, `skip: []` | `skip` is present and empty for the same reason `constraints` is |

None of the geometry is new — every one of these is already built by cases in the golden
corpus. What is new is that the *cycle* may ask for them.

The `features` array is now `anyOf` over seven variants (was two). The generated
`schemas/cad-ir-mvp-output.schema.json` grew by 543 lines and `--check` is clean.

## An opening now says how deep it goes

`OpeningClaim.through` is `true`, `false` or absent, in `packages/cad-ir/cad_ir/shape_claim.py`
and in `schemas/drawing-analysis.schema.json` (required, `["boolean","null"]`).

This is not decoration; it is the check that had to arrive *with* blind cuts. Until now
every opening the cycle could produce went through, so a depth could not be got wrong. The
moment a document may stop a hole inside the material, a misread depth is a document that
is valid, builds, and measures exactly what it declares — including its own
`through_hole_count`, which the compilation stage wrote to match the depth it chose. The
drawing is the only thing that says which was meant.

How the built side is derived (`_reaches_through`):

| what the document says | depth on the built side |
|---|---|
| an island in a solid feature's sketch | `True` — an island is a hole through the material that feature makes |
| an island in a cut's sketch | nothing — it is a plug in a pocket, and its depth is the pocket's |
| a cut with `through_all` | `True` |
| a cut with a distance | `False` |
| a subtracted tool body | nothing — its depth is geometry, not a word in the document |

**Nothing is not false** (`_depth_agrees`): a claim that says nothing agrees with either,
and so does a built opening whose depth the document did not state. The check exists for
the drawing that plainly shows a pocket against a document that drills through — not to
punish a reader for admitting the section view did not settle it. `WriteShapeClaim` copies
`through` only when it is a real boolean, so a `null` from the reading stage never arrives
at the claim as `false`.

## Both prompts grew with it

`apps/local-worker/DrawingPipeline.cs`. The analysis prompt asks for `through` per opening
group and spells out that guessing is worse than `null`. The compilation prompt gained the
blind cut ("state one or the other and never both"), the datum-plane-plus-boss pair (with
the instruction to give `offset_mm` the same parameter the base extrusion used, so a boss
moves when the plate gets thicker), both patterns ("the count INCLUDES the hole itself"),
the opening→feature and solids→bosses mapping, and the note that `through_hole_count`
counts only holes that break out.

A profile that grew without the prompt growing is a capability nothing will ever ask for,
so `TheCompilationPromptNamesEveryFeatureTheProfileOffers` renders the prompt and asserts
each offered feature type and both of the new rules appear in it.

### The defect this found

The compilation prompt is a C# raw string literal that spells out nested JSON, so `}}`
occurs in its text: at `$$` it does not compile. Raising it to `$$$` compiles — and then
the first mechanical pass over the *other* literals raised the repair prompt's
placeholders too, inside a `$` literal, where `{{{CadIrVersion}}}` **also compiles** and
renders `{1.7}`.

Neither mistake fails the build. Both are invisible until an AI run reads the nonsense,
which is the most expensive place to find out. `EveryPlaceholderInEveryPromptIsFilledIn`
now renders every prompt through the pipeline and asserts the version arrives as itself,
that no `{1.7}` survives, and that no placeholder name (`CadIrVersion`, `PromptVersion`,
`{candidate}`, `{errorCode}`) reaches the model as text.

## What stays out, and which wall each is behind

- **Fillet and chamfer** — the dialect *and* the claim. A blend's input is an edge selector
  whose predicates are individually optional, and a claim has no word for a rounded corner.
  Either wall alone would be enough.
- **Revolve** — the claim and vision. Expressible in the dialect; a turned profile with its
  centre line is not what the reading stage produces, and `closed_profile` is all a claim
  could say about the result.
- **Booleans and named bodies** — expressible, and nothing a drawing reader would emit. A
  drawing shows a hole; it does not show a tool body subtracted from a target.
- **Face selectors** — the dialect, as before.
- **XZ and YZ base planes** — a second orientation is a second thing to get wrong for a part
  that can always be drawn the first way.

## Tests

| file | what it adds |
|---|---|
| `apps/api/tests/test_cad_ir_mvp_profile.py` | every new shape is built as a document and shown **canonically valid**, not merely profile-valid; a cut stating both a depth and `through_all` is refused; a fillet — canonically valid — is refused by the profile, so the profile is still a narrowing |
| `apps/api/tests/test_shape_claim.py` | a blind hole where the drawing shows one through is caught; a reader that could not see the depth agrees with either; an island in the profile goes through by construction; a patterned pocket counts every instance as blind |
| `apps/local-worker/tests/DrawingPipelineTests.cs` | the two prompt-rendering tests above |

Full run: **702 Python passed, 1 skipped**; .NET **6 + 30 + 31 (4 container skipped, no
`CAD_ENGINE_IMAGE` here) + 41**; `generate_output_profile.py --check`,
`validate_schemas.py` and `check_openapi_compatibility.py` all clean.

## What is owed: the runs, on the machine that is signed in

A contract is not a run. Whether the model actually produces a pattern when it sees a bolt
circle is a question only real Codex can answer, and Codex is authenticated on the trusted
machine, not here. What is delivered above is the schema it will be constrained by, the
prompt that tells it these shapes exist, the claim that will check the answer, and tests
for all three.

Each of the following is one drawing through `DrawingPipeline`, and each has a specific
thing to find out. Recording the answer matters more than the answer being yes.

1. **A plate with a blind pocket.** Does the analysis stage set `through: false`, and does
   the compilation stage then emit a cut with a distance rather than `through_all`? A
   `null` here is a *reading* result, not a failure — note whether the section view in the
   drawing actually settled it.
2. **The same drawing, with the depth deliberately ambiguous.** Does the reader say `null`
   rather than guessing? This is the one behaviour the prompt asks for that no schema can
   enforce.
3. **A plate with a pad on it.** Does `solids` come back 2, and does compilation produce the
   datum-plane-plus-boss pair — with `offset_mm` referencing the thickness parameter rather
   than a literal? The literal is the likely failure and it is invisible until someone
   changes the thickness.
4. **A bolt circle, six holes.** Does compilation emit one hole and a circular pattern of
   count 6, or six spelled-out cuts? Both build the same part; only the first states the
   count the claim can disagree with. If it spells them out, the prompt needs a firmer
   instruction, not the profile.
5. **A bolt circle where the reading is wrong** (e.g. the drawing says 6 and the analysis
   says 8). Does `validate --claim` produce `OPENING_COUNT`, and does the repair loop react
   to the code rather than to prose?
6. **A misread depth**, forced: hand-edit the analysis to `through: true` on a drawing whose
   pocket is blind, and confirm the disagreement names the depth. This exercises the new
   check without needing the model to make the mistake.

For each: keep the analysis JSON, the compiled CAD-IR, the validation report and whether
the part is right. A run that fails is worth more than one that passes — it says which of
the three walls the cycle is actually standing at.
