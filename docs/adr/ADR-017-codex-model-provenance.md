# ADR-017: every Codex run names its model, and provenance is recorded separately from the request

## Status

Accepted on 2026-07-28.

## Context

POSTMVP-003B left `model = NULL` on every AI run. The router returned no model,
so `codex exec` used whatever the CLI defaults to. Two runs of the same prompt
over the same drawing could be served by different models with nothing
recording which, and the AI figure in a cost breakdown was attributed to
nothing.

The CLI accepts `-m/--model`, and the command line outranks every config layer.
The runner already passed `--ignore-user-config`, so the user's `config.toml`
was not the source either — the model came from the CLI's built-in default,
which is external behaviour that can change on upgrade.

## Decision

### Routing is a versioned profile, not a lookup

`CodexRoutingProfile` holds every model identifier and reasoning effort, keyed
by stage, under a version string. A stage with no rule raises
`CODEX_ROUTE_MISSING` rather than falling back: an unrouted run is exactly the
unattributable cost this removes.

`CodexRoutingDecision` is captured **before** the process starts, so a run that
crashes still has a routing decision attached.

### The model is always passed explicitly

`--model` is always on the command line and the runner refuses a request
without one (`CODEX_MODEL_UNSPECIFIED`). Combined with `--ignore-user-config`,
the model comes from the profile and from nowhere else.

### Requested and observed are separate fields

Collapsed into one `model`, "we asked for Terra" is indistinguishable from
"Terra is what ran", and only the second justifies charging Terra's weight.
`model_observation_status` says which is known:

| Status | Meaning | Billable model |
|---|---|---|
| `VERIFIED` | the CLI confirmed the requested model | observed |
| `EXPLICIT_NOT_REPORTED` | requested on the command line, CLI silent | requested |
| `MISMATCH` | the CLI reported a different model | none |
| `UNKNOWN` | neither requested nor reported | none |

**codex-cli 0.145.0 reports no model in any event**, so `VERIFIED` is
unreachable today and every routed run lands on `EXPLICIT_NOT_REPORTED`. The
event parser reads a model from several plausible shapes so that a CLI which
starts reporting one is believed immediately rather than after someone notices.

### A mismatch is never resolved in favour of either model

Charging the requested model would overstate; charging the observed one would
trust a CLI that has just contradicted an explicit instruction. The run is
weighted at the neutral default, the audit fails, and `finalize()` refuses the
snapshot unless an operator passes `allow_unverifiable`.

A draft is still written. The resources were genuinely consumed and somebody
has to be able to look at what they cost.

### Provenance is more than the model

```text
provenance_sha256 = SHA256(
    input_sha256 + prompt_bundle_sha256 + requested_model
  + requested_reasoning_effort + codex_cli_version + routing_profile_version)
```

Knowing the model is not enough to reproduce a result. A different answer under
a new prompt, a new CLI or a different reasoning effort is a different question
having been asked, not a regression to chase, and this fingerprint is what
separates the two.

The execution descriptor stored alongside is normalised rather than the raw
argument list, which carries workspace paths and file names — local detail with
no business meaning in a record that may be exported.

### Model provenance stays out of CAD-IR

CAD-IR describes geometric intent. Putting the model in it would change the
canonical hash of an identical part whenever the model or CLI changed. AI
provenance lives on the resource event; CAD-IR references the attempt, not the
model that produced it.

## Consequences

`model` is renamed to `requested_model` (migration 0004) rather than
duplicated, because the old column only ever held NULL. Rows written before
this change read as `UNKNOWN`, which is what they meant, and jobs made of them
are correctly reported `UNVERIFIABLE`.

Ingestion now rejects an AI run that names no model, so a worker that skipped
routing cannot file unattributable cost. The check is on the batch rather than
on the model, so historical rows still load.

Model-weighted allocation only becomes meaningful now. Every earlier job in the
ledger is unattributable and must not be used to calibrate weights.

The routing profile is deliberately static. Escalation — routing a hard case to
a stronger model — is a later decision that needs its own evidence; this ADR
only guarantees that whatever ran is recorded.
