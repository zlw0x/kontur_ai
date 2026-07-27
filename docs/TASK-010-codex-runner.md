# TASK-010: safe local Codex runner

## Installed runtime evidence

- Standalone CLI: `codex-cli 0.145.0`
- Authentication status: `Logged in using ChatGPT`
- Installed under the current user's Local Application Data.
- Desktop-app binaries under WindowsApps are not used because their ACL does
  not expose them as a general shell CLI.

No OpenAI API integration or API key was added.

## Enforcement

The wrapper uses argument-list process invocation rather than a shell command.
Every run is ephemeral, non-interactive, schema-bound and workspace-contained.
Web search and command environment inheritance are disabled. The native Codex
permission profile grants read access only to minimal runtime paths and the
single stage workspace.

The JSONL parser records thread ID and usage. If Codex emits a command,
file-change, MCP or web-search item, the wrapper terminates the process tree
and returns `CODEX_POLICY_VIOLATION`. Timeout, capacity, malformed protocol,
missing output and invalid JSON have separate error codes.

Budgets are reserved before process start and independently cap total and
repair runs. Model names are configurable because availability belongs to the
authenticated local CLI/account, not to the VPS contract.

## Real probe

On 2026-07-27, `cad-worker probe-codex` succeeded with local ChatGPT auth:

- sandbox: `cad-runtime-read-only`;
- no tool-use events;
- input tokens: 11,617;
- output tokens: 46;
- output SHA-256:
  `19EBEBC4FA400C2449A639BBC14A459820E08C43515599777526EA9F3E542B22`.

The probe used a fixed prompt and schema and did not include user content.

## Official interface checked

The implementation was checked against the installed CLI help and the current
Codex manual sections for non-interactive mode, structured output, permissions
and sandboxing:

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/permissions
- https://learn.chatgpt.com/docs/sandboxing
