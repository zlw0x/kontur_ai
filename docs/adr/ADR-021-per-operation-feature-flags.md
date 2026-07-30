# ADR-021: An operation can be turned off on the worker, without a release

## Status

Accepted on 2026-07-30.

## Context

The roadmap's definition of done asks for a feature flag and a rollback per
operation. Six operations had landed without one.

That is the wrong way round, and not only because a rule was unmet. The service
runs on one trusted machine that drives KOMPAS with the owner's licence, and the
failure it exists to prevent is a part that looks right and is wrong. When an
operation turns out to be producing those, the response cannot be "ship a new
worker": the geometry has to stop being produced now, and the fix has to be
smaller than "stop building anything".

Retro-fitting flags into six operations is also strictly more work than fitting
them into one, which is the argument for doing it before the seventh.

## Decision

### The flag lives on the worker

A file, `feature-flags.json`, under the worker's state root. Not a server-side
setting, because the thing that has to stop is the thing that drives KOMPAS, and
it has to stop even when the server cannot be reached to say so.

### One key per thing that can fail on its own

Granularity follows the failure, not the code. An arc and a slot share every
line of the drawing path, but a slot is expanded arithmetic that can be wrong by
itself, so it gets its own key. Eighteen keys cover what the adapter builds:
the profile kinds, each sketch primitive, islands, construction geometry, each
sketch plane kind, the boss, the cut, the three exports and the three checks.

### A flag has two effects, and both are needed

**The manifest publishes the operation as `disabled`.** The API's capability
vocabulary already treats `disabled` as "no" outright rather than as a low rung
on the maturity ladder, so work requiring it stops being scheduled.

**The parser refuses a document that needs it.** Anything already queued fails
with `CAPABILITY_DISABLED` before any COM object exists — measured: with arcs
turned off, the acceptance part fails naming the exact segment, and no KOMPAS
process starts.

Either effect alone is a half rollback. Without the manifest, the API keeps
handing over work that will fail. Without the parser, anything already in flight
still builds the geometry that was meant to stop.

### An optional operation is registered vocabulary, not a universal requirement

The API distinguishes baseline capabilities — the exports, the checks, the prism,
the through-cut, which every build needs whatever the part is — from optional
ones, which a particular document may need and most do not.

Only the baseline is demanded before a job is leased. Requiring the rest would
mean a worker with arcs turned off could build nothing at all, when what was
wanted was that it build everything except arcs.

The consequence is stated rather than hidden: a document needing a turned-off
operation is scheduled and then fails at parse time on the worker, rather than
never being scheduled. For a rollback that is enough — it stops producing bad
parts immediately, with a typed reason. Deriving a job's requirements from its
CAD-IR would let the scheduler know too, and is recorded as the follow-up it is.

### Absence is not a rollback, and neither is a typo

A missing flag file means every operation is on. A file that cannot be parsed is
a hard failure, not "no flags": an operator who wrote one believes it is in
force, and quietly running an operation they turned off is the single outcome
this must never produce.

A flag naming a capability this build does not have is refused for the same
reason. A typo in a rollback switch is the worst possible moment to fail
silently — the operator believes the operation has stopped and it has not.

### Everything POSTMVP-006 added is declared beta

One real acceptance part is not the ten positive and ten negative fixtures the
definition of done asks for. Declaring contours, arcs, slots, polygons, islands,
construction geometry, auxiliary planes, face-selector planes and bosses as
`beta` makes the gap visible instead of aspirational.

### The manifest and the gate cannot drift

Every key the parser can refuse on is a key the manifest declares, checked by a
test. Otherwise an operation could be turned off without the API ever hearing
about it — the build would stop and the scheduling would not.

## Consequences

A rollback is now one command, `cad-worker flags --disable <key>`, and it says
what it changed and what the effective status of every operation is. The reverse
is the same command with `--enable`, verified on the real acceptance part in both
directions.

Two costs. The worker reads the flag file on every job rather than caching it,
which is a file read against a KOMPAS session measured in seconds — deliberate,
because a flag flipped during a run should take effect on the next job rather
than after a restart. And the generation path uses the same gate as the build
path, so a disabled operation is also one Codex will not be asked to produce;
that means a flag flipped mid-order changes what the repair loop is aiming at,
which is correct but worth knowing.

## Alternatives rejected

**Server-side flags.** Simpler to administer and wrong: the machine that has to
stop is the one that might not be able to reach the server.

**One flag for the whole adapter.** That is a kill switch, not a rollback. The
point is that turning off arcs leaves the plate buildable.

**Requiring every optional capability of every job.** Then a rollback takes the
worker offline instead of narrowing it.

**Environment variables.** No record of what was changed or when, and no way to
reject a typo.
