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

The migration service is idempotent. It can adopt a complete v1 database
created before the migration journal existed, but refuses a partial schema.

## Trusted Windows worker

```powershell
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- doctor
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-codex
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-kompas
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- enroll `
  --server https://cad.example.com `
  --token <one-time-enrollment-token>
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- run
```

Only loopback HTTP is allowed. Remote enrollment must use HTTPS. To remove the
local worker credential:

```powershell
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- logout
```

This does not remove the user's independent Codex CLI login.

## Smoke test

Open the web page, enter `MANUAL_API_TOKEN`, upload a clear PNG/JPEG drawing of
a rectangular plate with dimensions in millimetres and optional circular
through-holes. The expected state sequence is:

```text
PENDING -> LEASED -> READY
                  \-> WAITING_FOR_USER_ANSWERS -> PENDING -> READY
```

At `READY`, inspect the 3D preview and download M3D, STEP, STL and the validation
report. A failure must retain a typed code in worker/API logs; do not bypass a
schema, geometry invariant or checksum to force completion.

## Stop and preserve data

```powershell
docker compose --env-file .env -f infra/docker-compose.yml down
```

Do not add `-v` unless PostgreSQL and artifact volumes are intentionally being
deleted.

