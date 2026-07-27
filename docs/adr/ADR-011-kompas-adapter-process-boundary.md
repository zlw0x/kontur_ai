# ADR-011: isolate KOMPAS behind a narrow STA adapter

## Status

Accepted for TASK-008.

## Decision

Only `CadAi.KompasAdapter` may translate a bounded build plan into KOMPAS API7
calls. COM activation and all subsequent RCW use occur on one dedicated STA
thread. The worker and AI stages depend on `ICadAdapter`; CI uses
`FakeCadAdapter`.

The adapter initially rejects every feature outside the locally probed
rectangle/base-extrusion surface.

## Consequences

- AI output cannot select COM members or execute arbitrary automation code.
- Extending CAD support requires a local typelib/SDK probe, handler code and
  failure-path tests.
- Linux CI remains independent of a KOMPAS installation and license.
- Process-level timeout hardening remains an orchestration responsibility and
  must be completed before unattended pilot operation.
