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
- `logout`

`run` makes outbound-only claims, verifies manifest downloads, maintains the
lease, invokes the trusted adapter and uploads checksummed artifacts.
