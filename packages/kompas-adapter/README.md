# KOMPAS adapter

# Trusted KOMPAS adapter

The API7 document/sketch/base-extrusion surface is confirmed by
`probe-kompas` and recorded in `docs/TASK-006-kompas-probe-evidence.md`.

Adapter v0 accepts one enabled `extrude_add` containing one
`center_rectangle` on XY and a +Z distance. Unsupported documents fail before
KOMPAS is started. The real adapter performs COM work on a dedicated STA
thread, writes only fixed artifact names, returns SHA-256 metadata and cleans
up only the KOMPAS process it started. `FakeCadAdapter` is used by CI.

Add further COM members only after recording evidence from the installed SDK
or type libraries.
