# Local Windows worker

Native .NET 8 console worker. TASK-005 provides:

- `enroll --server URL --token TOKEN` with a DPAPI-protected credential;
- `doctor`;
- `run` with outbound-only polling and bounded exponential backoff;
- `run-job PATH` with an atomic fake checkpoint and validation artifact;
- `logout`.

The credential is stored under the current user's Local Application Data and is
never written to config or logs. KOMPAS and Codex remain disabled until their
probe milestones.
# Local worker

Commands:

- `doctor`
- `enroll --server URL --token TOKEN`
- `run [--once]`
- `run-job PATH [--fake-cad]`
- `probe-kompas`
- `resolve-selectors [DIR]`
- `logout`

`resolve-selectors` is the selector stability acceptance: it builds a plate,
resolves the acceptance selector set, widens and rebuilds it, reopens the saved
M3D in a second KOMPAS process and drills a third hole, checking that every
selector still names what it meant. Needs KOMPAS installed; exits non-zero if
any check fails. See `docs/acceptance/POSTMVP-005-selector-stability.md`.

`run` makes outbound-only claims, verifies manifest downloads, maintains the
lease, invokes the trusted adapter and uploads checksummed artifacts.
