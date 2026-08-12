# P5 to P9: what is left, measured rather than inherited

**Date:** 2026-08-12 · **Status:** decided. Two stages close on a measurement, two are
builds this names and scopes, and one is mostly already done.
**Probe:** `scripts/probe_build123d_remaining_stages.py`

Every stage closed so far turned out smaller than its description once somebody asked
the kernel instead of re-reading the table — ADR-032's dialect wall, `until_face`,
ADR-040's helix, ADR-041's P4.3, and P3.4's thread. This does the same for what is left,
and the pattern holds for two of the four: **P5 closes by being refused, P7 closes by
already being expressible.** P6 and P9 are real work, and this says what kind and how
much.

| stage | verdict |
|---|---|
| P5 surfaces | **refused as a stage**, with a measurement |
| P6 sheet metal | geometry **already builds**; the flat pattern is a genuine build |
| P7 assemblies | **needs no solver**; what is left is packaging |
| P8 drawing analysis | gated by its own rule, and by vision (ADR-029) |
| P9 production hardening | **mostly landed**; what remains is named below |
| Gate P1 / Gate P2 | a corpus size, which is a number rather than a feature |

---

## P5 — surfaces are refused, and the reason is every check this service has

```text
the solid          volume 19200.0000   solids 1   genus 0
one of its faces   area    2400.0000   volume     0.0000
that face as STL      2 triangles   4 open edges
```

A surface has an area and **no volume**, and its mesh is open by definition. Now list
what this service checks a delivered part with:

- `volume` — an expectation in every corpus case;
- `bounding_box` — measured on the mesh;
- `body_count` — solids;
- `closed_manifold_mesh` and `consistent_normals` — open edges must be zero;
- the genus cross-check of POSTMVP-020 — Euler over a closed shell, twice;
- the shape claim (ADR-025) — outline, openings, solids, wall.

**Every one of them is a question about a solid.** Admitting surfaces means delivering a
part that none of them can check, which is the exact opposite of what ADR-018 through
ADR-025 were built for. That is not a limitation of the kernel: `thicken` works and is
exact —

```text
thicken(face, 3)   volume 7200.0000   expected 7200.0000   0 open edges   1 solid
```

— it is a limitation of what a document can *say*. CAD-IR has no way to state a surface
at all, so even the one operation that ends in a solid needs the whole vocabulary the
rest of P5 is refused for: trim, extend, offset, patch, sew, NURBS, intersection curves,
replace-face. That vocabulary is a second contract the size of the first, and everything
it produced would arrive unchecked.

The roadmap's own constraints already point the same way — Class-A out of scope, freeform
to manual review, "the agent must produce explicit sections and guides". The honest
version of that is: **the operations that end in a solid already exist** (loft between
sections, sweep along a path, revolve), and they are how a curved part gets built here.

**What would reopen it**: a drawing whose part cannot be expressed as a solid built from
solids. None has appeared in 100 labelled orders (POSTMVP-027) or in any acceptance run.

---

## P6 — the folded part already builds; the flat pattern is the work

A 2 mm sheet, 60 mm wide, folded 90° at an inside radius of 3 mm, built through the
engine as a rectangular section carried along a run–arc–run path:

```text
volume 9393.9822   section x length 9393.9822   diff 5.457e-12
276 triangles   0 open edges   0 flipped   1 solid   genus 0
```

**Uniform thickness is not a check — it is a property of the construction**, because the
swept section never changes. That is one of the four validations P6 lists, obtained for
free. Collisions are `SOLID_PASSES_THROUGH_ITSELF` and the bend-clearance rule, both of
which already run. A minimum-bend-radius warning is arithmetic on two stated numbers.

One caution worth keeping, because it is the same finding as ADR-040's amendment: the
identical sweep written **straight against build123d** — `Plane(origin, z_dir=path % 0)`
— comes back with **140 open edges** and two faces the mesher skips. A 60 × 2 section is
as sensitive to the in-plane frame as a thread's V is. The engine is safe from it only
because CAD-IR makes the document *state* the profile's plane rather than inherit one.

### What is genuinely missing, and it is not geometry

```text
K = 0.33   neutral radius 3.660   flat length 75.7491   folded volume 9393.9822
K = 0.42   neutral radius 3.840   flat length 76.0319   folded volume 9393.9822
K = 0.50   neutral radius 4.000   flat length 76.2832   folded volume 9393.9822
```

**Three blanks, one solid.** A K-factor changes nothing this service can measure on the
delivered part — which puts it exactly where a thread designation is (P3.4) and where
`hand` is (ADR-040): a manufacturing number that only a person can catch being wrong.

So P6 is a real build and it divides cleanly:

1. **Nothing** for the folded geometry.
2. **A manufacturing vocabulary** — thickness, bend radius, K-factor, relief type — which
   is the same shape of contract change as `thread.designation`: read off the drawing,
   carried by the claim, shown to the operator, never checkable by measuring the solid.
3. **A flat pattern and a DXF artifact**, which is the genuinely new part: an unfold is
   not a solid operation, and DXF is a third artifact beside STEP and STL, with its own
   digest, its own place in the manifest and its own line in the delivery.

Item 3 is the one that costs. It is worth doing **after** item 2, because a flat pattern
computed from a K-factor nobody stated is a number nobody chose.

---

## P7 — an assembly needs no solver, and ADR-022 already said so

```text
two 20 mm cubes, centres 26 mm apart   intersection volume    0.0000
the same cubes, centres 16 mm apart    intersection volume 1600.0000
```

`1600 = 20 × 20 × 4`, exactly the overlap. **An interference is an intersection volume**,
which is arithmetic on bodies the document already places (`new_body`, `source_body` and
`feature.boolean`, all since CAD-IR 1.7).

That settles the one design question P7 has. A *mate* could be either a constraint the
kernel solves for, or an assertion about placements the document states — and ADR-022
decided this class of question three years of milestones ago: **a constraint is an
assertion about the coordinates the document states, never an instruction that produces
them.** So an assembly here is bodies placed by the document plus assertions that check
the placement, and "coincident / concentric / distance / angle" are expectations rather
than a solver.

What is actually left of P7 is therefore **packaging, not geometry**:

- per-part STEP and STL — each body already exports on its own (measured: 0 open edges,
  1 solid each);
- an assembly STEP — several bodies already export as a compound (ADR-028);
- a ZIP — a delivery format;
- an `interference` expectation — a small contract addition of the kind `body_count` is;
- exploded preview — a viewer feature with no geometry behind it.

And one product rule the roadmap already states and this does not change: an ambiguous
mate becomes a question to the customer or manual review.

---

## P8 — gated by its own rule, and by vision

P8 opens with the rule that decides it: *extend the vision pipeline only after the
adapter supports the corresponding geometry.* Most of what it lists — threads, chamfers,
fits, roughness, GD&T, section views, hole tables — is now **behind adapter support that
exists**, and behind ADR-029's vision wall instead, which no code in this repository
settles. POSTMVP-016 and POSTMVP-019's runs measured that wall directly: the cycle
reaches ten of the engine's capabilities, and the reason the rest wait is what an agent
can read off a scan.

Two items are concrete and neither is vision:

- **WEBP** through the sanitizer. The approved input policy names it; the sanitizer does
  not accept it yet. It is a format check and a decoder path, in the process that already
  exists.
- **The PDF contour** — a separate isolated rasterizer, named and not built
  (`docs/SECURE-INPUT-ADDENDUM.md` says so).

The evidence graph and the web editor are product work with no geometry question in them.

---

## P9 — mostly landed, and the rest is named

Much of P9 arrived under other names during the production audit:

| item | state |
|---|---|
| concurrency = 1 | the worker's default |
| Windows Job Object | **obsolete** — CAD runs in a Linux container (ADR-023) |
| process watchdog, forced cleanup | the launcher owns the child; stdin is closed at start |
| orphan cleanup, lost leases | the reaper (P0-3), `LEASE_LOST`, `JobStatus.PAUSED` |
| disk quota, resumable upload | the quarantine counts and stops at the limit (P0-2) |
| budget limits | `CODEX_BUDGET_EXHAUSTED`, `max_attempts`, the order quotas of P1-7 |
| reboot policy | not built, and it is an operator runbook rather than code |

**The quality score is the one piece worth building next**, and it is small because every
number in it already exists somewhere in the pipeline: repair count, assumption count,
the verification report, the claim's verdict, whether a clarification round happened.
Assembling them is code, not research — and it has a customer, because it is what lets
the moderation queue be sorted rather than scanned. `automatic_acceptance` stays off
either way (P0-5): 2 wrong parts in 100 with nothing said is what a person is for.

---

## Gate P1 and Gate P2 are a number, not a feature

> **Gate P1:** at least 50 fixtures, each run on 20 parameter sets.
> **Gate P2:** 100 golden models, 30 part types, 99% deterministic build success.

The corpus is **65 positive cases and 42 negative** as of CAD-IR 1.15, generated by
substituting numbers into document shapes with every expected number closed-form from the
drawing. It is not 100 models across 30 part types, and that is why nothing in
`capabilities.py` is declared `stable`.

Closing these two is a corpus job rather than an engine one: more shapes, more parameter
sets, and the arithmetic for each stated in closed form. It is the cheapest remaining
item on this page and the one that changes the most, because it is what promotes a
capability from `beta` to `stable` and therefore what an operator can lease.

---

## What this leaves

Nothing on this page is blocked on a question about geometry any more. What is left is
four builds, in the order their evidence supports:

1. **`thread.designation` and the sheet-metal manufacturing vocabulary** — one contract
   version, because they are the same kind of thing: a note the solid cannot carry.
2. **The quality score** — assembling numbers the pipeline already produces.
3. **The corpus to Gate P2's bar** — what makes anything `stable`.
4. **The flat pattern and a DXF artifact** — the one genuinely new computation left in
   the CAD line, and it wants item 1 first.

And two that are not builds at all: P5, refused above with a measurement, and the vision
half of P8, which is the wall ADR-029 named and no code here settles.
