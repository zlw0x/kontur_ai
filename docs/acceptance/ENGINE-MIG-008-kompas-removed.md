# ENGINE-MIG-008: switch-over and removal acceptance

**Date:** 2026-07-31 · **Result:** PASS, **after a correction the same day.** KOMPAS
is gone, the worker runs on Linux, and the image is built by CI.

The first version of this record claimed the switch-over was finished when it was
not: the engine had been removed but the *service* still required its output
format in three places, so no order could have been built. That is written up under
"Found afterwards" below rather than quietly fixed, because the reason it was
missed is more useful than the fix.

Nine thousand lines out, roughly a thousand in. This is the step ADR-023 said would
come last and only after the replacement was proven, and it is deliberately a
separate decision from the six that proved it.

## What was removed

| Gone | Why it could go |
|---|---|
| `packages/kompas-adapter` | COM interop, the API5 session, the constant tables identified by measuring what moved, the sketch builder, the topology reader, the constraint applier |
| `packages/geometry-validation` | the engine reopens both files and measures them itself (ENGINE-MIG-005); a second verifier that could not see what the first saw existed only because KOMPAS could not |
| `CadIrBuildPlanParser`, `SketchValidator`, `ConstraintValidator`, `SelectorResolver`, `SelectorStabilityReport`, `GeometrySelectors`, `SketchGeometry`, `SketchConstraints`, `CadCapabilities` | all ported to Python in 004–006; a .NET copy would be a second opinion about what a valid document is |
| `ICadAdapter`, `FakeCadAdapter`, the build plan | the engine reads the document; a plan can no longer carry every document the contract allows |
| `KompasProbe`, `SelectorDiagnostic` | replaced by `describe-engine`, which is the question that still has an answer |
| `net8.0-windows` | one thing needed it, and it was DPAPI |

What stays in `packages/cad-engine-contracts` is what describes a *result* —
artifacts, timings, the engine's identity, the typed failure — because that is
still the worker's business: it holds the lease, writes the ledger and uploads the
files.

## Verified on this machine

```bash
cad-worker describe-engine
{"status":"ENGINE","engine":{"engine_id":"build123d","engine_version":"0.11.1",
 "kernel_id":"opencascade","kernel_version":"7.9.3.1.1"}, ...}

cad-worker run-job .../job          # bushing.v1_4.json — a revolve
{"status":"COMPLETED","adapter":"build123d","artifacts":2, ...}

cad-worker flags --disable sketch.slot
{"status":"FLAGS", "changes":["sketch.slot disabled"], "capabilities":[...]}
```

The part built is the one the deleted adapter refused by name. `doctor`, `flags`
and `run-job` all run from the `net8.0` build, on Linux, with no Windows anywhere
in the path.

This is the `run-job` path, which does not touch the API. What it does *not* prove
is that an order can be scheduled — see "Found afterwards" below.

## Found afterwards: the service still required M3D

Removing the engine that produced `model.m3d` did not remove the three places the
API demanded one. Each would have stopped an order on its own, and together they
made the whole cycle impossible while every test stayed green.

| Gate | What it did |
|---|---|
| `workers/capabilities.py` — `export.m3d` in `BASELINE_CAPABILITIES` | demanded of **every** `BUILD_CAD` and `ANALYZE_DRAWING` job. build123d declares no such capability, so a healthy worker was refused every job with `CAPABILITY_NOT_SUPPORTED` and polled forever |
| `main.py` — `"M3D" not in artifact_types` | a completed build was rejected `409 M3D artifact is required` |
| `main.py` — `has_model = any(type == "M3D")` | an order could never reach `READY` |

And a fourth, which this migration introduced: the worker began declaring the
coarse capability as `CAD_BUILD` while the API still enqueued jobs requiring
`KOMPAS_BUILD`. A raw set comparison made a worker and a job that meant exactly
the same thing look incompatible.

**Why nothing caught it.** Every test asserted the *old* rule — five of them
uploaded an artifact called `M3D` and expected a 200 — so the suite defended the
requirement rather than the behaviour. And the acceptance run for ENGINE-MIG-007
went through `run-job`, which is the path that skips the API entirely. A milestone
whose whole subject is scheduling was accepted without once exercising
claim → build → complete → READY.

**The fix.**

- `BASELINE_CAPABILITIES` demands `export.step` and `export.stl`. A baseline naming
  one engine's native format was always this failure waiting for the engine to
  change.
- `DELIVERED_MODEL_ARTIFACTS = ("STEP", "STL")` — one place, in the API — is what a
  finished build owes, and a partial upload is refused with the missing kind named.
  These are a statement about the *product* (ADR-023, `AGENTS.md` rule 11), which is
  the difference from `M3D`: STEP and STL are what a customer receives, not what an
  engine happens to write.
- `canonical_capabilities()` folds `KOMPAS_BUILD` onto `CAD_BUILD` in all three
  comparisons, so all four combinations of old and new names across a deploy work.
  A parametrised test covers all four.
- `ManualCadJobRequest.requested_formats` no longer accepts `m3d`. It was accepted
  and never honoured — the worker exported whatever its engine produced — so
  refusing it is more honest than ignoring it.
- The web page stops offering M3D on a new order and stops promising it on the
  landing page. It still *displays* one if an old order has it: artifacts are files
  and are served as written.

**Verified end to end through the API**, which is what should have been done the
first time: an order created, claimed by a worker publishing the manifest the real
engine publishes (no `export.m3d`, `CAD_BUILD`), STEP and STL uploaded, a
completion with only STEP refused `409 a completed build owes STL`, the full
completion accepted, the order `COMPLETED`, and STEP downloaded.

## The three decisions that needed care

### A rename that is stored is not a rename

`WorkerCapability.KOMPAS_BUILD` and `ResourceStage.KOMPAS_STARTUP` both name an
engine that no longer exists. Both are also **written into the database** by every
release before this one — in `worker.capabilities`, in
`order.required_capabilities`, and in every ledger row. Deleting either member
would turn a rename into rows nothing can parse.

So `CAD_BUILD` and `CAD_STARTUP` were added beside them, new writes use the new
names, and the old members leave when no stored row carries them. Both spellings
have a test saying why they are both there, because the obvious next change is to
tidy one away.

### The repair loop needed the engine, not a replacement parser

The loop that repairs AI-written CAD-IR used the .NET parser as its pre-flight
check. Deleting the parser without replacing that check would have made the loop
accept anything and discover the problem at build time — after paying for it.

`cad_worker validate` is the replacement: the same schema, the same trusted
validator and the same capability gate as a build, with no geometry. It answers
with the capabilities the document requires, so a refusal says which operation was
wanted rather than only that something was wrong.

Writing the check on the calling side instead would have recreated exactly the
thing this milestone deleted.

### The container could not write its own output

Found by writing the CI job that runs the image. The launcher passed
`--user 10001:10001` — the unprivileged user the Dockerfile creates — and that
cannot work: the job directory is a bind mount owned by whoever runs the worker, so
a container running as a different uid cannot create the `output/` the engine
exists to produce.

Two ways out, and only one is a smaller hole: loosen the directory's permissions,
or run the container as the uid that owns it. It now runs as the worker's own user,
which gains nothing — that account already owns the directory and already runs the
worker — while the read-only root still stops it writing anywhere else.

This is the second defect in this migration that only appeared when something ran
the real thing under the real restrictions, after the first was the axis read with
`float()`. Both are the argument for the acceptance runs.

## Tests

| Suite | Count | Note |
|---|---|---|
| Python | 466 | the engine, the contract, the capabilities, the worker CLI |
| `CadAi.LocalWorker.Tests` | 37 | the job path, the manifest, the flags, the credential store |
| `CadAi.Build123dLauncher.Tests` | 26 | 21 against a stub, 5 against the real engine |
| `CadAi.CodexRunner.Tests` | 30 | unchanged, and no longer Windows-only |
| `CadAi.CadEngine.Tests` | 6 | what is left of the neutral contracts |

The .NET total is 99 where it was 219. The 126 that went were testing the parser,
the validators and the resolver; what replaced them is in the Python suite, which
grew from 370 to 466 over the same milestones.

One test changed shape rather than leaving. It used to read `CadCapabilities.cs`
and assert the two engines spelled operations the same way; it now asserts that no
C# file declares a capability key at all — the same drift, made unrepresentable
rather than merely detected.

## CI

- `worker` (ubuntu) — `dotnet build` and `dotnet test` on the platform production
  runs on. This job did not exist; the .NET suite ran only on `windows-latest`.
- `worker-windows` — still there. An operator's machine with Codex signed in is
  still a supported place to run the worker; it is no longer the only one, and no
  longer where the CAD engine lives.
- `cad-worker-image` — builds the image and runs it under the launcher's own
  restrictions: read-only root, no network, a tmpfs for scratch, one bind mount.
  `describe` must answer with build123d, STEP and STL and revolve as experimental,
  and then it builds the lever plate — because a `describe` that works only proves
  the wheels installed.

## What is not claimed

- **The image build is unverified here.** There is no Docker daemon in this
  environment, so `cad-worker-image` is the first thing that will run it. The
  Dockerfile is unchanged from ENGINE-MIG-003 apart from how it is invoked.
- **No production deployment.** Everything above is a run on a Linux machine with
  the interpreter present. Pointing a deployment at a pinned image, and pushing
  that image to a registry, are operational steps with a credential behind them.
- **The M3D that older orders hold is untouched.** Artifacts are files and are
  served as written. A job completed before this migration still downloads
  everything it produced, including a format nothing can build any more — which is
  the correct behaviour for a record of what was delivered.
- **`kompas_version` is still in the manifest schema**, as an optional field, for
  the same reason the enum members are: something may still hold a manifest that
  sets it. Nothing writes it.
