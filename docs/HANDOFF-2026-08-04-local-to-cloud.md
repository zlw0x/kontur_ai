# Handoff: local → cloud, 2026-08-04

Written by the local session for whoever picks this up. It exists to be deleted
once the merge is done.

## What changed here, and why the cloud's own handoff needs re-reading

`docs/HANDOFF-2026-08-04-cloud-to-local.md` was written against `3c18326`. Since
then **eighteen commits** landed on `origin/master` (`3c18326..ba44ccc`), and
eight of them touch files that handoff describes as untouched locally. Its file
map is still useful; its "the local side is clean here" needs checking against the
current `origin/master` rather than against the base it was written on.

The overlaps, by file:

| file | what the local side did |
|---|---|
| `packages/cad-ir/cad_ir/shape_claim.py` | `steps` field, `_step_disagreement`, `_outer_signature`, and the call in `disagreements()` |
| `packages/cad-ir/cad_ir/canonical_validator.py` | `PARAMETER_DRIVES_NOTHING`, construction excluded from the reference walk |
| `packages/cad-ir/cad_ir/base.py` | `ScalarQuotient`, `ScalarNegation`, depth bound, `Scalar` union |
| `apps/local-worker/BuildFeedback.cs` | three codes classified, `MaxCompileRepairs` |
| `apps/local-worker/DrawingPipeline.cs` | `CompileAsync` split, round reuse, prompts to `drawing-mvp-8` |
| `apps/local-worker/Pipeline.cs` | `CreateDrawingPipeline`, failure reporting, `prior_analysis` input |
| `apps/api/app/contracts.py`, `main.py` | `JobStatus.FAILED`, the fail endpoint, answer shapes, KOMPAS removal |
| `apps/web/app/page.tsx` | failure card, demo banner, choice answers, M3D removed |
| `tests/fixtures/cad-ir/*` | renamed to `v1_11` **and four rewritten** to reference parameters instead of literals |

`packages/cad-engine-contracts/CadIr.cs` **does not exist locally** — it arrives
with the cloud branch. So its `Version = "1.10"` is untouched here and the cloud's
advice stands: set it to `"1.11"` after the merge, and delete the literal in
`apps/local-worker/WorkerCapabilities.cs:34` so the version is named once.

## The state you are merging into

- CAD-IR **1.11** — `ScalarQuotient` and `ScalarNegation` (ADR-034). A diameter can
  drive a radius; a parameter can drive both sides of a symmetric outline.
- `PARAMETER_DRIVES_NOTHING` — a `length` or `angle` parameter no feature
  references is refused, and construction geometry does not count as a reference.
- `ShapeClaim.steps` — how many distinct outside sizes the part has along its axis.
- The online path now checks documents at all: `ClaimLoop.CreateDrawingPipeline`
  passes the engine and the feature flags, which it previously did not.
- Failure is a state: `JobStatus.FAILED`, migration 0005, a lease-scoped endpoint.
- `MaxCompileRepairs = 3`, separate from `MaxBuildRepairs = 2`.
- KOMPAS and M3D are out of the vocabulary; migration 0006 rewrote the rows first.
- Migrations are read from the directory, not from a list in `migrate.sh`.

Tests as left: **594 python**, .NET 6 + 31 + 31 + 71 = 139 with containers
available, launcher **28 passed / 7 skipped** with `CAD_ENGINE_IMAGE` set.

## What only the local machine can do

Say so rather than working around it: the cloud has no containers and no Codex.

- Building geometry. Every closed-form check in `docs/acceptance/POSTMVP-0*` needs
  the engine image.
- `ContainerEngineTests` and `RealEngineTests`. **They skip silently without
  `CAD_ENGINE_IMAGE`, and a skip reads exactly like a pass in the summary line** —
  that hid three stale fixture names through the whole 1.11 bump.
- Any drawing run: `analyze-drawing`, `run --once`, the web path.

So the cloud should take contract and check work, and leave anything that ends in
a measured volume for here.

## Order, and the one thing that must not be parallel

The cloud's own note is right and this session is the evidence: two branches each
holding a contract change is expensive to reconcile. **`scalar-arithmetic` and
`up-to-face` are both CAD-IR versions and must not run at the same time.**

Recommended order:

1. **Merge**, following the file map above. Run
   `python -m pytest -q apps/api/tests/test_fixture_versions.py` first — it finds
   leftovers of the bump faster than anything else.
2. **`CadIr.Version = "1.11"`**, and delete the duplicate literal.
3. **`ScaledParameterRef` into `Scalar`** (`docs/TASK-POSTMVP-scalar-arithmetic.md`).
   Note it overlaps with what 1.11 already added: `ScalarQuotient` covers
   diameter-to-radius and `ScalarNegation` covers the symmetric pair. Read both
   before adding a third form — the question to answer first is whether
   `ScaledParameterRef` says anything those two do not.
4. Only then `up-to-face` and rib.

## The three findings that are still open

None of them is caught by making a rule stricter, and all three want a run.

1. **The model evades the parameter rule rather than building what is drawn.**
   Twice: eight construction circles no constraint mentioned, then three cut
   features named `*_reference_cut`. `steps` was added for this and has been seen
   once in a real claim (`steps: 2`); whether it changes what gets built is
   unmeasured.
2. **A selection cannot distinguish two coplanar-normal faces.** The bushing stops
   at `SELECTOR_AMBIGUOUS` because "planar face along +Z" finds both the flange and
   the sleeve end. "The topmost" is expressible; "the larger" is not, and inventing
   a predicate for it is a decision rather than a fix.
3. **`pattern.circular` is offered and not taken.** A bolt circle comes back as six
   islands with perfect arithmetic. Vision is not the wall — the count is read
   correctly. Nothing makes the model prefer the form that carries the count.

## Where P3.2 and P3.3 actually stand

Both were probed and neither needs an operation:

- **Rib** (POSTMVP-022): composition. A closed contour extruded both ways.
  31468.0000 mm³ against a closed form of 31468.
- **Draft** (POSTMVP-024): `taper_deg` already gives the pull direction, the signed
  angle and the self-intersection check, exact to the prismatoid rule
  (26689.1761). What is missing is *which faces*, which is a selection.

Three milestones have now reached the same conclusion from three directions —
holes, ribs, draft — and it is worth treating as a rule: **an operation earns its
place in CAD-IR only when it says something composition cannot.**
