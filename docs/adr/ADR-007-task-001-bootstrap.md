# ADR-007: TASK-001 local-first repository bootstrap

## Status

Accepted for milestone TASK-001.

## Decision

Create a polyglot monorepo with FastAPI and Next.js running in Docker Compose, while the Windows worker remains a native .NET 8 process. The worker exposes only an explicit fake mode until a real KOMPAS SDK/type-library probe exists.

## Consequences

- CI can run without Codex authentication or KOMPAS.
- Local development can validate API/web boundaries early.
- Real CAD integration is deliberately blocked behind evidence from the installed Windows SDK.
- The current Docker Compose is a development stand, not a production deployment.
