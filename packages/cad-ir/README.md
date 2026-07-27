# CAD-IR

The canonical contract is `schemas/cad-ir.schema.json`. The Python package in
`cad_ir/` provides:

- strict JSON Schema validation before typed parsing;
- Pydantic models with unknown fields forbidden;
- dependency graph, identifier, parameter-use and build-eligibility checks;
- a bounded expression parser supporting only numbers, parameter references,
  `+ - * /`, parentheses, `min`, `max`, `abs` and `pi`.

No expression is passed to Python `eval` or another code execution facility.
