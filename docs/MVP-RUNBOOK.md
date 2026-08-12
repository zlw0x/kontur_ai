# MVP runbook

## VPS or local Docker host

1. Copy `.env.example` to `.env`.
2. Replace PostgreSQL, worker-enrollment and manual API secrets. Do not use the
   example values on a networked host.
3. Set `NEXT_PUBLIC_API_URL` to the browser-reachable API URL and `WEB_ORIGIN`
   to the exact web origin.
4. Put TLS/reverse proxy in front of ports 3000 and 8000 for a remote host.
5. Start and inspect:

```powershell
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
docker compose --env-file .env -f infra/docker-compose.yml ps
Invoke-RestMethod http://localhost:8000/health
```

Keep `--build`. `up -d` on its own reuses the existing images, so an API
container can keep serving a previous contract while the worker already sends
the new one — which surfaces as the worker's batches being rejected with 422
and nothing else obviously wrong.

The worker has the same trap in reverse: JSON Schemas are copied into its build
output, so `dotnet run --no-build` can leave it sending Codex a schema from
before your change. Rebuild after touching anything under `schemas/`.

The migration service is idempotent. It can adopt a complete v1 database
created before the migration journal existed, but refuses a partial schema.
Later migrations are applied in order and skipped once recorded in
`schema_migrations`; `0002_resource_ledger` adds the resource ledger, pricing
profiles, cost snapshots and the worker capability registry.

After upgrading, an older worker keeps authenticating but stops receiving new
jobs: it publishes no capability manifest, and jobs created after this
migration declare the operations they require. Update and restart the worker
before expecting it to pick anything up — see
[`docs/TASK-POSTMVP-002-COST-ENGINE.md`](TASK-POSTMVP-002-COST-ENGINE.md).

## Trusted worker

Linux or Windows since ENGINE-MIG-008: the worker is plain `net8.0` and the CAD
engine is a container. Windows is still supported because that is where an
operator's Codex login often is; it is no longer required by anything.

```bash
W="dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj --"
$W doctor
$W probe-codex
$W describe-engine          # starts the CAD engine and prints what it is
$W enroll --server https://cad.example.com --token <one-time-enrollment-token>
$W run
```

`describe-engine` replaces `probe-kompas`. It is the check that matters now: a
container runtime that is not installed, an image that is not pulled or a mount
that is not permitted are what an operator needs to find out before a customer
does.

The engine is configured in `worker.json` under `cad_engine` — see
[`examples/local-worker.config.example.toml`](../examples/local-worker.config.example.toml).
`container` is the default and the mode with the isolation; `process` runs the
engine through a local interpreter and is for a developer machine.

### Running the engine tests against a real engine

Both suites skip themselves where there is nothing to run against, so a green
run says less than it looks like until one of these is set:

```powershell
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:ci .
$env:CAD_ENGINE_IMAGE  = "cad-ai/cad-worker:ci"     # container mode
$env:CAD_ENGINE_PYTHON = ".venv-cad\Scripts\python.exe"  # process mode
dotnet test packages/build123d-launcher/tests --nologo
```

With neither, 11 of the 35 skip. With both, all 35 run — and they are the only
check that the argument list this side builds and the invocation the other side
accepts are still the same contract.

**Rebuild the image after pulling.** A tag points at whatever was last built under
it, so an image from before a CAD-IR version bump keeps answering with the old
version and the container tests fail — reporting exactly what a code regression
would report, in the same four tests. `describe` says which version is really in
there:

```powershell
(docker run --rm --read-only --network none --tmpfs /tmp `
  cad-ai/cad-worker:ci describe | ConvertFrom-Json).cad_ir_version
```

If that disagrees with `cad_ir.canonical.CAD_IR_VERSION`, the image is stale and
nothing is wrong with the code.

The interpreter needs the worker's dependencies, not only the engine:
`pip install -r apps/cad-worker/requirements.txt`. A virtual environment created
to read build123d's source has build123d and nothing else, and the failure that
produces is an import error a long way from its cause.

The worker's credential is protected by DPAPI on Windows and by file permissions
elsewhere; which one is used is decided by the platform, not configured. To remove
it:

```bash
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- logout
```

This does not remove the user's independent Codex CLI login.

## Accounts

Since 0009 a customer signs in rather than typing a shared token. The first
administrator is made on the machine, because there is deliberately no public way
to create one — a form that hands out the role which reads everybody's drawings is
a door rather than a form:

```bash
CAD_AI_NEW_PASSWORD='...' python scripts/create_user.py --email ops@example.com --role admin
```

The password is read from the environment rather than from an argument, which
would be in `ps` and in the shell history. A TOTP secret is printed **once** for
`operator` and `admin`; enrol it in an authenticator app straight away, because it
is stored to verify codes against and is never shown again. Customers have no
second factor on purpose — a customer locked out of their own drawing by a flat
phone is a worse trade than the risk it removes.

Every account after the first is made through `POST /api/v1/admin/users` by an
admin. Customers create their own from the page.

`MANUAL_API_TOKEN` still works and is still what it always was: **a diagnostic
operator key, never a client authorization**. The API treats it as an operator, so
it can read any order and owns none — an order created with it has no owner rather
than belonging to an invented user.

## Limits

One account may have **3 orders in flight** and start **20 in a day**, and may get a
password wrong **10 times** before a fifteen-minute lockout. All three are in
`app.accounts.limits` with the reasoning beside them.

A quota refuses with `429` and a `Retry-After`; a sign-in refuses with the same `401`
as a wrong password, because a `429` on a sign-in form announces that the address has
an account. Staff and `MANUAL_API_TOKEN` are exempt from the order quotas — an
operator diagnosing the engine is not the load they protect against.

Per-IP request rate limiting is **not** here and is the reverse proxy's job (P1-6):
this service sits behind one and sees whatever `X-Forwarded-For` it is handed, so an
application-level version would be theatre.

## The moderation queue

`AUTOMATIC_ACCEPTANCE` is **off** by default, which is a change in behaviour rather
than a new option: a finished build now stops at `MANUAL_REVIEW` instead of reaching
the customer. An operator opens `/operator`, looks at the delivered files, and does
one of three things — approve (`READY`), reject (`FAILED`, reason required), or send
it back (a fresh reading round, reason required and shown to the model).

Every decision writes a row in `order_reviews` in the same transaction as the status
change, so an order cannot become `READY` without a record of who released it. A
decision carries the version the operator was shown; if somebody else decided in the
meantime it comes back `ORDER_VERSION_CONFLICT` rather than overwriting them.

To restore the old behaviour for a demonstration:

```bash
AUTOMATIC_ACCEPTANCE=true
```

Both branches are covered by tests. The `true` case is the one that used to be the
only behaviour, and a setting whose `true` case nobody exercises stops working
quietly.

## Is what is deployed built from what is checked out?

```bash
python scripts/check_deployment.py
```

Run it after `docker compose up` and before believing anything. Three images make up
this service and **two of them were stale on the same day**, in ways that looked like
nothing at all:

- the engine image spoke CAD-IR 1.12 against a contract at 1.15, so every document was
  refused at its first line — a worker that registers, heartbeats and then fails. Third
  time (`P0-RUN-2026-08-09`, `-09b`, `-12`);
- the web image was built before accounts existed, so the studio had **no way to sign
  in**. Every visitor saw "the drawing was not sent and no model was built" and
  downloads stayed disabled. Nine days, and the only symptom was a page that looked
  finished.

Neither is a crash and neither is visible to a test suite, because a suite runs against
the working tree and the bug is that the deployment does not. The check asks each
component what it *is* — the engine through `describe`, the API through `/auth/me`, the
web by reading the scripts the page actually serves — rather than trusting a tag.

## Smoke test

Open the web page, sign in (or register — it signs you in), and either press
**Попробовать на образце** — which loads `apps/web/public/sample-drawing.png`, the same 60 x 30 x 8
plate the acceptance runs build — or upload a clear PNG/JPEG drawing of a
rectangular plate with dimensions in millimetres and optional circular
through-holes. The expected state sequence is:

```text
PENDING -> LEASED -> READY
                  \-> WAITING_FOR_USER_ANSWERS -> PENDING -> READY
```

Both branches are normal. The same drawing can take either on consecutive runs:
the model is asked what it can see, and when it is unsure the design says ask
rather than invent.

At `READY`, inspect the 3D preview and download M3D, STEP, STL and the validation
report. The dimensions the page shows are read out of that validation report, so
they are what was measured on the exported file — if they disagree with the
drawing, the model is wrong, not the label. A failure must retain a typed code in
worker/API logs; do not bypass a schema, geometry invariant or checksum to force
completion.

A worked example of both branches, with the four defects the first browser run
found, is in
[`docs/acceptance/WEB-END-TO-END-drawing-to-model.md`](acceptance/WEB-END-TO-END-drawing-to-model.md).

## Repository checks

```bash
python -m pytest -q
python scripts/generate_schemas.py --check
python scripts/validate_schemas.py
python scripts/check_openapi_compatibility.py
dotnet test CadAi.sln --nologo
```

`generate_schemas.py` without `--check` rewrites the generated schemas; run it
after changing a contract model, then commit the result.

## Stop and preserve data

```powershell
docker compose --env-file .env -f infra/docker-compose.yml down
```

Do not add `-v` unless PostgreSQL and artifact volumes are intentionally being
deleted.

## Bumping the CAD-IR version

Three edits and a rename, and nothing in any test:

1. `CAD_IR_VERSION` in `packages/cad-ir/cad_ir/canonical.py`, and the previous version
   added to `MIGRATABLE_VERSIONS`.
2. `CadIr.Version` in `packages/cad-engine-contracts/CadIr.cs`.
3. `git mv tests/fixtures/cad-ir/*.vOLD.json` to the new suffix, and the
   `"schema_version"` line inside each.

Then `python scripts/generate_schemas.py` and `python scripts/generate_output_profile.py`.

**No test source names a version.** Python asks `cad_ir_fixtures.fixture("plate")`, .NET
uses `CadIr.FileSuffix`, and CI derives the suffix from the contract.
`apps/api/tests/test_fixture_versions.py` fails if a literal appears anywhere in a `.py`,
`.cs` or `.yml` file — which is the check that exists because the last bump left three
container tests naming a file that no longer existed, and those tests skip themselves
unless `CAD_ENGINE_IMAGE` is set. A skip in the summary line looks exactly like a pass.
