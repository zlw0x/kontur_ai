# TASK-011–014: drawing pipeline, validation, web and deployment

## Milestone and acceptance

The milestone is a bounded vertical MVP:

```text
PNG/JPEG -> API job -> outbound Windows worker -> local Codex
  -> schema-valid CAD-IR -> trusted KOMPAS adapter
  -> M3D + STEP + STL -> independent validation -> web preview/download
```

Acceptance requires typed inputs, no AI-generated code execution, a bounded
clarification/repair loop, checksummed artifacts, real KOMPAS and Codex probes,
browser-visible output, restart-safe order context and a bootable Docker stack.

## Implemented controls

- drawing analysis, clarification and CAD-IR have separate versioned schemas;
- drawing text is explicitly untrusted prompt data;
- Codex runs non-interactively with local ChatGPT auth, no inherited API key,
  no web search and no allowed command/file/MCP tool use;
- the trusted CAD-IR validator and the narrower C# adapter parser are separate
  gates;
- safe arithmetic expressions support parameter references without `eval`;
- KOMPAS is called only through `KompasApi7Adapter` on an STA thread;
- STL validation independently checks finite non-degenerate triangles, manifold
  edges, connected bodies, bounding box and Euler-derived through-hole count;
- the API validates magic bytes, size and SHA-256 and persists drawing lineage;
- web stores the manual token only in `sessionStorage` and fetches protected
  artifacts with an authenticated request.

## Real end-to-end evidence

On 2026-07-27 a 40 × 20 × 10 mm plate drawing with one centered Ø6 through
hole was submitted over the HTTP API and processed by the real local worker.
Order `e6650675-4e7d-4098-9737-b1fc01871cf9` completed with seven artifacts:

| Artifact | Size |
|---|---:|
| M3D | 61,032 bytes |
| STEP | 11,819 bytes |
| STL | 14,554 bytes |
| validation report | 1,354 bytes |
| drawing analysis | 1,618 bytes |
| clarification questions | 41 bytes |
| CAD-IR | 3,355 bytes |

Independent geometry results were 84 triangles, 42 welded vertices, 126 edges,
one connected closed body, bounding box `[40, 20, 10]`, and genus 1. The web
rendered the STL with the central hole and exposed authenticated downloads.
The browser console was clean and no KOMPAS process remained.

During the same test Codex attempted one PowerShell tool call to calculate a
hash. The runner killed that process as `CODEX_POLICY_VIOLATION`; after the
trusted host supplied the hash, the constrained run completed without tools.
This verifies the runtime enforcement rather than relying only on prompting.

## Automated acceptance

- Python API/contracts: 38 passed; PostgreSQL integration: 1 passed.
- Codex runner: 9 passed.
- KOMPAS adapter: 7 passed.
- geometry validation: 3 passed.
- local worker pipeline: 2 passed.
- JSON schemas and generated OpenAPI: valid and backward compatible.
- Next.js typecheck/build: passed; production dependency audit: 0 findings.
- Docker API/web builds: passed.
- Compose migration, API health check and web HTTP 200: passed.

## Release boundary

This MVP accepts only a rectangular prism with circular through-holes. It does
not automatically approve safety-critical parts, provide operator moderation,
payments, quotas, backup automation, horizontal API scaling or the broader
feature vocabulary in the roadmap. Those are pilot/production milestones, not
hidden unfinished behavior.
