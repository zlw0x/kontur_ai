# ADR-012: authenticated checksummed artifact transfer for MVP

## Status

Accepted for TASK-009.

## Decision

Use authenticated API endpoints for worker manifests, input download, artifact
upload and completion. The worker initiates every connection. Input and output
bytes are accepted only when manifest size and SHA-256 metadata match.

The local MVP uses a filesystem-backed `LocalArtifactStore` with
server-generated object keys and atomic replacement. Its interface is narrow
enough to replace with S3-compatible storage without changing worker trust
rules.

## Consequences

- The VPS never receives worker shell or Codex/KOMPAS credentials.
- User-controlled filenames cannot escape the object-store root.
- A completion request cannot refer to bytes that were not uploaded for its
  leased job.
- Multi-instance production deployment requires shared S3-compatible storage;
  local filesystem storage is not a production scaling choice.
