# TASK-005: local worker skeleton

## Acceptance evidence

- Native `.NET 8` worker builds without KOMPAS or Codex.
- Enrollment calls the typed VPS endpoint and stores only worker ID/server in
  JSON config; the credential is protected by Windows DPAPI for the current
  user.
- The claim loop initiates outbound HTTP(S), rejects non-HTTPS enrollment
  targets except localhost, and backs off exponentially up to 60 seconds.
- Fake jobs persist `state.json` and `validation-report.json` using temporary
  files followed by atomic rename.
- `doctor` distinguishes `READY` from `AUTH_REQUIRED` without revealing secret
  material.

## Deferred by design

KOMPAS and Codex probes, real CAD execution, artifact upload and process Job
Objects belong to TASK-006, TASK-008 and TASK-010.
