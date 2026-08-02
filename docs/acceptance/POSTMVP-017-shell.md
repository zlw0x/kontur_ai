# POSTMVP-017: shell — acceptance

**Date:** 2026-08-02 · **Result:** PASS. CAD-IR 1.8, two capabilities at `beta`, 47
positive and 20 negative corpus cases, 743 Python tests passing.

`docs/adr/ADR-030-a-shell-is-how-much-of-the-part-is-there.md` is the decision. This is
what was built and what each part of it is checked by.

## What it is

`feature.shell` — the faces the part is open at, a wall thickness, and a direction.
First operation in the contract that changes *how much of the part is there* rather than
what shape it is.

```json
{"id": "feature.hollow", "type": "feature.shell",
 "depends_on": ["feature.corners"], "produces": [],
 "inputs": {"faces": {"id": "selector.open_top", "kind": "face",
                      "from_result": "body.main", "cardinality": "exactly_one",
                      "where": {"surface_type": "planar",
                                "normal": {"parallel_to": "axis.z", "direction": "positive"}}},
            "thickness": {"parameter": "p_wall"}, "direction": "inward"}}
```

## The two measurements that decided the contract

Both against build123d 0.11.1 on OpenCascade 7.9.3.1.1, and both kept as tests rather
than as prose in a comment.

**`offset` is two operations wearing one name.** On a 100 × 60 × 40 box with a 3 mm wall:

| call | result | what it is |
|---|---|---|
| `offset(box, -3, openings=[top])` | 52 188 mm³, bounding box unchanged, 11 planar faces | a hollow box |
| `offset(box, -3, openings=[])` | 172 584 mm³ = 94 × 54 × 34, 6 faces | a **smaller solid** |

So a selector that matched nothing does not skip a step — it silently substitutes a
different part. CAD-IR 1.8 refuses `all`, `zero_or_one` and `exactly_n: 0` on a shell's
selector, which is the blend rule from ADR-026 with a sharper reason behind it.

**A wall the part has no room for does not fail.** `offset(box, -30, openings=[top])`
returns 240 000 mm³ — the original solid, whole, with no error raised. Bounding box, body
count, hole count and the manifold check all pass it. The engine therefore compares the
volume before and after and refuses with `SHELL_NO_CAVITY`.

A pre-check could not have done this: 25 mm walls in a 40 mm-deep box are fine with the
top open (a 15 mm cavity) and not fine with it closed. The kernel is the only thing that
knows, so it is asked and then checked.

## What each addition is checked by

| what | checked by |
|---|---|
| the arithmetic of a shell | 5 golden-corpus cases, every volume closed-form |
| a cardinality that opens nothing | contract test + corpus negative `shell-that-opens-nothing` |
| a wall with no room | corpus negative `shell-thicker-than-the-part` (`SHELL_NO_CAVITY`) |
| a selector that names no face | corpus negative `shell-opening-a-face-that-is-not-there` |
| a pattern of a shell | corpus negative `pattern-of-a-shell` (`UNSUPPORTED_FEATURE_SET`) |
| the direction being two different parts | `test_the_direction_is_the_difference_between_two_different_parts` |
| which body is hollowed | `test_a_shell_hollows_the_body_its_selector_names_and_leaves_the_other_alone` |
| a wall named by a parameter | `test_a_wall_stated_as_a_parameter_is_the_wall_that_gets_built` |
| a document that forgot to shell | `ShapeClaim.wall`, 10 tests in `test_cad_ir_shell.py` |
| determinism | `shell-cup` built twice, STL byte-identical |

### The corpus cases

| case | arithmetic |
|---|---|
| `shell-box-t2`, `shell-box-t5` | `W·H·T − (W−2t)(H−2t)(T−t)` |
| `shell-open-at-both-ends` | `W·H·T − (W−2t)(H−2t)·T`, and it is genus 1 — a duct is a through hole |
| `shell-cup` | `πR²h − π(R−t)²(h−t)` |
| `shell-outward` | `(W+2t)(H+2t)(T+t) − W·H·T`, plus `surface_face_count: 11` |

That varies both shapes the engine can shell, two thicknesses, one and two open faces,
and both directions — which is the criterion POSTMVP-013/014 set for promoting an
operation, so `feature.shell.inward` and `feature.shell.outward` arrive at `beta`. The
engine now declares **35 capabilities, 34 beta and 1 experimental**.

### The fixture

`tests/fixtures/cad-ir/enclosure.v1_8.json` — 120 × 80 × 40, corners rounded R10, a 3 mm
wall open at the top, two Ø6 mounting holes through the floor. It exercises a fillet, a
shell, a cut and a pattern in one document, and every number in it is closed-form:

```
outer area   120·80 − 4(1 − π/4)·10²   = 9 585.8407
inner area   114·74 − 4(1 − π/4)·7²    = 8 393.8620
volume       9 585.8407·40 − 8 393.8620·37 − 2·π·3²·3 = 69 821.0171
built                                                   69 821.0171   (Δ 6e-11)
```

The inner corner radius is the detail worth naming: offsetting a rounded outline inward
by `t` leaves arcs of `R − t`, so the cavity is the outer profile shrunk on every side
**and** rounded 3 mm tighter. The finished solid has exactly the ten cylindrical faces
that predicts — four at R10, four at R7, two at R3 — and both of the fixture's
`surface_face_count` expectations are about the shell.

## The claim

`ShapeClaim.wall` names the parameter that holds the wall thickness. Nothing else in the
claim can see a shell, and the table at the top of the ADR is why: a hollow part and a
solid one of the same size agree on the outline, the openings, the solid count and every
expectation the document could carry.

It stays inside ADR-025's rule — the claim carries a parameter's **name**, never its
value — and inside POSTMVP-016's: a reader who did not see a wall says nothing, and a
claim that says nothing agrees with either.

**The cycle cannot ask for a shell yet, and the ordering is deliberate.** A face selector
is behind the dialect wall ADR-029 named, so the output profile cannot offer one. The
claim's word for a hollow part arrives first; the profile follows when the dialect
allows. Until then a shell reaches the engine through the manual API, and `wall` is
checked by `validate --claim`. Nothing was added to `schemas/drawing-analysis.schema.json`
for the same reason: a claim the compilation stage cannot satisfy would fail every hollow
drawing.

## Two version defects found on the way

Both the same kind of mistake — one fact written down twice, and allowed to disagree.

**`MIGRATABLE_VERSIONS` and the normalizer disagreed about 1.6.** The list said a 1.6
document was migratable; the normalizer's branch handled 1.2 through 1.5 and nothing
else. So the validator told a caller to normalise first and the normalizer then refused
the same document as unsupported — the same build, the same run, contradicting itself.
It had been that way since 1.7 landed and nothing tested it. The relabel-only set is now
derived from the migratable list, and a test walks every version in it and asserts it
reaches the canonical form.

**`generate_output_profile.py` hard-coded the version it constrains the model to.** A
profile pinned to a version the contract has moved past would make every compilation
produce a document the validator refuses — total failure, not partial, and discovered
only in an AI run. It reads `CAD_IR_VERSION` from the contract now, as the corpus and the
canonical schema already did.

## Tests

| suite | result |
|---|---|
| Python | **743 passed, 1 skipped** |
| .NET | 6 + 30 + 41 + 31 (4 container tests skipped — no `CAD_ENGINE_IMAGE` here) |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

## What this is not

**It is not sweep or loft.** Those are P4, they need a path or a correspondence between
sections, and neither is a variation on this.

**It is not the rest of P3.1.** The roadmap's four bullets are inward/outward/both, faces
removed, constant thickness, minimum wall validation. Three of the four are in. "Both" is
refused with a reason (the ADR), and minimum-wall validation is here as a check on the
result rather than a rule about the input, because the measurement above showed a rule
about the input would be wrong half the time.

**A variable-thickness shell — a different wall on named faces — is not in.** It is a
second selector and a second number per face, and no drawing the reading stage can
currently produce asks for one.
