# ADR-009: local worker credential and configuration

## Status

Accepted for TASK-005.

## Decision

Store non-secret worker configuration as JSON under Local Application Data and
protect the bearer credential separately with Windows DPAPI
`DataProtectionScope.CurrentUser`. The worker uses outbound HTTP(S) only and
allows plain HTTP solely for localhost development.

## Consequences

- Copying the credential file to another Windows account does not reveal it.
- Headless service-account migration requires explicit re-enrollment.
- CI can build and run fake jobs without a worker credential.
