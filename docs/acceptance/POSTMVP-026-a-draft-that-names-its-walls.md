# POSTMVP-026: a draft that names its walls — acceptance

**Date:** 2026-08-04 · **Result:** PASS. CAD-IR **1.12**, 43 capabilities, 62 positive and
36 negative corpus cases, 1 035 Python tests and 159 .NET.

`docs/adr/ADR-035-*` is the decision. This is what was measured and what it cost.

## The operation had to argue its way in

Three milestones refused an operation on the grounds that composition already said it, and
POSTMVP-024 refused *this* one eight months' worth of decisions ago in project time — with
the measurement that makes the refusal look right: a 40 × 40 square drawn in 10° over
20 mm is **26 689.1761 mm³** whether the extrusion tapers or the walls are drafted after
the fact. Identical, not close.

So the case for adding it is not "the kernel can do it". It is two things composition
cannot reach, both measured before a line of contract was written:

| | | closed form |
|---|---|---|
| two walls of four | **29 178.7680 mm³** | `a·h·(a − h·tanθ)` |
| the outer wall of a turned tube | **14 678.4446 mm³** | frustum `πh/3·(R² + R·R₂ + R₂²)` less bore `πr²h` |

Both exact. The first keeps the bounding box, because the two walls the drawing leaves
alone still stand where it put them — and there is no sequence of extrusions that produces
it, since a second extrusion adds material and this takes it off two sides of one lump.
The second is the sharper one: `taper_deg` is part of an extrusion, so it cannot reach a
revolved body at all.

Both are corpus cases (`draft-two-walls`, `draft-a-turned-wall`), and so is the one that is
*not* an argument for the operation — `draft-all-walls`, which exists so that if the two
routes ever stop agreeing, one of them is wrong.

## The decision the measurement forced

`Plane(face)` takes the face's **outward** normal. A base face looks down and out of the
part, so a positive angle read straight off it narrows the part downwards and widens it
going up — the opposite of what a drawing dimensioning the base means. The corpus caught
it immediately: the first run of all three cases came back with a bounding box of
47.0531 against the 40 the document declared.

| neutral face | normal as-is | normal turned inward |
|---|---|---|
| the base | 37 974.1029 | **26 689.1761** |
| the top | 37 974.1029 | **26 689.1761** |

Turning it inward gives the named face its size back *and* the same answer whichever end
the document names, which is what makes the rule sayable in one sentence: **positive draws
the walls in as they leave the neutral face.** `test_the_named_face_holds_its_size_whichever_end_it_is`
is that table as an assertion.

## Two firsts in the failure modes

Measured on the block, whose 40 mm section closes at 45° over 20 mm:

```
40°   12 659.0858 mm³   valid solid, smaller, correct
45°   10 666.6667 mm³   the pyramid — and is_valid is FALSE
60°   Standard_ConstructionError, with an empty message
```

**The kernel says its own answer is wrong.** Every earlier finding of this kind came back
claiming validity — the shell with no room, the sweep round too tight a bend, the taper
past the closing point, `until`'s spike into open space. This is the first time
OpenCascade has volunteered it, and the check that reads `is_valid` is the cheapest one in
the engine.

**And past that it throws with no text.** `Standard_ConstructionError` carrying an empty
message is the shape ENGINE-MIG-006 recorded for the revolve's `StdFail_NotDone`: without
a wrap it escapes the worker's typed-error contract as a crash rather than a refusal. Both
become `DRAFT_TOO_STEEP`, and `DRAFT_MOVED_NOTHING` covers the fifth instance of the older
pattern — a result identical to the input.

## A selector trap, recorded rather than worked around

Naming two adjacent walls with `extreme_along axis.x / minimum` matches **three** of the
four: the two walls facing y span the whole width, so their own minimum touches it too.
That is the selector reading correctly, and it is the same trap the shell cases record for
z. The corpus names the pair by their normal instead, and the comment says why.

## What the bump cost, and one thing it caught

CAD-IR 1.11 → 1.12 renamed eleven fixtures and touched **no test source**, which is what
`tests/cad_ir_fixtures.py` and `CadIr.FileSuffix` were built for two sessions ago. One
literal did survive, in the spelling the guard could not see:

```csharp
Assert.Contains("canonical CAD-IR 1.11", compilation);
```

A version inside a *sentence* rather than inside a filename. It had passed every bump until
the prompt it checks started saying 1.12. The guard now refuses a quoted string that
carries the current version on a line mentioning CAD-IR — only the **current** one, because
an older version written down deliberately is a statement rather than a stale copy: a
worker manifest declaring 0.1.0, a launcher test proving an engine's own 1.7 is echoed
back, a document refused for saying 1.5. Those mean what they say. Two genuinely stale
copies were found with it (`cad_ir_versions=["1.11"]`) and now derive.

## Tests

| suite | result |
|---|---|
| Python | **1 035 passed, 1 skipped** |
| .NET | 6 + 89 + 31 + 33 = **159 passed**, 4 container tests skipped (no `CAD_ENGINE_IMAGE`) |
| corpus | 62 positive, 36 negative; every capability covered |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

39 new: 28 in `test_cad_ir_draft.py` for the contract and what the claim makes of it,
11 in `test_drafts.py` on real geometry.

## What is not in

**The cycle cannot ask for a draft.** The output profile is unchanged, and the ordering is
the shell's from ADR-030: contract and corpus first, offer when a run says whether an agent
reads a draft angle off a scan. The upright-wall selection POSTMVP-024 asked for is what
the offer needs, and it now has an operation to be handed to — which is precisely what it
lacked this morning.

**`feature.draft` is `experimental`, not `beta`.** The corpus has the two shapes that
earned it and no more, and a status is a claim about coverage rather than about confidence.

**A neutral plane the part has no face in** stays out. That is a coordinate, and a drawing
that means one says so with a dimension to a datum the reading stage has no word for.
