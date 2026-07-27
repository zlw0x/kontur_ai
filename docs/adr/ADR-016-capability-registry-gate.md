# ADR-016: the capability registry gates the lease

## Status

Accepted on 2026-07-27.

## Context

The MVP builds one rectangular prism with circular through-holes. The post-MVP
roadmap adds operations one at a time, and a worker's real ability depends on
its installed KOMPAS version, its adapter build and whichever feature flags are
on. Before this change the API decided what to schedule from a coarse
`AI_DRAWING` / `KOMPAS_BUILD` capability pair and a CAD-IR version string, none
of which say whether a specific operation can be built.

Without a gate, a job needing an unsupported operation is discovered halfway
through a CAD session on the owner's machine: KOMPAS is already running, the
lease is already consumed, and the failure looks like a defect rather than an
unmet requirement.

## Decision

A worker publishes a `WorkerCapabilityManifest` on heartbeat and claim: worker
version, KOMPAS version, Codex CLI version, supported CAD-IR versions, and a
status per capability key. A job carries the capability keys it needs, and the
API will not lease it to a worker that cannot serve all of them.

Statuses are `unsupported`, `experimental`, `beta`, `stable` and `disabled`.
**Only `beta` and `stable` qualify for a lease.** An operation under
development must not be reachable through an ordinary claim; reaching it has to
be a deliberate act, not a scheduling accident.

A worker that has published no manifest can serve nothing new. It is either an
older build or one that has not completed a heartbeat, and inferring
capabilities on its behalf is precisely how an unsupported job reaches KOMPAS.

An incapable worker is passed over silently rather than rejected with an error.
A claim is a poll, not a request for a specific job, and the job is still
waiting for a worker that can build it.

Capability keys are a controlled vocabulary in `app/workers/capabilities.py`,
matching `^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$`. The worker declares the same eight
keys in `WorkerCapabilities`. Adding a key is the deliberate step that makes an
operation schedulable, and it belongs there only once the adapter builds it and
an independent verifier checks it.

Distinct manifests are retained as history, so a cost or incident review can
tell which capabilities were in effect when a job ran rather than only what the
worker advertises today. Repeated heartbeats of an unchanged manifest do not
grow that history.

## Consequences

Backward compatibility is preserved in both directions: `capability_manifest`
is optional on the protocol-1.0 heartbeat and claim, and jobs enqueued before
the registry carry an empty requirement list and stay leasable.

The corollary is that an old worker will silently stop receiving new jobs once
those jobs declare requirements. That is the intended failure mode, but it is
invisible from the worker's side — it simply keeps polling and getting nothing.
Operational visibility for "a job is waiting and no enrolled worker can serve
it" is not part of this change and is needed before a second worker exists.

Two lists now describe the same vocabulary, one in Python and one in C#. They
are asserted independently rather than generated from a shared source; if the
list grows much beyond the current eight keys, generating both from the
schema is the better answer.
