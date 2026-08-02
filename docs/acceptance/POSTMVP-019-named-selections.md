# POSTMVP-019: named selections, and the dialect wall — acceptance

**Date:** 2026-08-02 · **Result:** PASS for the contract. The cycle reaches **ten**
capabilities instead of six. **The AI runs are owed**, and three more are added to the
list.

`docs/adr/ADR-032-the-dialect-wall-was-lower-than-it-looked.md` is the decision.

## What the wall actually was

ADR-029 said a selector could not be offered because rule 4 of the Codex dialect —
every object lists all its properties as required — would force the model to emit every
predicate, and the canonical validator would then refuse the result.

That is true of offering the predicate **vocabulary**. Rule 4 governs the properties a
schema *declares*, and nothing obliges the profile to declare all of them:

```json
{"where": {"curve_type": "line", "direction_parallel_to": "axis.z", "convexity": "convex"}}
```

Three predicates declared, three required, dialect-legal — and canonically valid,
because the predicates left out are optional in the contract. Checked both ways before
anything else was written:

```
edge ok: {'curve_type': 'line', 'direction_parallel_to': 'axis.z', 'convexity': 'convex'}
face ok: {'surface_type': 'planar', 'normal': {'parallel_to': 'axis.z', 'direction': 'positive'}}
```

The wall was a misreading. Three operations sat behind it for a milestone.

## What the profile now offers

Three **selections** — fixed predicate sets with nothing to choose but a count:

| selection | what it names | why it names only that |
|---|---|---|
| `outer_corner_edges` | the upright corners of the outline | `convex` excludes the inside of a hole, which is where "round the corners" would otherwise land |
| `bore_rim_edges` | the rims where holes break out of the top face | `circle` excludes the outline's upright edges; topmost-along-Z excludes the far side |
| `top_face` | the face a hollow part is open at | planar with a +Z normal is one face on every part this profile builds |

`from_result` is the constant `body.main`. Every predicate is a constant. **The model
composes nothing** — that is the decision, not a side effect: a selection is written here
against the topology this engine builds and is exercised by the corpus, where a composed
one would be a selector nobody has ever resolved against a real part.

Four features follow: a corner fillet, a corner chamfer, a bore chamfer and a shell. All
four were verified profile-valid, canonically valid **and buildable** before the tests
were written:

```
fillet           profile-valid, canonical-valid, volume 47742.478
corner chamfer   profile-valid, canonical-valid, volume 47784.000
bore chamfer     profile-valid, canonical-valid, volume 46596.886
shell            profile-valid, canonical-valid, volume 13040.000
```

Two constants inside them:

- **a blend's cardinality is `exactly_n` and nothing else** — a blend may not declare one
  that permits zero matches (ADR-026), and a count in the document is what the claim can
  disagree with. One cardinality satisfies both;
- **a shell is `inward` only** — an outward wall changes the part's overall size and the
  reading stage has no word for that (ADR-030).

## The claim grew to match

Offering an operation the claim is blind to trades a narrow-but-checked cycle for a
wide-but-unchecked one, which is ADR-029's own rule. So:

**`ShapeClaim.blends`** — kind and count, checked by `BLEND_COUNT`. It catches the case
nothing else can: a plate with square corners where the drawing shows R5 has the same
outline, the same openings, the same one solid and the same bounding box. `surface_face_count`
could see a blend, but the compilation stage writes that expectation itself, so it agrees
with whatever that stage chose.

A count, never a radius. The count is comparable only because the profile emits
`exactly_n`; a hand-written `one_or_more` states no number and therefore agrees with
either — the same silence rule as `OpeningClaim.through` and `ShapeClaim.wall`.

**`wall_parameter` reached the reading stage.** `ShapeClaim.wall` has existed since
ADR-030 and nothing emitted it, because the cycle could not build a shell. Now the
drawing-analysis schema and the reading prompt ask for it, and `WriteShapeClaim` copies
it — only when the reader named one.

## What each addition is checked by

| what | checked by |
|---|---|
| each new shape is canonically valid | `test_each_shape_the_profile_grew_is_canonically_valid`, four new cases |
| the model may not compose a selector | `test_the_profile_offers_named_selections_and_not_composed_selectors` — a predicate dropped, added or changed is refused while staying canonically valid |
| a blend states its count | `test_a_blend_the_profile_offers_must_state_how_many_edges_it_treats` — all four other cardinalities refused |
| the shell is inward | `test_the_shell_the_profile_offers_is_inward_only` |
| a document that forgot the fillet | `test_a_drawing_with_rounded_corners_and_a_document_without_is_caught` |
| a chamfer where the drawing rounds | `test_a_fillet_and_a_chamfer_are_counted_apart` |
| silence on both sides | `test_a_reader_who_marked_no_blend...`, `test_a_blend_whose_count_the_document_never_stated...`, `NothingSeenIsNothingClaimed` |
| the reading prompt asks for every claim field | `TheAnalysisPromptAsksForEveryPartOfTheShapeTheClaimChecks` |
| the wall and the blends reach the engine | `TheWallAndTheBlendsTheDrawingWasReadAsAreHandedToTheEngine` |
| the compilation prompt spells the selections out verbatim | `TheCompilationPromptNamesEveryFeatureTheProfileOffers` |

## The prompt defect, one level deeper

Spelling a selection out verbatim puts `}}}` in the compilation prompt, and at `$$$`
that is the interpolation terminator — it does not compile. Raising to `$$$$` would work
and would make the next nested object break it again, so the JSON examples are formatted
with their closing braces on their own lines instead.

The prompt-rendering test from POSTMVP-016 is what makes hand-formatting safe: a
placeholder that fails to render is caught before an AI run reads the nonsense.

## Tests

| suite | result |
|---|---|
| Python | **803 passed, 1 skipped** |
| .NET | 6 + 30 + 44 + 31 (4 container tests skipped — no `CAD_ENGINE_IMAGE` here) |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

## Where the three walls stand now

- **Dialect** — constraints and driving dimensions, and only these. A constraint's `to`
  and `axis` are optional in a way no fixed choice resolves; pinning them would make
  every constraint binary and axial, which is a different contract rather than a subset.
- **Claim** — nothing, for what is now offered.
- **Vision** — revolve, sweep, loft, named bodies, booleans. **This is the only wall that
  matters now**, and no code here settles it.

## What is owed: three more runs

Added to the six in `docs/acceptance/POSTMVP-016-*.md`, on the machine Codex is signed
in on:

7. **A plate with "R5" against its four corners.** Does the reading stage emit
   `blends: [{"kind":"fillet","count":4}]`, and does compilation emit a fillet whose
   selection states 4? A count of 2 or a missing feature is now a `BLEND_COUNT`
   disagreement rather than a silent wrong part.
8. **A bore with a "2×45°" note on its rim.** Chamfer, count 1, on the *rim* selection
   rather than the corner one. Picking the wrong selection is the likely failure and it
   builds fine — a chamfer on the outline instead of the bore.
9. **A housing with a wall thickness.** Does `wall_parameter` come back named, and does
   compilation shell the part with that parameter rather than a literal? A document that
   builds it solid is the failure `ShapeClaim.wall` exists for, and it weighs four times
   what the drawing says.

For each: keep the analysis JSON, the compiled CAD-IR, the validation report and whether
the part is right.
