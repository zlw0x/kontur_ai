# P3.3, draft: three of five already exist, and the rest is a selection

**Date:** 2026-08-03 · **Status:** probe done, contract change **not** proposed ·
**Probe:** `scripts/probe_build123d_draft.py`, run in the engine image.

P3.3 asks for five things: a neutral plane, a pull direction, **selected faces**, a
signed angle, and a self-intersection check. Before deciding whether the contract
needs an operation, the kernel was asked what it does — the rule this project
keeps, because an API member is cited or probed and never invented.

## What the kernel has

```text
candidates by name: ['Draft', 'DraftAngleError', 'draft', 'drafting',
                     'offset', 'offset_topods_face', 'to_align_offset']
extrude taper parameter: True
```

So build123d has **both** routes: a taper at creation and a `draft` that takes
faces of a solid already built. Neither has to be invented.

## What CAD-IR already reaches

A 40 × 40 square drawn in 10° over 20 mm:

| | |
|---|---|
| prismatoid rule | 40²… closed form **26689.1761 mm³** |
| `extrude(taper=10)` — what `taper_deg` compiles to | **26689.1761**, 6 faces, valid |

Exact. So a drafted boss is expressible in CAD-IR 1.10 today, with
`EXTRUDE_DRAFT_TOO_STEEP` already guarding the over-driven case (POSTMVP-021).
Three of P3.3's five — pull direction, signed angle, self-intersection check — are
done and measured.

## What is genuinely missing, and it is not an operation

`taper_deg` drafts an extrusion **as it is created**, so it draws in *every* wall
that extrusion makes. What it cannot express:

- drawing in **some** walls and not others;
- drafting a solid that was not made by an extrusion — a revolve, or a body a
  boolean produced;
- a neutral plane other than the sketch plane.

Every one of those is a question about **which faces**, and the probe shows the
faces are there to name: a straight 40 × 40 × 20 boss has four upright walls, and
"planar face whose normal is horizontal" finds exactly those four.

So P3.3 is not blocked by a missing operation. It is behind the same wall as
everything else that needs to point at geometry — ADR-029's dialect and claim
walls, which ADR-032 has already shown are lower than they looked for *named*
selections. A draft would want a selection like "the upright walls of body.main",
written here and exercised by the corpus rather than composed by a model.

## Why this is not being added now

Three milestones have now reached the same conclusion from three directions:

| | asked for | answer |
|---|---|---|
| POSTMVP-011 | hole families | composition — a through hole is a cut with `through_all` |
| POSTMVP-022 | rib | composition — a closed contour extruded both ways |
| **POSTMVP-024** | draft | `taper_deg` for the common case; the rest is a selection |

That is no longer a coincidence and is worth stating as a rule: **an operation
earns its place in CAD-IR only when it says something composition cannot.** Each
of these three would have added a type to validate, a capability key, a failure
mode, and a line in every prompt — in exchange for a second way to say what the
contract already says.

What a draft *would* buy is the partial case, and nothing in the drawing cycle can
ask for it yet: the reading stage has no word for "these walls are drawn in and
those are not", so an operation offering it would be one nothing can state. That
is ADR-029's claim wall, and it is the same reason `feature.shell` waited for
`ShapeClaim.wall`.

## What to do first, when this is picked up

1. **A word in the claim** — draft is invisible to every count the claim carries:
   a drawn-in boss and a straight one agree on the outline, the openings, the
   solid count and, unless the draft reaches it, the bounding box. Whatever the
   word is, `surface_face_count` is not it; a taper changes no face count.
2. **A named selection for upright walls**, in the ADR-032 style — written here,
   against the topology this engine builds, and exercised by the corpus.
3. Only then an operation, and only if 1 and 2 show the partial case is real.
