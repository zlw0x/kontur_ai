# TASK-009: manual end-to-end CAD without AI

## Flow

1. An authenticated manual API request submits CAD-IR.
2. The backend runs JSON Schema and semantic validation.
3. A typed `BUILD_CAD` job is queued with an idempotency key.
4. The worker claims a compatible lease over its outbound connection.
5. The worker downloads a manifest and CAD-IR, verifying size and SHA-256.
6. `KompasApi7Adapter` builds `model.m3d`.
7. The worker uploads M3D and its validation report with SHA-256.
8. The backend verifies uploaded bytes before idempotent completion.
9. The authenticated manual API exposes status and result download.

Local-development HTTP is accepted only for loopback addresses. Non-loopback
worker enrollment requires HTTPS.

## Failure paths covered

- unauthenticated manual and worker requests;
- incompatible worker capabilities or CAD-IR version;
- expired/wrong lease owner;
- input size/checksum mismatch;
- upload checksum mismatch or oversized artifact;
- completion metadata that does not match stored bytes;
- completion without M3D;
- duplicate completion and duplicate artifact identity.

## Real-machine acceptance

On 2026-07-27, five consecutively submitted jobs completed on their first
attempt. Each produced and uploaded both M3D and `validation-report.json`.
M3D sizes were 53,043–53,064 bytes. There was no manual file copying between
the API storage and the worker workspace, and no orphan KOMPAS process
remained.

The one-shot worker command used by this acceptance run was:

```powershell
cad-worker run --once
```
