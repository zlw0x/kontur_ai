# ADR-010: CAD-IR validation is a two-gate trust boundary

## Status

Accepted for TASK-007.

## Decision

Treat every CAD-IR payload as untrusted. Validate it first against the
versioned Draft 2020-12 JSON Schema and then run deterministic semantic checks
before constructing a typed model for downstream code.

Expressions use a dedicated recursive-descent parser. General-purpose
evaluation, imports, attribute access, strings and arbitrary function calls
are not part of the language.

## Consequences

- AI and uploaded content cannot add executable behavior to the CAD pipeline.
- Schema-valid documents can still be rejected for graph, reference or
  build-eligibility violations.
- The same fixture corpus can be used by the backend, fake CAD and the trusted
  local adapter.
- Any new operation or expression construct requires a contract version and
  explicit validator/test changes.
