# Deploy on the image: the last tail of the migration, closed

**Date:** 2026-07-31 · **Result:** PASS. 35 launcher tests, none skipped.

ENGINE-MIG-008 left one thing unproven, and it was unproven for a reason that had
nothing to do with the code: the sandbox the migration was finished in could not
reach the Debian package hosts, so the worker image could not be built there and
every test that needs one skipped itself. The code was written and reviewable;
what was missing was a machine with an ordinary network and a container daemon.

This machine is that machine. Nothing here is a new decision — it is the CI job
run by hand, on the same commit, to find out whether it passes.

## What was run

`.github/workflows/ci.yml`, job `cad-worker-image`, step for step.

```powershell
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:ci .
```

### 1. The image describes itself, under the restrictions it will actually have

```powershell
docker run --rm --read-only --network none --tmpfs /tmp cad-ai/cad-worker:ci describe
```

```text
engine    build123d 0.11.1
kernel    opencascade 7.9.3.1.1
cad-ir    1.7
artifacts STEP, STL
capabilities 33 — 32 beta, 1 experimental
solid.revolve  beta
```

Every assertion the CI step makes passes: the engine names itself, it produces
exactly the two user-facing artifacts ADR-023 allows, and revolve is at least
beta.

### 2. It builds a real part, with nothing writable but the job

```powershell
docker run --rm --read-only --network none --tmpfs /tmp `
  --mount "type=bind,src=$job,dst=/work" cad-ai/cad-worker:ci build --job /work
```

`tests/fixtures/cad-ir/lever-plate.v1_7.json`, the fixture that exercises a
stadium profile of lines and arcs, two islands, a hexagonal hub on a datum plane
and a pin on a face named by a selector:

```text
status    COMPLETED
verified  true
model.step              51 226 bytes
model.stl              102 684 bytes
validation-report.json   2 162 bytes
```

A `describe` that answers proves the wheels installed. This proves the kernel
runs, and that results come back out of the bind mount rather than staying inside
a container that is about to be discarded.

### 3. The launcher against the same image, in the mode production uses

```powershell
$env:CAD_ENGINE_IMAGE = "cad-ai/cad-worker:ci"
dotnet test packages/build123d-launcher/tests --nologo
```

```text
28 passed, 7 skipped
```

Four container tests that had never run anywhere now run. They are the only
thing standing between two hand-written descriptions of one contract — the
argument list the launcher builds and the invocation a real daemon accepts — and
a silent drift between them.

## The seven that were still skipping, and why that was worth fixing

`RealEngineTests` covers the *other* runtime: the launcher driving the engine as
a plain process rather than a container. It probed `python3` and `python` on
PATH, found neither could import build123d, and skipped.

That is the right default and it was hiding available coverage. A developer
machine almost never has an engine of this size on PATH — it has it in a virtual
environment. The probe now consults `CAD_ENGINE_PYTHON` first, exactly as
container mode consults `CAD_ENGINE_IMAGE`, and it is still a probe: an
interpreter that cannot import the engine is passed over rather than trusted, so
a stale variable costs a skip and never a false pass.

```powershell
$env:CAD_ENGINE_PYTHON = ".venv-cad\Scripts\python.exe"
$env:CAD_ENGINE_IMAGE  = "cad-ai/cad-worker:ci"
dotnet test packages/build123d-launcher/tests --nologo
```

```text
35 passed, 0 skipped
```

Both runtimes, against the real engine, on one machine.

## What this did not need, and one thing it did

No code changed to make the container half pass. The image built, the engine
answered, the part came out, and the launcher's four container tests went green
on the first run — which is the outcome the cloud agent's work predicted and
could not demonstrate.

The process half needed one thing that was nobody's mistake: the local virtual
environment had build123d installed and none of the worker's other dependencies,
because it had been created earlier in the migration to *read* the library's
source rather than to run the worker. `pip install -r apps/cad-worker/requirements.txt`
into it, and the seven tests had something to talk to.

## What is still true afterwards

The image is built here and nowhere else. Publishing it to a registry, and the
credential that would need, remain a deployment decision rather than a repository
one — which is what the CI job's own comment says it owes: that the image builds
and that the thing inside it answers.
