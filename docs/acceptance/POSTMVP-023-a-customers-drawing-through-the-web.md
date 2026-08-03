# A customer's drawing, through the web, three times

**Date:** 2026-08-03 · **Machine:** the one Codex is signed in on ·
**Drawing:** a flanged, stepped, threaded bushing and a separate nut on one sheet,
with a handwritten note. Supplied by the operator; not generated here.

The first browser-path order since the engine changed, and the first ever on a
drawing nobody drew for the test. It was run three times as the service was fixed
under it, and each run found the next thing.

## Run A — a Ø88 part from a Ø44 drawing, every check green

`READY`. STEP, STL and the report delivered.

```text
valid: true
bounding_box   expected [88, 88, 44], measured [88, 88, 44]
through_hole_count  expected 0, genus 0
topology       3 faces, 3 edges, 2 vertices
```

Three faces is a solid cylinder. No bore, no flange, no step, no thread — and
twice the diameter the drawing states.

The reading was not at fault: 44, 11.5, 40, 27, 3.3, 30, 4.5 all reached
parameters correctly. The document declared `bushing_outer_radius: 44` — the
*diameter* value under a radius name — extruded a circle of that radius, and
restated 88 in its own expectation so the check agreed. **Seven of nine
parameters drove nothing.**

The claim did not catch it because the reading said `openings: []`, and the claim
compares compilation against reading, never reading against the drawing.

Four defects came out of this run and all four were fixed:

- `Scalar` had no arithmetic, so a diameter could not drive a radius
  (CAD-IR 1.11, ADR-034).
- The reading carried into round two was a **stub** — its only question had been
  "which part?", so `ready_for_cad` was false and the shape a placeholder. Round
  reuse now happens only when the reading settled the shape.
- `docker compose up -d` reused a stale API image, so the code on disk and the
  code in the container disagreed and it read as a regression. Third instance of
  that trap today.
- Migrations 0005 and 0006 had never run: the runner iterated a list written by
  hand. It reads the directory now.

## Run B — the arithmetic works, and the rule has a hole in it

With 1.11 and `drawing-mvp-7`:

```json
"radius": {"divide": {"parameter": "param.main_outer_diameter"}, "by": 2}
```

| | |
|---|---|
| bounding box | **[44, 44, 44]**, against run A's [88, 88, 44] |
| volume | π(22² − 9²) × 44 = **55706.72**, measured 55706.7209 |
| through_hole_count | 1, genus 1 — the bore run A lost entirely |

The reading improved with it: two questions instead of one, **both choices**, the
second asking whether the central opening goes through. Neither could have been
answered before the clarification contract learned to carry a choice — of the six
questions the nine earlier acceptance runs produced, four were unanswerable
through the web.

And the document passed while building almost nothing. Thirteen dimensions, two
used by the geometry, and the other ten referenced from **eight construction
circles no constraint mentioned**. Every parameter technically used; ten of them
driving nothing.

So `PARAMETER_DRIVES_NOTHING` stopped counting construction — precise rather than
blunt, because no fixture here has a parameter living only there, while refusing
unreferenced construction outright would refuse three that carry an axis line
nothing constrains.

## Run C — the loop converges, and stops at a real disagreement

The sharpened rule visibly changed what the model built: **five features** — base,
counterbore, datum plane, sleeve boss, shell — and ten parameters where run B
built a tube from two. The claim came back `solids: 2`, one through opening, and a
**named wall**.

Then nothing happened, twice, and each silence was its own defect.

**`PARAMETER_DRIVES_NOTHING` was not classified**, so the loop treated it as
unknown — not repairable by design — and the job neither healed nor failed.
Classifying it changed nothing, which was the more interesting half: the engine
reports a refused document as **`CAD_IR_INVALID`** and puts the rule that fired in
the *message*. The loop decides on the code; the agent reads the message. The
whole class "the trusted gate refused this document" was unrepairable, which is
backwards — the agent wrote it, and rewriting it is the entire fix.
`SHAPE_CLAIM_CONTRADICTED` was missing for the same reason.

With both classified the loop fired and converged:

| | |
|---|---|
| compilation | refused — dimensions parked in construction |
| repair 1 | refused — the same |
| repair 2 | refused — `FEATURE_DEPENDENCY_MISSING` |
| repair 3 | **accepted** — four features, six parameters, none idle |

The build then refused *that* with `SELECTOR_AMBIGUOUS`: "planar face along +Z"
found **two** faces on a stepped part — the flange and the sleeve end — where the
selection declares one. That is exactly the failure ADR-019 forbade a
zero-or-more cardinality to hide. It is repairable, and the loop had spent its
attempts reaching it.

So `MaxCompileRepairs` is three now, named rather than a literal `2` in the loop,
and separate from `MaxBuildRepairs`, which stays at two: a compile repair is one
model call, a build repair is a model call plus a container start and a kernel
run. Three because this order needed all three, and stopping at two is the most
expensive place to stop — everything paid for and nothing delivered.

## Where the drawing stands

Yesterday it produced a Ø88 cylinder with every check green. Today the cycle
reaches a flanged, stepped bushing with a shell and a named wall, and stops at a
genuine geometric disagreement about which face to open.

It is not yet the part. What stands between:

- **A selection that distinguishes two coplanar-normal faces.** The topmost is
  expressible; "the larger of the two" is not, and inventing a predicate for it
  is a decision rather than a fix.
- **Thread.** CAD-IR has no operation and POSTMVP-011 recorded that what is
  missing is a *callout*, not geometry.
- **Trigonometry.** Hole centres on a pitch circle are still literals; only the
  one on the axis can be derived.

None of those is arithmetic, and none of them is caught by making a rule stricter.
