# POSTMVP-004: CAD-IR 1.1 acceptance

**Date:** 2026-07-28 · **Result:** PASS. Two defects found by the real run,
both in schemas rather than in code.

The geometry this build constructs is unchanged. The point of the milestone was
a data model that the next few dozen operations can grow into, and the point of
this run was to prove the existing part still builds through it.

## Real end-to-end run

Order `78894456-f0a0-4591-974f-06d19cf34e04`, job
`a01a083b-8fd3-4967-87d3-82372d4842ca`, through Docker, PostgreSQL,
codex-cli 0.145.0 and KOMPAS v22. One clarification round, then READY.

Codex produced canonical CAD-IR 1.1 directly — no normalisation step in the
worker:

```text
schema        cad-ai/cad-ir 1.1
document      units mm, single_part, right_handed, name "plate"
parameters    param.width 60, param.height 30, param.depth 8,
              param.hole_radius 2.5, param.left_hole_x -15,
              param.right_hole_x 15, param.hole_y 0
features      feature.base            solid.extrude  depends_on []              produces [body.main]
              feature.cut_left_hole   cut.extrude    depends_on [feature.base]  produces []
              feature.cut_right_hole  cut.extrude    depends_on [feature.base]  produces []
expectations  bounding_box 60x30x8, body_count 1, through_hole_count 2
```

Identifiers are readable, the graph is explicit, and every dimension is a named
parameter rather than a literal.

## Independent geometry validation

| Check | Result |
|---|---|
| `solid_body_count` | expected 1, measured 1 |
| `bounding_box` | expected [60, 30, 8], measured [60, 30, 8] |
| `through_hole_count` | expected 2, topology-derived genus 2 |
| `closed_manifold_mesh` | 0 edges without exactly two incident triangles |
| `finite_non_degenerate_triangles` | 0 degenerate |

M3D 63 113 B, STEP 13 427 B, STL 25 628 B (148 triangles).

## Old orders are untouched

A job completed before this milestone still downloads all four artifacts
(HTTP 200), and its CAD-IR artifact is still `schema_version 0.1.0` with
`extrude_add` / `extrude_cut` features. Artifacts are files and are served as
written; the schema change does not reach backwards.

## Migration of the existing fixtures

Both 0.1.0 fixtures normalise to 1.1 with the part unchanged — 40 × 20 × 10 mm,
one Ø6 through hole, tolerance 0.05 — verified field by field rather than by
hash. Normalising twice produces identical bytes.

## Defects found by the run

Both were in schemas, and both cost real AI calls to discover.

### 1. The output schema used constructs the structured-output API rejects

Three consecutive runs failed at the CAD-IR compilation stage with HTTP 400,
each after the repair loop had retried it:

```text
'oneOf' is not permitted
schema must have a 'type' key
array schema missing items
```

`schemas/cad-ir-mvp-output.schema.json` is not a general JSON Schema — it is
the response format Codex is constrained by, and that dialect is narrower.
Rather than discover the fourth restriction the same way, the rules were
derived offline from the 0.1.0 schema the API had been accepting for months:

1. no `oneOf`
2. every schema node declares a `type`
3. every array declares `items`
4. every object lists **all** its properties as `required`
5. every object sets `additionalProperties: false`

The 0.1.0 schema satisfies all five. Rule 4 is the consequential one: strict
mode has no optional properties, so a field kept "just in case" becomes a field
the model is forced to invent. The profile was trimmed accordingly.

A test now asserts the profile obeys every rule, and asserts the same of the
0.1.0 schema — so the rules are derived rather than guessed, and would have
caught all three failures before a single call.

### 2. The prompt mentioned a value with nowhere to put it

The compilation prompt still said "the trusted analysis digest for this job is
…", left over from 0.1.0 where the document had a `provenance.analysis_sha256`
slot. Version 1.1 has none, so Codex put the digest in `metadata.prompt_version`:

```json
"prompt_version": "F4958DC3AC86D35C8EE7A5DA4D0B2B9402F3E5911426E5BF9A"
```

Not wrong of the model — it was told about a value and given one plausible
place for it. The sentence is removed, and the prompt now states exactly what
`prompt_version` must contain. The binding between an analysis and the CAD-IR
it produced lives in the ledger's provenance fingerprint (ADR-017), which is
where ADR-018 says it belongs.

## Also confirmed

- The C# expression evaluator is deleted along with the expression language it
  served: 130 lines that parsed untrusted arithmetic, now unreachable and gone.
- The adapter distinguishes `CAD_IR_VERSION_TOO_NEW` from
  `CAD_IR_VERSION_UNSUPPORTED`.
- The manual API endpoint normalises 0.1.0 submissions and returns the lineage;
  the stored artifact is canonical 1.1.
- Normalisation time is recorded in the resource ledger.

## Two build artifacts went stale mid-run, twice

The first attempt failed because `docker compose up -d` without `--build` left
the API on the previous contract. The second failed because
`dotnet run --no-build` left the worker with the previous copy of the output
schema, which is copied into the build output.

Neither was a code defect, and both cost a run to notice. The runbook already
warns about the Docker case; the worker case is the same shape and worth the
same care after any schema change.

## Verification

- Python 215 passed, 1 skipped.
- .NET 62 passed (CodexRunner 30, LocalWorker 16, KompasAdapter 13,
  GeometryValidation 3).
- Generated schemas current; all schemas valid; OpenAPI v1 compatible; web
  typecheck clean.

## Open findings

Unchanged from POSTMVP-003B and 003C: the ledger shipper logs a status code
and no reason, reasoning effort is requested but never confirmed,
`cache_write_input_tokens` is measured by the CLI and discarded, the
clarification contract carries one number per question, and a crashed attempt
is unaccounted for.

New: the repair loop retried a schema rejection three times. A `turn.failed`
carrying an `invalid_request_error` is not a repairable CAD-IR problem — it is
the same failure every time — and spending three AI runs to confirm that is
waste the runner could avoid by classifying the error before retrying.
