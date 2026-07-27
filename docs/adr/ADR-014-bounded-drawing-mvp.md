# ADR-014: bounded drawing-to-CAD MVP

## Status

Accepted on 2026-07-27.

## Context

The product roadmap describes a broad future feature vocabulary. Implementing
an operation without evidence from the installed KOMPAS SDK would violate the
trusted-adapter boundary. A useful first release still needs one complete,
measurable path from a drawing to downloadable CAD artifacts.

## Decision

The first deployable MVP supports one centered rectangular extrusion followed
by zero to nineteen contained circular through-cuts. Codex may only produce
schema-constrained analysis and CAD-IR for that surface. Trusted parsers reject
all other feature shapes and operations before COM activation.

Drawing analysis is bounded to three Codex executions: one initial attempt and
at most two repairs. Repair receives immutable analysis and user answers. Any
tool-use event terminates the Codex process. User clarification is limited to
three rounds.

The API persists job state in PostgreSQL, binary and JSON artifacts in its
artifact volume, and drawing-order lineage in the same persistent volume. The
deployment is intentionally single-API-instance; moving lineage to a dedicated
relational table is required before horizontal API scaling.

## Consequences

The release is a functional vertical MVP, not the full operation list in the
long-term roadmap. Polyline/revolve/pattern/fillet/chamfer/mirror, assemblies,
sheet metal, arbitrary photos and responsible-part acceptance remain outside
this release. Expanding the supported surface requires exact SDK evidence,
adapter tests, real KOMPAS probes and new geometry invariants.

