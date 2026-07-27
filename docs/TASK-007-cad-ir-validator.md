# TASK-007: typed CAD-IR and static validation

## Acceptance criteria

- The canonical `0.1.0` JSON Schema rejects unknown structural fields and
  bounds collection sizes.
- JSON Schema validation completes before typed parsing.
- Duplicate IDs, missing dependencies and cyclic feature graphs are rejected.
- An enabled feature cannot use an unresolved or missing parameter.
- Build eligibility requires `bounding_box` and `solid_body_count` invariants.
- Expressions are parsed without `eval` and support only the documented
  arithmetic grammar.
- Invalid JSON, injection-like expressions, division by zero and unknown
  functions have typed validation errors.

## Implementation

- Contract: `schemas/cad-ir.schema.json`
- Typed models: `packages/cad-ir/cad_ir/models.py`
- Validator: `packages/cad-ir/cad_ir/validator.py`
- Expression parser: `packages/cad-ir/cad_ir/expression.py`
- First buildable fixture: `tests/fixtures/cad-ir/plate.json`

The validator returns a typed `CadIrDocument` only after all schema and
semantic gates pass. Failure details are machine-readable
`ValidationIssue(code, path, message)` values.

## Verification

```powershell
python -m pytest -q apps/api/tests/test_cad_ir.py
python scripts/validate_schemas.py
```

The initial suite contains happy-path and failure-path coverage for schema
strictness, IDs, graph references, cycles, unresolved parameters, expressions,
required invariants and malformed JSON.
