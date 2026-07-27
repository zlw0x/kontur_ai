# TASK-002 and TASK-003: contracts and order state machine

## Contract decisions

- Public API is versioned under `/api/v1`; its canonical OpenAPI document is
  `schemas/openapi.v1.json`.
- Worker protocol `1.0` is carried in every claim request/response. The backend
  supports the current major and may add an N-1 adapter when protocol `2` is
  introduced; workers reject unknown major versions.
- Orders use integer optimistic locking. A caller must send `expected_version`;
  the persistence adapter must update only where both `id` and `version` match.
- Status transitions are requested commands, not mutable fields. The service
  emits an `OrderStateChanged` audit event with both status and version pairs.
- `schemas/openapi.v1.compatibility.json` records the v1 surface that cannot be
  removed or weakened. CI rejects breaking removals; additive changes remain
  compatible.

## State-machine acceptance evidence

`apps/api/app/orders/state_machine.py` contains the complete transition table.
Tests exercise every declared edge, every absent ordered pair, stale versions,
and terminal states. Database persistence, HTTP command handlers, worker
leases, and authentication are intentionally deferred to TASK-004.
