# ADR-037: an order belongs to somebody, and that somebody can be signed out

**Date:** 2026-08-09 · **Status:** accepted · **Migration:** 0009 ·
**Builds on:** ADR-036 (an order is a row)

## What was there

One credential, for everybody:

```python
def authenticated_manual_api(token: str | None) -> None:
    if token is None or not secrets.compare_digest(token, settings.manual_api_token):
        raise HTTPException(status_code=401, detail="manual API token is required")
```

`MANUAL_API_TOKEN` — a single static string, shared by every caller — guarded
`/api/v1/drawing-jobs`, the status poll, the answers endpoint, the transition
endpoint and every artifact download. And `orders`, added by 0008, had these
columns:

```text
id, status, version, created_at, updated_at,
latest_job_id, source_job_id, clarification_round
```

Nothing about whose. So anybody holding the token could read, download and cancel
anybody else's order, and the service had no way of telling one customer from
another because it had never written the difference down.

This is the one item on the audit that directly blocks letting strangers in, and it
is not the kind of thing that can be fixed in the handlers. Thirty checks are
thirty chances to forget one, and no check can consult a column that does not
exist.

## Decision

Three tables' worth of change and one rule.

- `users` — email (case-folded and unique), a bcrypt hash, a role, an optional
  TOTP secret, and `disabled_at` rather than deletion.
- `sessions` — the SHA-256 of the token the browser holds, the SHA-256 of the CSRF
  token issued with it, an expiry and a `revoked_at`.
- `orders.owner_id`, nullable, referencing `users`.

And `may_see_order(principal, owner_id)`, which is the **only** place the question
is answered, so there is one thing to get right rather than one per endpoint.

## What the decisions actually were

### `owner_id` is nullable, and stays nullable

Every order created before this migration has no owner, and there is nothing to
fill it with — the service did not record who uploaded them because it had no idea.
A backfill would have to invent an answer.

The tempting alternatives are both worse. Assigning them to the first account
created is a lie in a column that decides access. Making them visible to whoever
asks is not a guess but a giveaway. So an order with no owner is visible to
`operator` and `admin`, who can already see everything, and to nobody else — and
that is written down as an assertion rather than left to be inferred from the code.

The column will therefore never become `NOT NULL`. That is not technical debt; it
is the honest shape of a table that existed before the fact it now records.

### The refusal is 404 and not 403

A 403 answers "does this order exist?" for anybody willing to guess an id, and the
existence of an order is itself information about somebody else's business. An
order somebody does not own and an order that was never created return the same
status and the same body.

The same reasoning covers the operator surface: `/api/v1/admin/users` and
`/api/v1/manual/cad-jobs` answer 404 to a customer rather than 403, because a 403
confirms the endpoint is there and worth attacking.

### `MANUAL_API_TOKEN` becomes an operator, not a customer

The standing rule for this token is that it stays a **diagnostic operator key and
never a client authorization**. The way to keep that true while adding accounts was
not to take the token away from the client paths — it was to say what it
authenticates *as*.

It authenticates as an operator with no `user_id`. So it can look at everything, the
way an operator can, and it owns nothing: an order created with it has
`owner_id IS NULL` rather than belonging to a phantom user. `GET /api/v1/auth/me`
deliberately answers 404 for it, because it is not an account and inventing one
would be exactly the confusion the rule exists to prevent.

This also happens to be why the 935 existing tests stayed green through the change.
That is a consequence, not the reason.

### A session is a row, not a signed token

Revoking has to take effect on the next request rather than at expiry. A
self-contained signed token cannot be recalled without keeping a list of the ones
that have been, and once there is a list the token has bought nothing. So the
session is the list.

What is stored is the SHA-256 of the value the browser holds, so a copy of the
database is not a set of working credentials. A plain hash rather than bcrypt, and
that is not an inconsistency with the password column: this value is 32 bytes from
`secrets.token_urlsafe`, so there is no dictionary to run against it and no work
factor worth paying on every request. The password column *is* bcrypt, because a
password is something a human chose.

The user's own state is checked on every resolve, so disabling an account ends its
sessions without anybody having to find them — the version that goes looking is the
version that misses one.

### CSRF is bound to the session

Double submit in its usual form compares a cookie against a header. That loses to
anything that can write a cookie on a sibling subdomain: an attacker who sets both
halves passes a check that only compares them to each other.

The token here is checked against a hash stored **on the session row**, so passing
requires knowing a value that was sent to the browser once. The cookie is still set
and still readable by JavaScript, because the client has to be able to copy it into
a header — and a header is precisely what a cross-origin page cannot set without a
preflight this API answers only for its own origins.

Which is also why the check applies to cookie-authenticated requests only. A
credential that has to be typed into a header cannot be sent by accident.

### bcrypt, and why not Argon2id

Argon2id is the better algorithm: it is memory-hard, so an attacker cannot buy
their way out with parallelism the way they can against bcrypt.

It is not what this uses. `argon2-cffi` is not in the service's dependency tree and
`bcrypt` already is, and adding a compiled dependency to the API image is a change
with its own build and its own failure modes. The difference that matters here is
between *a hash* and *a hash that costs something*, and both candidates are on the
same side of that line. Recorded rather than hidden, so that moving is a decision
somebody makes on purpose.

Two details are not optional and are in the code with reasons:

- **The 72-byte pre-hash.** bcrypt reads 72 bytes and ignores the rest — silently
  in older releases, with an exception in 5.0. Without SHA-256 first, two
  passphrases sharing a 72-byte prefix are one password, and nobody notices because
  both users can still sign in.
- **The decoy hash.** An unknown address is verified against a real bcrypt hash of
  nothing in particular. Saying the same words in a microsecond for an unknown
  address and a quarter of a second for a real one is a working
  account-enumeration oracle attached to a form that was careful about its wording.

### MFA for operators and admins only

A customer with a second factor is a customer who cannot reach their own drawing
when their phone is flat. An account that can read *everybody's* drawings is a
different size of accident, and those two are the only accounts that can.

An account whose role requires a second factor and has no secret **cannot sign
in**. Letting it through because the secret is missing turns the requirement into a
suggestion that any failed enrolment silently switches off.

TOTP is RFC 6238 from the standard library — a counter, an HMAC and a truncation —
rather than another dependency in an image that has to be reviewed. The acceptance
window is one step either side, which is the RFC's own advice: zero produces a
factor that fails for reasons the user cannot see, and every extra step is another
code that is valid at any instant.

### A customer may cancel their order and do nothing else to it

`transition` accepts any target the state machine allows, which for an owner would
include declaring their own order `READY`. Customers get a whitelist of exactly
`CANCELLED`, so a status added to `OrderStatus` later is unreachable by a customer
until somebody decides otherwise. `EXPIRED` is deliberately not in it: expiry is
something the service observes, not something an owner announces.

## What it does not do

Rate limiting, account lockout and quotas are P1-7 and are not here. Without them,
this is an authentication system that is correct and not yet hard to grind against
— which is the right order to build them in, because a lockout without a correct
password check protects nothing.

There is no password reset, no email verification and no session listing. Each is a
flow with its own failure modes, and the pilot's accounts are created either by the
customer at the moment they upload or by an operator on the machine.

## What it is measured by

`apps/api/tests/test_accounts.py`, and every one of them is a failure path:

- another customer's order and an invented id return the same 404 and the same body
- an order with no owner is visible to staff and to nobody else
- a signed-out session is refused on the very next request, not at expiry
- a disabled account's live session stops resolving without being revoked
- a mutating request with no CSRF token, with somebody else's, and with one echoed
  into both the cookie and the header, are all refused
- a password never appears in any log record, asserted by running sign-up and
  sign-in with logging at DEBUG and grepping everything captured
- an unknown address still pays for a bcrypt verification
- a passphrase longer than 72 bytes is not truncated
- an operator cannot sign in without a code, and cannot sign in at all with no
  secret enrolled
