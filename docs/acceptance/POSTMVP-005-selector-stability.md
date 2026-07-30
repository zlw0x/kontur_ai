# POSTMVP-005: selector stability acceptance

**Date:** 2026-07-30 · **Result:** PASS, after two defects the real run found
and the synthetic tests could not have.

No new geometry. The milestone delivers the layer every later operation needs
to say *which* face it applies to, plus the run that proves it survives the
things that break an index.

## What was run

```bash
dotnet run --project apps/local-worker -- resolve-selectors .local/selector-stability
```

Live KOMPAS v22 on the trusted Windows machine, no Docker, no Codex. Six
selectors resolved in each of four phases:

| Phase | Model | Process |
|---|---|---|
| `initial` | 40 × 30 × 8 plate, two Ø5 holes at x = ±13 | first |
| `widened` | base sketch edited to 60 wide, rebuilt | first |
| `reopened` | same M3D opened from disk | second |
| `third_hole` | a third Ø5 hole drilled at x = 0 | second |

The plate is widened by editing the base sketch in place rather than by
rebuilding a wider one from scratch: face numbering is stable when the history
is identical, so building afresh would test nothing. The reopen uses a second
KOMPAS process so that no COM handle, index or kernel numbering from the first
can possibly still be in scope.

## The selector set

| Selector | Declares | Purpose |
|---|---|---|
| `top_face` | exactly one | planar, normal +Z, furthest along Z — the face a fillet would take |
| `hole_walls` | exactly 2 | cylindrical, radius 2.5 ± 0.01 |
| `hole_walls_by_area` | exactly 2 | cylindrical, lateral area 125.66 ± 0.1 mm² |
| `side_face_ambiguous` | exactly one | planar, normal parallel to X — **must fail** |
| `side_face_max_x` | exactly one | the same, plus furthest along X |
| `top_hole_rims` | exactly 2 | circular edges, radius 2.5, furthest along Z |

`side_face_ambiguous` is a requirement, not a concession. Two symmetric side
faces match it, and a resolver that quietly returned the first one is exactly
the defect this milestone exists to remove.

## Results

Every selector behaved as declared in all four phases.

```text
initial     faces 8  edges 16   read 145 ms  resolve 16 ms
widened     faces 8  edges 16   read  84 ms  resolve  0 ms
reopened    faces 8  edges 16   read 111 ms  resolve  0 ms
third_hole  faces 9  edges 18   read 101 ms  resolve  0 ms
```

| Check | Result |
|---|---|
| `phases_recorded` | initial, widened, reopened, third_hole |
| `selectors_as_declared[·]` | 6 of 6 in every phase |
| `top_face_is_the_same_face` | planar, +Z, z_max 8.000 in every phase |
| `top_face_index_observed` | index moved 0 → 0 → 0 → 1 |
| `rebuild_actually_changed_the_model` | top face width 40.000 → 60.000 mm |

### The headline

Drilling the third hole moved the top face from collection index **0 to 1** and
the +X side face from **3 to 6**. Both selectors still found what they meant. A
document that had written `face_index: 0` against the two-hole model would have
applied its operation to a different face, validated, built, and reported
success.

### Ambiguity, and its repair

`side_face_ambiguous` returned `SELECTOR_AMBIGUOUS` with two candidates in
every phase, with a trace showing where they came from:

```text
surface_type=planar        8 -> 6
normal parallel to x       6 -> 2
```

`side_face_max_x` is the same selector with one position predicate added — the
repair that trace suggests — and resolved to exactly one face every time.

### A declared count catching a change

In `third_hole`, all three `exactly_n = 2` selectors returned
`SELECTOR_CARDINALITY_MISMATCH` with three matches rather than silently
operating on all three. That is the contract working: a document that says two
mounting holes and finds three has a real disagreement in it.

## Defects found by the real run

**The unit bit vector is 1, not 0.** `ksEdgeDefinition.GetLength` and
`ksFaceDefinition.GetArea` take a unit selector; the reader passed 0, which is
centimetres. Nothing failed loudly — every length came back a plausible number
ten times too small — and the first run had all four rim selectors miss on a
radius filter. Measured on a Ø5 rim: bit vectors 0 to 3 give 1.570796,
15.707963, 0.15708 and 0.015708, and 2π · 2.5 is 15.707963.

`hole_walls_by_area` was added to the catalogue afterwards so the area unit is
pinned by a selector that fails when it moves. The synthetic tests could not
have caught this: they measure nothing.

**One API5 application object per session, not per read.** Creating it per
topology read starts a *second* KOMPAS process — the first is busy serving
API7 — and the second has no document open, so `ActiveDocument3D` answers with
nothing. Symptom: the first phase read fine and the second could not find the
model.

## Ledger

Selector resolution is its own stage. The run emitted one `CAD_SESSION` and one
`CAD_OPERATION` per phase, all at `SELECTOR_RESOLUTION`:

```text
selector:stability:run        CAD_SESSION     10091 ms
selector:resolve:initial      CAD_OPERATION     143 ms  faces 8  edges 16
selector:resolve:widened      CAD_OPERATION      85 ms  faces 8  edges 16
selector:resolve:reopened     CAD_OPERATION     117 ms  faces 8  edges 16
selector:resolve:third_hole   CAD_OPERATION     101 ms  faces 9  edges 18
```

Reading the topology dominates; filtering it is under 16 ms. Nothing in the
build pipeline resolves a selector yet, so the events are emitted by the
diagnostic rather than by a job — wiring the measurement into the pipeline now
would add code no order reaches. The stage exists so that the first operation
to use a selector reports its cost separately from the feature it serves.

## What this does not prove

The plate has nine faces. Resolution time on a model with several hundred is
unmeasured, and the resolver is a linear scan per predicate.

No operation consumes a selector yet. The contract, the resolver and the
measurement are in place; the first consumer is a later milestone.

## Reproducing

```bash
dotnet test CadAi.sln --nologo
dotnet run --project apps/local-worker -- resolve-selectors .local/selector-stability
```

The second needs KOMPAS v22 installed and exits non-zero if any check fails.
It leaves `selector-stability.m3d` in the output directory; `.local/` is
ignored by git.
