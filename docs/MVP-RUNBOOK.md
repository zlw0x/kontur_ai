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

The worker's credential is protected by DPAPI on Windows and by file permissions
elsewhere; which one is used is decided by the platform, not configured. To remove
it:

```bash
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- logout
```

This does not remove the user's independent Codex CLI login.

## Smoke test

Open the web page, enter `MANUAL_API_TOKEN`, and either press **Попробовать на
образце** — which loads `apps/web/public/sample-drawing.png`, the same 60 x 30 x 8
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

