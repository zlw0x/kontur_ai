# Gate P4: what it asks, what is there, and what is checkable without a run

**Date:** 2026-08-04 · **Status:** analysis, and both halves it named are now closed.
Every number was measured on CAD-IR 1.10 in an environment with the engine but no
container and no Codex. The two "reachable today" items at the bottom were done in the
commit after this one; what remains is P4.3 and everything that needs it.

The roadmap states the gate in one line:

> **Gate P4:** loft/sweep имеют topology oracle; неоднозначное сопоставление сечений
> отклоняется.

Two clauses. Each was **half done**, and in neither case was the missing half the one the
phrasing suggests. Both halves are closed now; the sections below say what was there,
what was not, and what closed it.

---

## Clause 2 — ambiguous section correspondence is rejected

### What is closed

ADR-031 requires every section of a loft to be **the same kind of contour with the same
number of vertices**. A circle into a square is refused by the contract; so is a hexagon
into an octagon. That closes the ambiguity which produces a *fold* — the kernel pairing a
vertex with the middle of an edge — and it closes it by reading the document rather than
by inspecting a result.

### What is open, and it is reachable

Two sections of the same kind can still be rotated relative to each other, and when the
rotation is a **symmetry of the contour** the correspondence is genuinely undecided. The
kernel picks one. Measured on a 40 × 40 square lofted 30 mm to another 40 × 40 square:

| stated rotation | volume | topology | what was built |
|---|---|---|---|
| 0° | 48 000.0000 | 6/12/8 | a prism |
| 15° | 47 454.8132 | 6/12/8 | a twist |
| 45° | 43 313.7085 | 6/12/8 | a twist |
| **90°** | **48 000.0000** | 6/12/8 | **a prism** |

At 90° the document states a quarter turn and gets **no turn at all** — the same volume,
to the digit, as the un-rotated case. Nothing is wrong with the kernel: a square turned
90° is the same set of points, so both readings are consistent with the sections as
stated. The document is ambiguous, which is precisely what the gate says must be refused.

It reports itself valid, the topology is unremarkable, and the volume is exactly that of a
correct part — the same failure shape as the three findings of POSTMVP-017/018/021.

### What closed it

**The contract, not the engine.** A section is a sketch with an explicit contour, so the
rotation between two of them is arithmetic on numbers the document already states — the
same class of check as `_require_corresponding`, and it landed beside it as
`_require_unambiguous_rotation` in `cad_ir/loft.py`.

> The rotation between two sections, normalised to `[0, 360)`, must be **less than the
> contour's own symmetry**.

One condition rather than a modulo test, and the difference matters: it catches 135° on a
square as well as 90°, because a square at 135° has the vertex set of one at 45°. In every
refused case the document states one angle and the sections record another, so the kernel
is left choosing.

The symmetry is the contour's own — a square repeats every 90°, an oblong every 180°, a
hexagon every 60°. That is why it is not a constant: an oblong turned 90° is a genuinely
different pair of sections and a single threshold would have refused a correct document. A
circle is exempt, having no vertices to pair. A rotation stated as a parameter is left
alone, because the check reads numbers rather than guessing at names, and so is a rectangle
whose sides are parameters — there the guaranteed symmetry of *every* rectangle is used,
which refuses the half turn and lets a quarter through rather than refusing a document that
may be correct.

A drawing that genuinely means a quarter-turn twist has to say so as a twist, which is
P4.1's `controlled twist` and a different input from a rotated section.

Cost, as built: one function, one corpus negative, seven contract tests, no engine change
and no version bump — it narrows what is accepted rather than widening it, and none of the
eight sweep/loft corpus cases rotates a section.

---

## Clause 1 — loft and sweep have a topology oracle

### What is closed

POSTMVP-020 added the check that needs nothing from the document:
`topology_agrees_with_mesh`. The genus of the delivered solid is computed twice, off two
files written by two different exporters — Euler–Poincaré over the B-rep in the STEP,
Euler over the triangles in the STL — and they must agree. It runs on **every** build.

It catches the self-intersecting sweep, which is the specimen failure of these two
operations: the STEP reports a tidy genus-0 solid of four faces and `is_valid` true, the
STL reports genus −45 with 69 open edges, and only the disagreement says the solid is not
one.

### What was open, and it was exactly the operations the clause names

The corpus stated `(faces, edges, vertices)` for **16 of 59** cases. Which sixteen:

```
plates (3)   islands/cuts (6)   blind-hole   extrude modes (4)   shell-box (2)
```

None of them is a sweep or a loft. The eight cases that state no topology at all are:

```
sweep-straight  sweep-elbow  sweep-rectangular-section  sweep-cut-groove
loft-truncated-cone  loft-truncated-pyramid  loft-three-sections-ruled
loft-cut-tapered-pocket
```

So the clause reads "loft and sweep have a topology oracle" and those were the two
operations for which the *stated* half of the oracle was absent. The genus cross-check
covered them; the structure did not. Six of the eight state one now — **22 of 59** — and
the two that do not are named at the end of this section.

### The arithmetic, derived and verified

This is the part worth having, because it turns "state the topology" from transcribing a
run into deriving a number from the drawing.

**A swept solid of a circular section over `n` path segments:**

```
faces = 2 + n        edges = 2n + 1        vertices = n + 1
```

Two caps, one lateral face per path segment; one circle at each section boundary plus one
seam per lateral face; one vertex per circle. Verified at three points:

| n | predicted | measured |
|---|---|---|
| 1 (a cylinder) | 3 / 3 / 2 | 3 / 3 / 2 |
| 2 (an elbow) | 4 / 5 / 3 | 4 / 5 / 3 |
| 3 (elbow and run) | 5 / 7 / 4 | 5 / 7 / 4 |

**A swept solid of a rectangular section over `n` segments of a planar path:**

```
faces = 4 + 2n       edges = 4(n + 1) + (2n + 2)      vertices = 4(n + 1)
```

Not the naive `2 + 4n` faces, and the difference is a finding rather than an off-by-one.
The two faces whose normals are **perpendicular to the bend plane** stay planar *and
coplanar* across every segment — a planar path never tilts them — so `clean()` merges each
into one face spanning the whole sweep. Only the two faces that actually bend are split
per segment. Measured: n = 2 gives 8/18/12 where the naive form predicts 10/20/12; n = 1
degenerates to a box, 6/12/8, which both forms agree on.

**A lofted solid of `m` sections of a `k`-vertex contour:**

```
faces = 2 + k(m − 1)     edges = km + k(m − 1)     vertices = km
```

A circle counts as `k = 1` — its seam is the one longitudinal edge. Verified at three
points:

| contour | m | predicted | measured |
|---|---|---|---|
| circle (k=1) | 2 | 3 / 3 / 2 | 3 / 3 / 2 |
| square (k=4) | 2 | 6 / 12 / 8 | 6 / 12 / 8 |
| square (k=4) | 3 | 10 / 20 / 12 | 10 / 20 / 12 |
| hexagon (k=6) | 2 | 8 / 18 / 12 | 8 / 18 / 12 |

**The two cut cases are different and should be honest about it.** `sweep-cut-groove`
measures 8/18/12 and `loft-cut-tapered-pocket` 11/24/16, but those counts describe a plate
*minus* a tool: they are a property of how the tool meets the faces it breaks through, not
of the operation. Stating them would be pinning a measurement, which is what the corpus's
own rules forbid — "a figure whose source cannot be named is a figure somebody typed to
make a test pass". Either leave them unstated, or state them with the intersection
reasoning written out. The former is honest and cheap; the latter is a small essay per
case.

### Cost, as built

Six of the eight cases now state a topology, and each states it as the **formula** rather
than the number: `round_topology(n)`, `square_topology(n)` and `topology_of(k, m)` sit
beside the volume arithmetic in the same docstrings. The corpus gate needed no change —
`test_a_case_that_states_its_topology_is_made_of_what_the_drawing_says` picks up any case
that states one, and the corpus went from 122 to 128 assertions.

The two cut cases stay unstated, for the reason above.

---

## The rest of stage P4, and which wall each item is behind

| item | status | wall |
|---|---|---|
| P4.1 2D path | **in** (1.9) | — |
| P4.1 join / cut / new body | **in** (1.9) | — |
| P4.1 3D path | out | CAD-IR has no way to state a point in space; needs P4.3 first |
| P4.1 orientation modes, guide curve, controlled twist | out | each is an input the *document* would have to state; none is something the reading stage can produce |
| P4.1 pipe/duct templates | out | composition, like the hole families of POSTMVP-011 — a second way to say what 1.9 already says |
| P4.2 two or more profiles | **in** (1.9, up to 16) | — |
| P4.2 open/closed profiles | closed only | an open profile lofts to a surface, not a solid; the engine delivers solids |
| P4.2 vertex correspondence | **the open half of clause 2** | contract, reachable now |
| P4.2 guide curves | out | needs P4.3 |
| P4.2 topology validation | **the open half of clause 1** | corpus, reachable now |
| P4.3 3D curves | out | a new coordinate vocabulary in CAD-IR; the largest single piece of P4 |
| P4.4 templates (spring, auger, helical groove, real thread) | out | all four need a helix, so all four need P4.3 |

The shape of stage P4 is therefore: **two small pieces reachable today, then a wall called
P4.3.** Nothing in P4.4 is approachable before a 3D curve exists, and a real modelled
thread — the thing the roadmap wants most from P4.4 — is a helical sweep.

---

## What is actionable in an environment with no container and no Codex

In order of value:

1. ~~**The symmetry rule for loft sections.**~~ Done.
2. ~~**Topology on the six derivable sweep/loft cases.**~~ Done.
3. ~~**The version out of test sources.**~~ Done. Not part of P4, but it is what let a
   fixture rename hide inside skipped container tests. A version bump is now a rename of
   files and nothing else: `tests/cad_ir_fixtures.py` derives the filename from
   `CAD_IR_VERSION`, `CadAi.CadEngine.CadIr` does the same for .NET, and
   `apps/api/tests/test_fixture_versions.py` refuses a version literal in any source
   file — in a test that always runs rather than one that might be skipped.

Not actionable here: anything in P4.3 or P4.4 (design work first, and a large contract
addition), and anything that needs the image built.

## What was deferred, and what was not

CAD-IR 1.11 is not on `origin/master` — `steps`, POSTMVP-022 through 024 and the container
fix are still local on the machine the runs were done on. The first deferral of both items
above was wrong about why: a version bump does **not** touch `golden_corpus.py` (it derives
`CAD_IR_VERSION`) and does not touch `cad_ir/loft.py` at all, so both are additions that
merge rather than collide, and both are done.

Item 3 does collide — it edits the nineteen files a bump renames, which is exactly the
set 1.11 has rewritten locally — and it was done anyway, deliberately, because the merge
resolves in one direction: this side has **no** version literal at all, so every conflict
is "take the version out" plus whatever else that file changed. And after it, no future
bump touches a test source again.
