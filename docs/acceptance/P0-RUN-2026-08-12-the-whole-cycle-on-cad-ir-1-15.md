# The whole cycle on CAD-IR 1.15, and the health check that could never pass

**Date:** 2026-08-12 · **Machine:** the one Codex is signed in on ·
**Drawing:** `apps/web/public/sample-drawing.png` — 60 × 30 × 8 plate, two Ø5 through
holes at x = 15 and x = 45.

The contract had moved to 1.15 over four milestones and the engine image still spoke
**1.12**, which is the refusal that ended `P0-RUN-2026-08-09` and the first thing
`P0-RUN-2026-08-09b` had to fix. Third time: the drift is the most reliably repeated
failure this deployment has, and it is repeated because nothing rebuilds the image when
the contract moves.

## What happened

```text
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:latest .
docker run --read-only --network none … describe          cad_ir_version 1.15, 47 capabilities
dotnet test packages/build123d-launcher/tests             35 of 35, nothing skipped
docker compose up -d                                      api healthy, 12 migrations applied
local-worker run                                          registered: supported_cad_ir ["1.15"], codex available

POST /api/v1/auth/register                          201   session + CSRF
POST /api/v1/drawing-jobs        (image/png)        201   WAITING_FOR_LOCAL_WORKER
  → DRAWING_ANALYSIS                                      WAITING_FOR_USER_ANSWERS, 1 question
POST /api/v1/drawing-jobs/{id}/answers              200   15 mm
  → DRAWING_ANALYSIS → build → verify                     MANUAL_REVIEW, 6 artifacts
POST /api/v1/operator/orders/{id}/review            200   approve, v1 → v2
GET  /api/v1/drawing-jobs/{id}                            READY
GET  …/artifacts/STEP, …/artifacts/STL                    22 682 and 51 484 bytes, downloaded as the owner
```

## The part

From the validation report the worker wrote by reopening its own exported files:

| | |
|---|---|
| bounding box | expected [60, 30, 8], **measured [60, 30, 8]** |
| volume | **14085.8407 mm³** |
| through holes | expected 2, mesh-derived genus 2 |
| mesh | 1028 triangles, 0 open edges, 0 inconsistent normals |
| solids | expected 1, measured 1 |
| engine | build123d 0.11.1 / OpenCascade 7.9.3.1.1, **cad_ir_version 1.15** |

```text
60 × 30 × 8 − 2 × π × 2.5² × 8 = 14400 − 314.1593 = 14085.8407
```

Four decimal places against a number nothing in the pipeline computed — and the same
digits as the 1.12 run, which is what a contract change is supposed to leave alone.

## The question it asked

One clarification round, and the question was a real one:

> *What is the distance in mm from the left edge to the left hole centre?*

Answered 15. The document it then wrote carries seven parameters — including
`left_hole_center_offset: 15`, the answer, as a parameter rather than a literal — one
`solid.extrude` with two islands, and three expectations. That is the reading stage
asking for the one dimension the raster does not settle, which is what the clarification
loop is for.

## What the run found

**`probe-codex` could never pass.** It builds a `CodexStageRequest` and never named a
model; `CodexRunner` requires one and answers `CODEX_MODEL_UNSPECIFIED`. So the
operator's first health check — the one the runbook tells them to run *before*
enrolling — failed on every machine it had ever been run on, and failed in a way that
reads like "Codex is broken here" rather than "this command is".

Fixed by asking the router for a route rather than writing a model name into the probe:
`CodexStage.InputTriage`, which is the cheapest rule the routing table has and whose
only question is whether the CLI answers at all. Taking it from the router means the
probe exercises the same decision the pipeline makes and cannot drift from it. Measured
after the fix:

```json
{"status":"CODEX_OK","auth":"local-chatgpt","model":"gpt-5.6-luna",
 "Usage":{"InputTokens":11743,"OutputTokens":46}}
```

**`doctor` reports `"mode":"fake"` as a string literal.** It is not a state — the field
is written that way in `WorkerCore.cs` whatever the worker is configured to do, and this
worker went on to run real Codex and a real container in the same session. Recorded
rather than fixed here: it is a one-line change in a diagnostic, and changing a
diagnostic in the middle of an acceptance run is how a run stops being evidence.

**A stale image is silent until it is asked.** Nothing in CI or in the release routine
rebuilds `cad-ai/cad-worker` when `CAD_IR_VERSION` moves, and the failure it produces —
a worker that registers, heartbeats and then refuses every document at the first line —
looks like a code regression. The runbook already says to rebuild after pulling; what it
cannot do is make anybody.

## Reproducing

```bash
docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:latest .
docker run --rm --read-only --network none --tmpfs /tmp cad-ai/cad-worker:latest describe
```

If `cad_ir_version` there disagrees with `cad_ir.canonical.CAD_IR_VERSION`, the image is
stale and nothing is wrong with the code.

---

## The second stale image, and the one that had been stale for nine days

The studio told every visitor:

> Чертёж **не отправлялся** и модель **не строилась**. Всё, что показано ниже, —
> пример того, как выглядит работа сервиса, а не ваша деталь. Скачивание отключено.

That banner is correct and deliberate: `order && !authed` means a visitor who is signed
in as nobody gets the flow and not a part (P0-1). The defect was that **there was no way
to stop being nobody**. Read from the running page:

```text
scripts served by /studio            7
any of them calling /auth/me         false
any of them calling /auth/register   false
requests to the API                  none
```

The sign-in card is gated on `authChecked`, which is set in the same effect that calls
`/auth/me` — and the call was not in the bundle at all. `infra-web` was built nine days
ago, and accounts landed in `2fcd1b6`. The source on disk had a sign-in form the whole
time; the deployment did not.

Rebuilt and restarted, with nothing in the page's code changed:

```text
GET  /api/v1/auth/me        401     (nobody, as expected)
POST /api/v1/auth/register  201     through the form, in the browser
auth card gone, demonstration banner gone, the account's address on the page
```

## What was built because of it

`scripts/check_deployment.py`. Neither stale image is a crash and neither is visible to a
test suite, because a suite runs against the working tree and the bug is that the
deployment does not. The check asks each component what it **is** — the engine through
`describe`, the API through `/auth/me`, the web by reading the scripts the page actually
serves — which is the launcher's rule (*what a component is beats what something upstream
believes about it*) applied to a deployment.

Measured against both failures:

```text
--engine-image cad-ai/cad-worker:claimfix   STALE  speaks CAD-IR 1.12, this checkout defines 1.15   exit 1
current stack                               OK     engine 1.15 / api / web                          exit 0
--web http://localhost:9999                 STALE  answered nothing                                 exit 1
```

The web branch is written against the failure this run found: it reads the served
bundles, not the source, because the source was right for nine days while the page was
not.

---

## The third defect: signing in and then being told to sign in

Reported from the panel after a successful sign-in and an upload. Reproduced in a
browser, and the sequence is the whole explanation:

```text
POST /api/v1/drawing-jobs   201   the page's own form, straight after signing in
GET  /api/v1/auth/me        200   anything at all: a reload, a second tab, an effect that runs twice
POST /api/v1/drawing-jobs   403   the same page, the same form, the same session
```

`/auth/me` **re-issues the CSRF token on every call** — deliberately, to close the
window where an old one is still accepted — by overwriting the hash the session
compares against. It did not rewrite the `cad_ai_csrf` cookie, and the page held its
token in React state from mount. So the second visit revoked the credential every
existing page was carrying, and left no way to notice: the cookie still held the value
from sign-in, which the server had already stopped accepting.

**Two bugs meeting.** The API handed out a credential and revoked it in the same breath;
the page kept a copy of something that was designed to change.

Fixed on both sides, because either alone leaves a way to lose:

- `/auth/me` sets the cookie to the token it returns. The cookie is the client's only
  durable copy — the comment beside it has always said it is readable *because the
  client has to copy it into a header* — so re-issuing without updating it is what made
  the rotation destructive.
- `api()` reads the token **from the cookie at the moment of the call** rather than from
  state, so a second tab can no longer disarm the first.
- A write refused with 401 or 403 refreshes `/auth/me` **once** and retries. If that
  fails the session is genuinely gone, and the page says so in words a customer can act
  on — "the session ended, sign in again, your order is still there" — instead of
  showing them the API's `sign in to continue`, which is a program talking to a program.

`test_asking_who_i_am_does_not_disarm_the_page_that_asked` asserts the cookie moves with
the token, that the new one works and the old one does not. Checked against the defect:
it fails without the cookie write and passes with it.

Verified afterwards in the browser, on the same sequence that produced the 403:
**201 Created**, the order id in the address bar, the real progress on the page, no
demonstration banner and no error.

**1014 python, typecheck clean, OpenAPI unchanged, all three images current.**

---

## The fourth: signed in at one address, refused at another

Reported again after the CSRF fix, and it is a different defect with the same words.
Reproduced by opening the site at `http://127.0.0.1:3000` while the API is named
`http://localhost:8000`:

```text
POST /api/v1/auth/register   201   the account, in the body
document.cookie              (none)
GET  /api/v1/auth/me         401   sign in to continue
```

`127.0.0.1` and `localhost` are **different hosts**, and a session is a cookie, and a
cookie belongs to a host. The browser accepted the answer and refused the cookie. The
page then showed the customer as signed in — because it took the reply as proof — and
everything they did afterwards was 401.

Three things were wrong, and each one alone is enough to lose an afternoon.

**The API address was baked in and the page's address was not.**
`NEXT_PUBLIC_API_URL` is fixed when the image is built, so a local deployment carries
`http://localhost:8000` whatever anybody later types into the address bar. `apiBase()`
now follows the page's own hostname **when the configured host is a loopback name** —
a local deployment, never a production domain, which is left exactly as configured.

**The page believed a reply instead of checking.** `setSession(...)` came straight from
the register/sign-in body. It is not proof: the body says who you are, the cookie says
whether the browser kept you. Sign-in now confirms with `/auth/me` before it claims
anything, and when the cookie did not survive it says so in a sentence somebody can act
on — which address to open — instead of leaving them signed in as nobody.

**The staff field was shown to everybody.** "Код из приложения *(для сотрудников)*" sat
on the only way in, under a comment claiming it was optional "so a customer is not shown
a field they can never fill". It cannot be asked for on demand — the API answers a
missing code and a wrong password with the same words on purpose, so nothing can learn
from the difference — so it is behind "Я сотрудник — нужен код подтверждения". A
customer never meets it; the click happens in the browser and discloses nothing.

Verified at both addresses after the fix. At `http://127.0.0.1:3000`: register through
the form, cookie kept, `/auth/me` 200, upload accepted, order id in the address bar, no
banner and no error.

**1015 python, typecheck clean, web builds, all three images current.**

---

## The fifth, and it was the other half of the fourth

`Failed to fetch`, reported straight after the loopback fix. The page had started
sending its requests to the host it was loaded from — which was the point — and the
API's allowlist named two spellings of "this machine" and refused the third.

A refused preflight reaches a script as `Failed to fetch` and nothing else: no status,
no origin, no cause. Measured before the fix, against a service that was running the
whole time:

```text
origin http://localhost:3000        200  allow-origin echoed
origin http://127.0.0.1:3000        200  allow-origin echoed
origin http://DESKTOP-LQGRUAU:3000  400  (refused)
origin http://192.168.1.42:3000     400  (refused)
```

So in `local` the **port** is pinned and the host is not, which is the same rule the
page now follows. Outside `local` nothing changes — there the origin is a real domain
and guessing at it is how a service ends up accepting authenticated requests from pages
it has never heard of. After:

```text
http://localhost:3000        200  access-control-allow-origin: http://localhost:3000
http://127.0.0.1:3000        200  access-control-allow-origin: http://127.0.0.1:3000
http://DESKTOP-LQGRUAU:3000  200  access-control-allow-origin: http://DESKTOP-LQGRUAU:3000
http://192.168.1.42:3000     200  access-control-allow-origin: http://192.168.1.42:3000
http://evil.example.com      400  (refused, no header)
```

And the page no longer repeats the browser at the customer: a `TypeError` from `fetch`
now reads *"the service did not answer at http://…:8000"* with the address it tried in
it, because `Failed to fetch` names neither the address nor anything to do about it.

`test_a_local_deployment_answers_the_address_it_was_opened_at` asserts both halves —
four local spellings answered, a foreign origin refused.

Verified end to end from the machine name: registered through the form at
`http://desktop-lqgruau:3000`, uploaded, order id in the address bar, no banner and no
error.

**1016 python, typecheck clean, OpenAPI unchanged, all three images current.**

---

## The sixth, and it was never the network

`Сервис не ответил по адресу http://127.0.0.1:8000` — the message added one commit
earlier, and it was wrong. The service was up and answering `health` on both spellings
throughout. Instrumented `fetch` in the page rather than trusting the message:

```text
POST /api/v1/drawing-jobs            201
GET  /api/v1/drawing-jobs/{id}       TypeError: Failed to fetch
```

The upload worked; the **status poll** did not. In the API's log:

```text
GET /api/v1/drawing-jobs/{id}
  → scheduler_diagnostics().report(job)
  → sql_protocol.workers()
  → WorkerCapabilityManifest(**row.capability_manifest)
  ValidationError: kompas_version — Extra inputs are not permitted
```

**One worker row left from before the KOMPAS removal** still carried
`kompas_version: null` — a probe worker registered on 2026-07-28. Migration 0006
rewrote the rows it knew about, and this one survived. `WorkerCapabilityManifest`
forbids unknown keys, which is right **at the door** and wrong on the way **out of the
database**: a stored row outlives the model that wrote it.

So every customer's status poll answered 500 — and an unhandled 500 carries no CORS
header, so a browser reports it as a network failure with no cause in it. Two of the
last three rounds were spent on a message rather than on the fault.

The order it was polling had **built correctly the whole time**: `MANUAL_REVIEW`, six
artifacts, STEP 22.1 KB and STL 50.3 KB. Nothing was wrong with the model; the page
could not ask about it.

Fixed where the asymmetry belongs: keys this build does not declare are dropped when a
manifest is read **out** of the database and named in the log; a worker **sending** one
is still refused. `test_a_manifest_from_before_a_field_was_dropped_is_still_readable`
asserts both directions, and fails without the fix.

This is the other half of a rule CLAUDE.md already states — *deleting a name rows still
hold turns a rename into an outage*. Migration 0006 got the order right. What was
missing was a reader that survives the row a migration missed.

Verified in the panel afterwards: poll 200, "Смотрит инженер", 62%, both files listed
with their sizes, no banner and no error.

**1017 python, typecheck clean, all three images current.**
