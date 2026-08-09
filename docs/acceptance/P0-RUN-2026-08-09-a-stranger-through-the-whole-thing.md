# A stranger, through the whole thing, on a real deployment

**Date:** 2026-08-09 · **Machine:** the one Codex is signed in on ·
**Drawing:** `apps/web/public/sample-drawing.png` — the 60 × 30 × 8 plate with two
Ø5 through-holes at x = 15 and x = 45 that the earlier acceptance runs build.

The first run of the pilot perimeter as a whole: an account created from nothing,
an order that belongs to it, the moderation queue behind it, and the fleet gate
above it — through the compose deployment rather than through the test suite.

Five defects, and **not one of them is in geometry**. Four were invisible to
1 100 green tests because every one of them lives where the tests do not go: the
container image, the process boundary, and the exception filter.

## What ran

```text
POST /api/v1/auth/register        201, session cookie + CSRF token
POST /api/v1/drawing-jobs         201, owner_id = the new account
  -> ANALYZE_DRAWING  ->  WAITING_FOR_USER_ANSWERS, 2 questions
POST /api/v1/drawing-jobs/{id}/answers   201, round 1
  -> FAILED, CAD_IR_INVALID: CAD_IR_VERSION_TOO_NEW@$.schema_version
```

The order does not reach a model, and the reason is the fifth defect below. What
the run was for is the first four.

## 1. The API did not start at all

```text
PermissionError: [Errno 13] Permission denied: '/data/quarantine'
```

The Dockerfile created and chowned `/data/artifacts`; the secure-input work put
quarantine beside it at `/data/quarantine`, and `/data` itself stayed root-owned.
The API crashed **on import** — the container never served a request.

Nothing in the suite could see it: the tests point quarantine at a `tmp_path`, and
a Dockerfile is not something they run.

## 2. The sanitizer was never in the image

```text
IndexError: 4    # Path(__file__).resolve().parents[4]
```

Two halves. `_sanitizer_path()` counted four parents up — right in a repository
checkout, and an `IndexError` at `/app/app/input/sanitizer.py`, which has three.
It walks up looking for the directory now instead of counting.

The half underneath it is worse: `packages/image-sanitizer` **was not copied into
the image at all**, and neither was Pillow. So the secure-input path could not work
in a deployment under any circumstances — every upload would have been a 503, and
every test green, because the tests run where the package is a sibling directory.

Both fixed: the package and its one dependency are installed beside the app, with a
comment saying why Pillow is allowed there and still must not be imported by the
API.

## 3. Three attempts, no report on any of them — again

The order that reached the compile stage ended:

```text
status FAILED, failure_code LEASE_LOST
"The worker stopped responding on the last permitted attempt and never said why."
```

`LEASE_LOST` is the reaper's code for *the worker said nothing*, which was true and
says nothing about the drawing. The API log has no `/fail` for that job on any of
its three attempts.

The cause is the defect `CLAUDE.md` already records as fixed, one exception type
later. `ClaimLoop.Typed` named `WorkerException` and `CodexRunnerException`. The
third type that carries a code is **`CadAdapterException`** — what the CAD-IR gate
and the engine raise, and therefore what a refused document arrives as once the
compile repairs are spent. It walked straight past the reporting filter into the
claim loop's blanket backoff.

Fixed, and pinned by `TheThreeTypedFailuresAreAllNamed`, which enumerates the types
rather than exampling one. One example per type is exactly what let the second one
through.

**Measured after the fix**, same drawing, same answers:

```text
attempt 1, status FAILED, failure_code CAD_IR_INVALID
"CAD_IR_VERSION_TOO_NEW@$.schema_version"
```

One attempt instead of three, and a code a person can act on instead of silence.

## 4. The worker offered a version its engine does not speak

That message is the fifth finding and it is not about the drawing.

`supported_cad_ir` is what the scheduler checks before leasing a job, and it was
`WorkerCapabilities.CadIrVersion` — the constant compiled into **this worker
build**, 1.12. The capability manifest sent in the same request carried
`report.Engine.CadIrVersion` — what the **engine** answered, 1.11, because the
container image on this machine is six days old and predates CAD-IR 1.12.

Nothing compared the two. So the API leased a 1.12 job to a worker whose engine
speaks 1.11, the worker paid for a vision call and a compilation, and the engine
refused the document at the first line.

The check that would have withheld the job existed and was reading the wrong
number. It reads the engine's now, for the reason the launcher compares digests
against the bytes on disk: **what a component is beats what something upstream
believes about it.**

## 5. What is left, and is not a defect

The engine image is stale. Rebuilding it is the next thing on this machine and was
not done tonight — it is a long build against the Debian package hosts, and the
finding is recorded rather than papered over.

One thing about the model's behaviour is worth keeping, because it is the only
observation here that is about quality rather than plumbing. On the first order,
the **initial compilation was canonically valid** and all three repairs were not:

```text
cad-ir.json          VALID
cad-ir-repair-1.json FEATURE_DEPENDENCY_MISSING  $.features[2].inputs.source_body
cad-ir-repair-2.json FEATURE_DEPENDENCY_MISSING  (the same)
cad-ir-repair-3.json FEATURE_DEPENDENCY_MISSING  (the same)
```

Something after the canonical gate refused the first document — the shape claim or
the build — and each repair then broke the dependency graph in the same place and
never recovered. Three rewrites, three identical mistakes. That is a prompt
question rather than a contract one, and it needs a run against a current engine
image before it is worth acting on: the version refusal above may well be what the
repair loop was reacting to.

## What this run says about the perimeter

The parts built today worked. The account was created, the session cookie carried
it, CSRF was enforced on every write, the order recorded its owner, and the drawing
went through quarantine and a sanitizer running in a child process with the
ceilings this platform can give it.

None of that is what the run found, and that is the point of running it. Every
defect above sits in a seam — image, process, exception type, or a number copied
from the wrong side of a boundary — and a seam is precisely what a test suite that
imports its subject cannot see.
