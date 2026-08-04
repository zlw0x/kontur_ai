# Handoff, 2026-08-04: `master-jpf4u2` → the local 1.11 branch

Delete this file once the merge has landed and its checklist is green. It exists to make
one merge safe, not to describe the project.

## What is on `master-jpf4u2`

Six commits, none of which changes CAD-IR's version. Base: `3c18326`.

```
f4aa525  scalars: the arithmetic a reading needs, designed and built short of the contract
016b9df  docs: rib is unblocked, and it does not need extrude(until=...)
28994ba  claim: a word for a draft, and the contract's extrusion rules under test
8984de4  tests: no source names a CAD-IR version, and a test that refuses one
ab773f3  loft: a rotation the sections cannot record, and the topology sweep and loft owe
26e69f5  docs: Gate P4 taken apart, and the two halves that are actually missing
```

Verified green on this branch at `f4aa525`:

| suite | result |
|---|---|
| Python | **911 passed, 1 skipped** |
| .NET | 6 + 61 + 31 + 31 = **129 passed, 4 skipped** (container tests, no `CAD_ENGINE_IMAGE`) |
| `generate_schemas.py --check` | valid |
| `generate_output_profile.py --check` | up to date |
| `validate_schemas.py` | valid |
| `check_openapi_compatibility.py` | valid |

**CAD-IR is still 1.10 on this branch.** Every version-bump artefact — the fixture renames,
`CAD_IR_VERSION`, `SUPPORTED_VERSIONS`, `MIGRATABLE_VERSIONS`, the normalizer — belongs to
the local branch and was deliberately not touched here.

## The one thing to do first

`8984de4` took the CAD-IR version out of every source file. The local branch bumped to 1.11
and fixed version literals by hand — including three container tests that still named
`lever-plate.v1_10.json`. **After the merge those hand-fixes are unnecessary and the
literals must not come back.** Two declarations hold the version now:

- `packages/cad-ir/cad_ir/canonical.py` → `CAD_IR_VERSION` (already 1.11 locally)
- `packages/cad-engine-contracts/CadIr.cs` → `CadIr.Version`, **still `"1.10"` on this
  branch — set it to `"1.11"` as part of the merge.** Nothing else in .NET states it;
  `WorkerCapabilities.CadIrVersion` and `CadIr.FileSuffix` both derive from it.

Python callers ask for a bare fixture name: `fixture("plate")`, `fixture_path("plate")`
from `tests/cad_ir_fixtures.py`, which derives `plate.v1_11.json` from the contract. .NET
callers build `$"{name}.{CadIr.FileSuffix}.json"`.

`apps/api/tests/test_fixture_versions.py` refuses a `v\d+_\d+` literal in any `.py`, `.cs`,
`.yml` or `.yaml` file outside three allow-listed files, and checks that every fixture on
disk is reachable by name. It runs in the ordinary suite, so it cannot be skipped the way
the container tests were. Run it first after the merge — it is the fastest way to find
whatever the bump left behind.

## File-by-file, where both sides have touched

Everything not listed is a new file from this branch and merges clean.

| file | what to expect |
|---|---|
| `packages/cad-ir/cad_ir/shape_claim.py` | **Both sides add a claim word.** `steps` (local) and `draft` (here) are independent fields near `wall`/`blends`, and each adds one `found.extend(...)` line in `disagreements()`. Keep both, in both hunks. Neither reads the other. |
| `apps/api/tests/test_shape_claim.py` | Rewritten here for bare fixture names; the local branch likely added `steps` cases and edited fixture names. Take **this branch's** version of every name, keep the local branch's new tests. |
| `packages/build123d-adapter/tests/golden_corpus.py` | This branch touches only `_sweeps()`, `_lofts()` and `_sweep_and_loft_refusals()` (topology for six sweep/loft cases, plus one refusal case). Steps cases live elsewhere, so expect no real overlap. |
| `packages/build123d-adapter/tests/test_capabilities.py` | Rewritten here for bare names; the local branch adds the step capability. Take this branch's naming, keep the new capability assertions. |
| `apps/local-worker/WorkerCapabilities.cs` | Here: `CadIrVersion = CadIr.Version`. Locally: the literal `"1.11"`. Take this branch's line and put 1.11 in `CadIr.cs`. |
| `packages/build123d-launcher/tests/{RealEngineTests,ContainerEngineTests}.cs` | Same story — the three fixture names are derived here. Take this branch's. `RealEngineTests` asserts `CadIr.Version` against the engine's own declaration, which is the two halves of the boundary agreeing rather than a tautology. |
| `apps/cad-worker/tests/test_cli.py`, `apps/api/tests/test_cad_ir_{boolean,pattern,mvp_profile}.py`, `packages/build123d-adapter/tests/test_{blends,booleans,patterns,revolve,shells,sweeps,fixture_parity}.py`, `apps/local-worker/tests/*.cs` | De-versioned here only. Take this branch's. |
| `.github/workflows/ci.yml`, `pyproject.toml` | Small additions here (the fixture copy derives the suffix; `tests` on the pytest path). |
| `CLAUDE.md`, `docs/POST-MVP-ROADMAP.md` | Both sides append. Keep both sets of paragraphs — they describe different work. |
| `packages/cad-ir/cad_ir/loft.py`, `apps/api/tests/test_cad_ir_sweep_loft.py`, `docs/adr/ADR-031-*` | This branch only (the rotation rule). |
| `packages/cad-ir/cad_ir/base.py`, `packages/build123d-adapter/cad_engine_build123d/parameters.py` | This branch only (`ScaledParameterRef` and its resolver). |

## After the merge

```bash
python -m pytest -q apps/api/tests/test_fixture_versions.py   # the guard, first
python -m pytest -q
python scripts/generate_schemas.py --check
python scripts/generate_output_profile.py --check
python scripts/validate_schemas.py
python scripts/check_openapi_compatibility.py
dotnet test CadAi.sln --nologo
CAD_ENGINE_IMAGE=<image> dotnet test packages/build123d-launcher --nologo   # the 4 that skip here
```

Expected totals are the local branch's plus this branch's 46 new Python tests (24 in
`test_cad_ir_extrude_modes.py`, 22 in `test_parameters.py`).

Three assertions will need one look each if 1.11 changed the shape of a document:

- `apps/api/tests/test_cad_ir_extrude_modes.py` builds documents inline from
  `CAD_IR_VERSION`, so it follows the bump — unless 1.11 made a new field required.
- `test_fixture_versions.py::test_the_legacy_fixtures_are_left_out_of_the_versioned_set`
  expects exactly `plate.json` and `plate-with-hole.json` as the unversioned 0.1.0 pair.
- `test_parameters.py::test_it_is_not_in_scalar_yet_and_that_is_on_purpose` **should fail
  the moment `ScaledParameterRef` joins `Scalar`.** When that happens, delete the test and
  the note in `base.py`; do not weaken it.

## What this branch left for the local machine

In priority order, with the reasoning already written down so none of it needs re-deriving.

1. **The three items only a daemon can do.** Rebuild the engine image on 1.11, run the four
   container tests with `CAD_ENGINE_IMAGE` set, and confirm nothing skipped.
2. **`ScaledParameterRef` into `Scalar`** — `docs/TASK-POSTMVP-scalar-arithmetic.md` has the
   design, the measurements and a six-step wiring list. It closes the last unfixed defect
   the nine runs found: a parameter cited to a drawing callout that drives nothing. The
   model and the resolver are built and tested; what is left is one union member, the
   schemas, a third `anyOf` branch in the output profile (offer `times` as an enum of
   0.5 / −1 / −0.5), `PARAMETER_DRIVES_NOTHING`, and four fixtures rewritten to reference
   their parameters.
3. **Up-to-face extrusion and rib** — `docs/TASK-POSTMVP-P3-2-up-to-a-face.md`. Sixteen
   measured cases, six named refusals, and the reach formula that reproduces the kernel's
   own answer to 0.000e+00. Also a CAD-IR version, so it wants to follow (2) rather than
   race it.
4. **Offer the draft to the drawing cycle, or find out that vision cannot read it.** The
   claim now has the word (`ShapeClaim.draft`); what is missing is a run that shows whether
   an agent reads a draft angle off a section view. One drawing answers it.
5. **The pattern that is offered and not taken.** Runs 7–9 found a bolt circle coming back
   as six islands with perfect arithmetic and no `pattern.circular`. A fourth kind of wall —
   an operation that is offered, readable and *unnecessary* — and the softest, because
   nothing makes the model prefer the form that carries the count. It is a prompt question
   and it needs runs.
