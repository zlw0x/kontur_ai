# ADR-008: versioned contracts and optimistic order transitions

## Status

Accepted for TASK-002 and TASK-003.

## Decision

Use OpenAPI 3.1 JSON and JSON Schema as versioned interchange contracts. Keep
the order state machine pure and require an expected integer version for every
transition. Persisted implementations must atomically compare this version and
append the emitted audit event.

## Consequences

- Clients cannot set an order status directly.
- Retry and concurrent-update failures are typed rather than silently merged.
- The protocol remains testable without PostgreSQL, Codex, or KOMPAS.
