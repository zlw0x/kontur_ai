# ENGINE-MIG-007: service integration acceptance

**Date:** 2026-07-31 · **Result:** PASS. A worker configured for build123d builds
a real job end to end, publishes a manifest that says which engine it is, and can
have an operation switched off without a release.

The migration's last step before removal. ENGINE-MIG-003 through 006 built an
engine and proved it; this is the one that connects it to the service that
schedules work. It also pays the debt ENGINE-MIG-006 left open: revolve was the
first operation in this repository not behind a per-operation feature flag, and
ADR-021 was never waived.

## What was run

The real `cad-worker` binary, configured for build123d in process mode, against a
job directory holding `bushing.v1_4.json` — a part the KOMPAS adapter cannot build
at all:

```bash
dotnet cad-worker.dll run-job .../job
{"status":"COMPLETED","adapter":"build123d","artifacts":2,"path":".../job"}
```

The same worker with no `cad_engine` section, on the same document, refuses it —
`UNSUPPORTED_FEATURE_TYPE: This adapter cannot build solid.revolve.` Two engines,
one document, and each says honestly what it can do with it.

## Result

```text
output/model.step   20 634 B
output/model.stl   126 084 B   2 520 triangles, genus 1
output/validation-report.json
```

The envelope the rest of the service reads, from a build123d worker:

```json
{
  "valid": true,
  "adapter": "build123d",
  "engine": {
    "engine_id": "build123d", "engine_version": "0.11.1",
    "kernel_id": "opencascade", "kernel_version": "7.9.3.1.1",
    "cad_ir_version": "1.4"
  },
  "geometry": { "valid": true, "checks": [ ... 14 ... ] },
  "artifacts": [ { "Kind": "STEP", ... }, { "Kind": "STL", ... } ]
}
```

`geometry` is the engine's own report, carried through whole rather than
summarised. It reopened a written STEP and parsed the STL as a file and made
fourteen measurements; restating that as a boolean here would throw away the only
evidence anyone has that the model is right.

## The rollback path, end to end

A flag file on the worker, and the same document:

```bash
echo '{"disabled":["sketch.arc"]}' > .../feature-flags.json
dotnet cad-worker.dll run-job .../job-lever
{"status":"FAILED","code":"CAPABILITY_DISABLED",
 "message":"the arc in sketch.plate needs sketch.arc, which is turned off on this worker."}
```

The job directory afterwards holds `cad-ir.json` and a `state.json` saying
`FAILED`, and **no `output/`**. An empty output directory beside a failed job
reads like a build that ran; both the engine and the worker now create theirs
last, which a test found by asserting it.

Five hops, and each one had to be built: an operator's file on the worker, a key
on the engine's command line, a requirement collected from the document, a gate
checked before any geometry, and a typed refusal that arrives back as the code it
was raised with rather than as an exit status.

## The three decisions worth recording

### The engine is asked, never described from here

The manifest a build123d worker publishes comes from the engine's own `describe`,
with the operator's flags already applied — the same call whose gate the build
then enforces. A hard-coded list on the worker would be a second place for the
truth to live, and the failure it produces is the worst kind available: the API
schedules an operation the worker then refuses, repeatedly, with nothing saying
why.

Described once per worker and cached against the flags it was asked under. The
claim loop asks on every poll and describing a container engine means starting
one; a container start every few seconds to learn something only a flag changes
is not a cost worth paying.

### `kompas_version` is not reused

The manifest gains an optional `engine` block. Putting an OpenCascade version in a
field named `kompas_version` would make every reader of a manifest wrong about
what produced a model, and the field is still the right one for the worker that
does drive KOMPAS. Additive and optional, so a worker older than this build still
publishes a manifest the API accepts. Both leave in ENGINE-MIG-008.

### Nothing the child process says is taken on trust

The launcher compares the digests the engine reports against the bytes on disk,
checks that every artifact the engine declared as required exists, refuses an
artifact name that is a path, and compares the flags the engine echoes against the
flags it was given — in both directions. That last one is why the engine echoes
them at all: a launcher that dropped a key would otherwise report a clean build of
exactly the operation an operator was trying to stop, and nothing anywhere would
say so.

Failures stay typed. `REVOLVE_PROFILE_CROSSES_AXIS` arrives with its code and
stage so a repair loop can react to it. A crash with nothing on stdout becomes
`ENGINE_PROCESS_FAILED` carrying the exit code and nothing else — `stderr` never
reaches the message, because a Python traceback names host paths and that message
can reach a customer.

## What the tests cover

| Suite | Count | What it is for |
|---|---|---|
| `test_capabilities.py` | 19 | what a document requires, and what a flag blocks |
| `apps/cad-worker/tests` | 12 | the engine's command line as a program's interface |
| `Build123dProcessEngineTests` | 20 | every way the far side can answer, against a stub |
| `RealEngineTests` | 5 | the same launcher against the real Python engine |
| `DocumentEngineJobTests` | 9 | the branch, the flags, the envelope, the manifest |

`RealEngineTests` is the one that could not be replaced by a stub. The C# records
and the dictionaries the Python worker prints are two hand-written descriptions of
one format, in two languages, in two directories, and nothing else in either suite
would notice them drifting apart. It runs on the Linux CI job that already has the
engine installed, and skips where it is absent — which keeps the .NET suite
runnable on a machine with no Python, the same property the Python suite keeps for
a machine with no CAD library.

One test reads `CadCapabilities.cs` from Python and asserts the two engines spell
the same operation the same way, with `export.m3d` and the two revolve keys as the
only deliberate differences. A key added to one side alone fails it.

## Observed, and worth knowing before someone chases it

**STEP is not byte-reproducible; STL is.** The same document built twice gives an
identical STL — same length, same digest — and a STEP whose digest differs, because
the format writes a timestamp into its header. Anything that wants to recognise "we
already built this part" has to use the CAD-IR canonical hash, which is what it was
for, and not the digest of a delivered file.

## What is not done, and is ENGINE-MIG-008

- **`WorkerCapability.KOMPAS_BUILD`.** The API's coarse routing capability is named
  after an engine. Renaming it is a change to a published enum and belongs with the
  removal that makes the old name meaningless, not before it.
- **`apps/local-worker` still targets `net8.0-windows`**, because it still holds the
  KOMPAS adapter and the Codex runner. The CAD path no longer needs Windows — the
  launcher and the contracts are plain `net8.0` — but the worker as a whole does
  until the adapter goes.
- **The container image is not built by CI.** Process mode is what the acceptance
  run and the tests use. Building and pinning the image is a deployment task.
- **No production run.** This was a run on a Linux machine with the interpreter
  present, not a deployment. The switch-over is ENGINE-MIG-008 and it is deliberate
  that it is a separate decision.
