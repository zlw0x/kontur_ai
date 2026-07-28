# ADR-018: CAD-IR 1.1 is the canonical form, and the output profile is a dialect

## Status

Accepted on 2026-07-28.

## Context

CAD-IR 0.1.0 was shaped around the one part the MVP builds: a `part` header, a
flat feature list with untyped `inputs`, parameters that were floats with a
unit string, and an expression language. Every operation the roadmap adds would
have widened that shape in a different direction.

Nothing in this decision adds geometry. The buildable surface is unchanged.

## Decision

### The document declares itself

`schema` and `schema_version` are checked before any feature is read. A
document from a newer build may use a field this one would silently ignore, so
`CAD_IR_VERSION_TOO_NEW` is a distinct answer from `CAD_IR_VERSION_UNSUPPORTED`:
the first tells an operator to upgrade the worker, the second sends them
looking for a malformed document.

### Features form an explicit graph

`depends_on` and `produces` replace positional convention. A later operation
names the body the base extrusion made rather than "whatever the previous
feature left behind", which stops meaning the same thing as soon as features
are reordered. The validator rejects duplicate ids, missing dependencies,
self-reference, cycles, and dependencies declared after their dependent —
features build in array order, so the last of those would build too late.

A result reference must also be *reachable*: using `body.main` without
depending on the feature that produces it is rejected, because the reference is
only meaningful if that feature is guaranteed to have run.

### Identifiers are readable

`^[a-z][a-z0-9_.-]{1,63}$`. Random GUIDs would make a repair prompt, a log line
and a diff between two versions of the same part unreadable.

### There is no expression language

A value is a number or `{"parameter": id}`. Arithmetic written by a model is a
second thing to validate and a second thing to get wrong, and no supported
geometry needs it. The C# expression evaluator — 130 lines whose only job was
to safely evaluate strings a model wrote — is deleted rather than left unused.

### Expectations do not drive the build

They are what an independent verifier checks afterwards. A build that could
read them could satisfy them by construction, which would make them worthless.
A document with no bounding-box or body-count expectation is rejected: without
them a wrong model looks exactly like a right one.

### Intent, not execution

No COM handle, face or edge index, file path or command may appear. The closed
schema is the first defence — such a value has no field to live in. A scan of
free text is the second, for anything smuggled through a name, label or note.

### The model stays out of the document

Per ADR-017, model and CLI version belong to the AI run. In the document they
would change the canonical hash of an identical part whenever the model
changed, which is precisely what the hash must not do.

### Normalisation is a translation, never a repair

The normalizer refuses anything 1.1 cannot express rather than approximating
it: real arithmetic, a recorded assumption, an unresolved item, a non-millimetre
unit, an advisory invariant. A cut's `source_body` *is* derived from its
dependency, because 0.1.0 already stated that relationship through
`depends_on` — and only when the dependency is unambiguous.

Lineage (both versions, both hashes, the normalizer version) is stored beside
the artifact. A document containing its own hash could not have one. The
original is kept as an artifact, so nothing 0.1.0 carried is lost even where
1.1 has no slot for it.

### The Codex output profile is a separate, narrower schema — in a narrower dialect

`schemas/cad-ir-mvp-output.schema.json` constrains generation to what the
adapter can build: one plane, one direction, two operations. The canonical
schema stays wider because a later version needs it.

That file is **not** a general JSON Schema. It is the structured-output
response format, and that dialect rejects things ordinary JSON Schema allows:

1. no `oneOf`
2. every schema node must declare a `type` — a bare `const` is rejected
3. every array must declare `items`
4. every object must list *all* its properties as `required`
5. every object must set `additionalProperties: false`

Rule 4 has teeth: strict mode has no optional properties, so a field kept "just
in case" becomes a field the model is forced to invent.

## Consequences

Jobs now require CAD-IR 1.1, so a worker still declaring 0.1.0 stops being
offered them. That is the capability gate behaving correctly; the worker,
prompts and drawing pipeline were bumped together.

Old completed orders are unaffected. Their artifacts are files and are served
unchanged; a 0.1.0 CAD-IR artifact downloads exactly as it was written.

The dialect rules are encoded in a test derived from the 0.1.0 schema the API
had been accepting, not guessed. Each of the three rejections that produced
them cost a full AI run, and the repair loop paid for it three times before
giving up — which is the argument for testing the schema offline rather than
discovering its constraints in production.

`reference_geometry` exists in the canonical model but must be empty. The slot
is there so 1.2 can fill it without moving anything; accepting entries now
would mean accepting a shape nothing validates.
