# Contracts

Versioned JSON Schemas are the trust boundary between untrusted AI output and trusted code. Unknown schema major versions are rejected; no generated code is executed.

`schemas/openapi.v1.json` is the API source of truth for TASK-002. The small
TypeScript client in `generated/client.ts` is generated from that contract and
contains no authority to change an order state. Worker protocol envelopes use
major version `1`; unknown majors must be safely rejected.
