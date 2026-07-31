# POSTMVP-015: the reading states the shape — acceptance

**Date:** 2026-07-31 · **Result:** PASS

The gap this closes is the one named in `docs/adr/ADR-025-*`: every check the
pipeline had was the document checked against itself, so a misread outline
produced a valid document that built an exact, manifold, wrong part and nothing
could say so.

## What was run

### 1. The failure, through the real engine's real command line

`tests/fixtures/cad-ir/lever-plate.v1_6.json` — a stadium outline, two Ø8 holes, a
pin standing on it — with a claim that reads the outline as a rectangle. Everything
else in the claim is right, and the document is valid, buildable and measures
exactly what it declares.

```bash
python -m cad_worker validate --job <job> --claim claim-misread.json
```

```json
{"status": "FAILED", "code": "SHAPE_CLAIM_CONTRADICTED", "stage": "cad-ir",
 "message": "the drawing was read as a rectangle outline, which is 4 straight segment(s) and 0 arc(s); feature.plate spells out 2 and 2",
 "disagreements": [{"code": "PROFILE_KIND", "claimed": "rectangle",
   "built": "a contour of 2 straight segment(s) and 2 arc(s)",
   "detail": "the drawing was read as a rectangle outline, which is 4 straight segment(s) and 0 arc(s); feature.plate spells out 2 and 2"}]}
```

Exit 1. Structured for the repair loop and readable for a person, and it names
both sides of the comparison rather than announcing a mismatch.

### 2. The same document, read honestly

```json
{"profile": "closed_profile", "solids": 3,
 "openings": [{"kind": "round", "count": 2}],
 "note": "a stadium outline with two round holes and a pin"}
```

```text
status VALID · 15 required capabilities
```

Exit 0. The check that fires on a correct document is the one that costs a repair
run on something that was right, so this half matters as much as the first.

### 3. Every fixture against an honest reading of it

`plate`, `plate-with-hole`, `constrained-plate`, `lever-plate`, `bushing` — five
documents, five claims written by reading the fixtures as a drawing agent would
describe them. No disagreements.

That run is what found the one false positive this had. `constrained-plate` writes
its rectangle as four named segments, because its constraints reference the sides;
requiring a `RectangleContour` contradicted a document that was right. The claim
is a statement about the part, not about how to write CAD-IR — so a named kind
accepts a path and the path's signature is checked where it is unambiguous, which
is what still catches case 1.

### 4. The claim reaches the engine from the drawing pipeline

`apps/local-worker` extracts `result.shape` into `output/shape-claim.json` and
hands its path down; in container mode it becomes a read-only bind mount at
`/claim.json`, inserted before the image name, with `--claim /claim.json` after
it. Asserted: the file arrives, it carries `profile`, `openings`, `solids` and
`thickness`, and **nothing about the drawing crosses over** — no `confidence`, no
`source`, no `questions`, no `summary`. A relative claim path is refused with
`OUTPUT_PATH_INVALID` like any other.

## Tests

| Suite | Count |
|---|---|
| `apps/api/tests/test_shape_claim.py` | 18 |
| `apps/cad-worker/tests/test_cli.py` (`--claim` cases) | 6 of 18 |
| `packages/build123d-launcher/tests` — incl. 7 against the real engine | 31 |
| `apps/local-worker/tests` | 39 |

Full runs: `498 passed, 1 skipped` (Python), `6 + 31 + 30 + 39` (.NET), schemas and
OpenAPI compatibility valid, web typecheck clean.

The failure-path tests are the point of the suite, and the ones worth naming:

- a stadium read as a rectangle — `PROFILE_KIND`
- a hole nobody read, and a hole the drawing has that the document does not —
  `OPENING_COUNT` both ways
- two round holes read as two slots — `OPENING_COUNT`, on a document that builds
  the wrong part and passes every measurement it declares
- a boss nobody read — `SOLID_COUNT`
- a thickness that lost its name to a literal — `THICKNESS_PARAMETER`
- a thickness claimed for a revolve — said so rather than silently ignored
- a document that builds nothing — `NO_SOLID`
- a claim file that is absent, oversized, or not a claim —
  `SHAPE_CLAIM_MISSING` / `SHAPE_CLAIM_INVALID`
- a disabled operation reported before any shape disagreement, so a repair loop is
  not sent after a document the worker would refuse to build either way

And what it deliberately does not do, each with a test: an island and a cut are
the same hole; a disabled feature is not part of the shape; **doubling every
dimension changes nothing**, because a claim carries kinds and counts and never a
coordinate.

## What this cost the contract

`shape` is required in `drawing-analysis.schema.json`, so the reading stage always
states one. A missing `shape` in an artifact is not a failure anywhere downstream:
no claim is written and the compilation is checked exactly as it was before, which
is what an older artifact gets.

Both prompts stopped naming one shape class. The analysis prompt asked for "one
centered rectangle and zero or more circular through-holes" — the MVP's geometry
written into an instruction, years after the engine started building slots,
polygons, arcs, islands, bosses and revolves. What a drawing agent can recognise
off a scan is still narrower than the schema now allows; that is a vision problem
and it is not fixed here. The contract no longer caps it.

## Not done

A question with `parameter_id: "shape"` now has a meaning and a place in the
prompt, and no run has yet produced one — that needs a genuinely ambiguous drawing
and a real Codex run on the trusted machine.

`closed_profile` is where an outline that is none of the four named kinds goes, and
about it the check says only the solid count, the opening counts and the
thickness. Sharpening that means naming more kinds, and naming a kind only helps
if the reading stage can tell it apart.
