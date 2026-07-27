# ADR-013: runtime AI is local, schema-only and tool-free

## Status

Accepted for TASK-010.

## Decision

Invoke AI only through the standalone, locally authenticated `codex exec`.
Runtime prompts receive a stage-specific workspace and must return a
schema-constrained JSON object. They have no legitimate command, write, MCP,
or web-search operation; observing any such event invalidates the run.

Use a native permission profile rather than `danger-full-access` or
`--dangerously-bypass-approvals-and-sandbox`. Do not pass API keys, worker
credentials or VPS configuration into the child process.

## Consequences

- Codex authentication remains on the trusted Windows user account.
- AI cannot call KOMPAS; only validated JSON reaches trusted deterministic
  code.
- Stages that genuinely need a new tool require a separate security review and
  ADR rather than silently widening this profile.
- JSON Schema remains necessary but not sufficient; semantic CAD-IR validation
  still runs after AI output.
