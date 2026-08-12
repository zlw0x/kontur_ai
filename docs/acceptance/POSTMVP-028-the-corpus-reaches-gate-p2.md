# POSTMVP-028: the corpus reaches Gate P2, and eighteen keys become `stable`

**Date:** 2026-08-12 · **Status:** accepted · **Engine:** build123d 0.11.1 /
OpenCascade 7.9.3.1.1, CAD-IR 1.15

> **Gate P2:** 100 golden-моделей, 30 типов деталей, 99% deterministic build success
> на synthetic corpus.

Three numbers. All three are now met, and each is asserted rather than described.

| Gate P2 asks | measured |
|---|---|
| 100 golden models | **100** positive cases (was 65) |
| 30 part types | **38** (was 23) |
| 99% deterministic build success | **100 of 100**, built twice |

Negative cases went along for the ride: **42**, unchanged, each naming the code it must
be refused with.

---

## What was added, and why these shapes

Thirty-five cases across **fifteen new part types**, in four families. None of them is a
new operation — every one is built out of what the engine already declares — and none is
here to raise a count. Each is a shape somebody orders, with arithmetic that comes off
its drawing:

| family | part types | the arithmetic |
|---|---|---|
| `_turned_parts` | stepped shaft, tapered bushing | two cylinders summed; the frustum rule `πh/3(R₁² + R₁R₂ + R₂²)` less the bore |
| `_ring_parts` | washer, spacer, nut blank, flange, gasket | `π(R² − r²)t`, and a hexagon by `½ n R² sin(2π/n)` |
| `_prismatic_parts` | hex bar, angle bracket, vee block, cross plate, counterbored cover, triangular gusset, slotted arm | area × thickness, with the area written out: two rectangles less their overlap, `2Lw − w²`, `½ab`, `πr² + 2rL` |
| `_folded_parts` | sheet-metal flange | the section times the path it travels |

The last one is deliberate: `docs/TASK-POSTMVP-closing-the-remaining-stages.md` claimed
that stage P6's folded geometry already builds, and a claim in a document is not evidence.
It is a corpus case now, at three sizes.

**Thirty-two of the thirty-five were right at the first build.** The three that were not
were one mistake repeated: a counterbore depending on the feature it followed rather than
on the feature that produced the body it cuts. The contract caught it —
`FEATURE_DEPENDENCY_MISSING` — which is the validator doing exactly what it is for.

### Part types are stated, not inferred

`Case.part_type` is a field. A plate at three sizes is three models and **one** part
type, so a count derived from ids or from families would be a count anybody could inflate
by resizing one shape. Families name their type in one line; a case that differs — a bent
tube among the straight sweeps — says its own.

---

## Determinism, and the second thing OpenCascade writes per export

`CAD_CORPUS_DETERMINISM=all` builds every case twice. The first full sweep came back
**99 of 100**, and the one exception is worth the paragraph it costs.

`two-separate-bodies` exports as a STEP *assembly*, and its two occurrences were named
`'1'` and `'2'` on the first build and `'3'` and `'4'` on the second. The STL was
byte-identical; the geometry had not moved. Measured further:

```text
process 1   NEXT_ASSEMBLY_USAGE_OCCURRENCE('1', ...)  ('2', ...)   step 20d8da7fc02f6c5d   stl 9d1a2619e1a4bac2
process 2   NEXT_ASSEMBLY_USAGE_OCCURRENCE('1', ...)  ('2', ...)   step 20d8da7fc02f6c5d   stl 9d1a2619e1a4bac2
```

**The counter is per process, not per document.** Two separate processes produce
byte-identical STEP and STL, occurrence labels included — which is the case that matters,
because a worker builds one job per process. Only a double build inside one process sees
it, exactly like the `FILE_NAME` timestamp this gate has normalised since POSTMVP-014.

So the label is normalised, and the exception is kept narrow by a test of its own: the
only lines that may differ are the timestamp and the occurrences, and inside an
occurrence only the label may move — its path (`=>[0:1:1:2]`) and both entity references
must not. A real change to the assembly still fails.

With that, the sweep is **100 of 100**.

---

## What that promotes, and the rule it follows

Meeting the gate is what makes any promotion possible. It is not what promotes a
particular key: a capability the corpus builds on one kind of part has been proved on one
shape, whatever the corpus's total. So the rule is stated and asserted:

> A capability is **`stable` when the corpus exercises it in at least three distinct part
> types.**

Three rather than one because this repository's own defects are the kind that only appear
when a *second* sort of part uses an operation — the multi-body boss POSTMVP-006 found,
and the two-group opening claim POSTMVP-027 found on flanges after nine acceptance runs
on parts with a single hole size.

**Eighteen keys become `stable`:**

```text
export.step (38 types)          export.stl (38)
validate.bounding_box (38)      validate.hole_count (38)
validate.manifold (38)          validate.topology (38)
sketch.plane.base (37)          solid.rectangular_prism (34)
feature.hole.simple_through (9) sketch.islands (7)
solid.contour_profile (6)       sketch.regular_polygon (4)
feature.boss.additive (3)       sketch.construction_geometry (3)
sketch.plane.datum_offset (3)   sketch.slot (3)
solid.revolve (3)               solid.sweep (3)
```

Everything else keeps the status it had. `feature.pattern.linear` (2 types) and
`validate.surface_face_count` (2) are the near misses, and the rule bites on them rather
than rounding up.

`test_a_capabilitys_status_is_the_corpus_behind_it` asserts it **in both directions**: a
key the corpus has outgrown fails, and a key claiming more than the corpus shows fails.
A declaration can no longer drift from the evidence in either direction, which is what
turns `stable` from an opinion into a measurement.

## What `stable` is worth

`experimental` means the API will not lease a job needing the key. `beta` and `stable`
are both leasable; the difference is what an operator is entitled to assume. Eighteen
keys now carry evidence at the roadmap's own bar, and the rest carry exactly the evidence
they have.

## Reproducing

```bash
python -m pytest packages/build123d-adapter/tests/test_corpus.py -q
CAD_CORPUS_DETERMINISM=all python -m pytest packages/build123d-adapter/tests/test_corpus.py -q -k "same_bytes or occurrence or timestamp"
```

Run on this machine with `.venv-cad`, where build123d is installed. The whole adapter
suite is **439 passed**; the root suite is 1013 passed, 15 skipped.
