# From the site to a finished model, with nothing in the way

**Date:** 2026-08-17 · **Machine:** the one Codex is signed in on ·
**Mode:** `OPEN_LOCAL_ACCESS=true` · **Drawing:** the sample plate, 60 × 30 × 8, two Ø5
holes at x = 15 and x = 45.

Driven through the browser at `http://localhost:3000/studio`, clicking what a visitor
clicks. No account, no password, no operator approval, no second window.

## What happened

```text
open /studio                          no sign-in card, no demonstration banner
"Попробовать на образце"              the sample drawing loaded
"Создать 3D-модель"                   201, ?order=7aceeabf-… in the address bar
  → DRAWING_ANALYSIS                  two questions, shown as a form on the page
"Подтвердить"  15 mm, 15 mm           the answers went back as parameters
  → build → verify                    READY, 6 artifacts, 100 s
files on the page                     STEP 22.1 KB · STL 50.3 KB · "Скачать выбранные"
downloaded                            22 648 and 51 484 bytes
```

## The part

```text
volume                14085.8407 mm³
bounding box          expected [60, 30, 8], measured [60, 30, 8]
through holes         expected 2, mesh-derived genus 2
mesh                  1028 triangles, 0 open edges, 0 inconsistent normals
topology              B-rep genus 2, mesh genus 2
engine                CAD-IR 1.15
```

```text
60 × 30 × 8 − 2 × π × 2.5² × 8 = 14400 − 314.1593 = 14085.8407
```

Exact to four decimal places against a number nothing in the pipeline computed, and the
same digits as every earlier run of this drawing — which is what a stack of contract
versions and six defect fixes are supposed to leave alone.

## What had to be fixed to get here

Everything in this file's siblings, and one more found on the way: with
`OPEN_LOCAL_ACCESS` the standing account was a **customer**, so `/operator` answered 403
and there was no second account to become — the same shape of dead end the sign-in form
had been. The standing account is now an **operator with a `user_id`**, a pair nothing
else in this service produces: the manual token is an operator and owns nothing, a
customer owns orders and cannot see the queue. On one machine both are the same person.

`/auth/me` reports the **principal's** role rather than the stored row's. An account
created before the role was decided still reads `customer` in the database, and
answering with that told the operator page it could not open a queue the API was already
serving it.

## What this run does not show

Quality. One drawing, one part type, and the questions it asked were answered by
somebody who knew the drawing. `POSTMVP-027` is the measurement that matters there: 91
of 100 delivered, 89 of 91 correct, 2 wrong with nothing said. This run is about the
pipeline being whole, not about the reading being right.

And `OPEN_LOCAL_ACCESS` is why it is this short. With it off the same run needs an
account, a CSRF token and an operator's approval — all of which work, and all of which
are what a service strangers can reach requires.
