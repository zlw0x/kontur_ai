# Local Codex runner

`LocalCodexRunner` invokes only the standalone Codex CLI and reuses persisted
local ChatGPT authentication. It never accepts or forwards an OpenAI API key.

Runtime defaults:

- ephemeral session;
- JSONL event stream and structured final output;
- schema and every input path contained in the stage workspace;
- no web search;
- no inherited environment for model-generated shell commands;
- a native permission profile that reads only minimal runtime files and the
  stage workspace;
- no approvals or permission escalation;
- process-tree timeout;
- immediate failure and termination on command, file-change, MCP or web tool
  events.

Model IDs are deployment configuration. The router does not invent a model
slug when none is configured; it lets the authenticated CLI use its available
default.
