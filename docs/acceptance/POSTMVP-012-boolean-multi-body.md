# POSTMVP-012: boolean and multi-body — acceptance

**Date:** 2026-07-31 · **Result:** PASS, declared `experimental`.

Design decisions in `docs/adr/ADR-028-*`. What follows is what was run.

## What was run

`tests/fixtures/cad-ir/boolean-bracket.v1_7.json`, through the real engine's real
command line. Four bodies created, two consumed, two delivered:

| feature | what it does |
|---|---|
| `feature.plate` | 80 × 40 × 10, the body every later feature works on |
| `feature.rib` | a second lump overlapping it, `new_body: true` |
| `feature.weld_rib` | **union** — the rib is fused in and stops being a body |
| `feature.punch` | a Ø16 tool body standing where the bore goes |
| `feature.bore` | **subtract** — the punch cuts the plate and is thrown away |
| `feature.stud` | a Ø16 × 24 lump on its own, never combined |

```text
status COMPLETED · verified true
2 solid bodies in one STEP · 1 036 triangles
```

### The volume is arithmetic from the drawing

| | mm³ |
|---|---|
| 80 × 40 × 10 — the plate | 32 000 |
| + 20 × 20 × 10 — the rib's half outside the plate | +4 000 |
| − π × 8² × 10 — the bore through it | −2 010.6193 |
| + π × 8² × 24 — the stud, kept as its own body | +4 825.4862 |
| **expected** | **38 814.8670** |
| **measured** | **38 814.8670** |

### Every check in the report

```text
step_readable · step_has_solid 2 solid bodies found · step_shape_valid
positive_volume 38 814.8670 mm3 · no_degenerate_solids
solid_body_count expected 2, measured 2
bounding_box expected [80, 138, 24], measured [80, 138, 24]
closed_manifold_mesh 0 open edges · consistent_normals 0
through_hole_count expected 1, mesh-derived genus 1
mesh_matches_solid the mesh sits 0.0025 mm inside and 0.0000 mm outside
```

`solid_body_count` measuring 2 is the first time that expectation has been able to say
anything: before 1.7 no document could make the number anything but 1.

## A defect this found before any fixture used it

`_genus` assumed Euler's formula for a **single** closed surface, `V − E + F = 2 − 2g`.
For a mesh of `c` components the right form is `2c − 2g`.

- two bodies with one through hole between them read as **genus 0** — a hole the
  document declared and the mesh could not find;
- two bodies with no holes at all would have read as **genus −1**: a negative number of
  through holes, on a part that is perfectly correct.

The component count is now computed by union-find over the mesh's vertices, with both
cases tested. Nothing about the geometry changed; the arithmetic had a wrong constant in
it, and it took a part that is more than one thing to expose it.

## Which body was touched

The tests that matter are the ones where two bodies exist and only one should have
changed:

- **a cut reaches only the body it names.** A slit cut through `body.main` runs straight
  across where the stud stands, and the stud comes out whole at exactly π × 8² × 24.
  Before 1.7 every cut removed material from the single running solid, so a document
  with `source_body` was believed rather than obeyed.
- **a blend reaches only the body its selector names.** A fillet on `body.stud`'s rims
  leaves the plate's volume unchanged to 1e-3.
- **a consumed body's name resolves to nothing.** A fillet naming `body.punch` after the
  subtraction fails with `FEATURE_RESULT_UNAVAILABLE` and the message lists what does
  exist. The alternative — a stale name falling through to whatever took its place — is
  how a fillet lands on the wrong lump of metal.
- **a kept tool stays a body.** `keep_tools: true` on the bore makes the part three
  solids instead of two.

## What it refuses

| | where | code |
|---|---|---|
| a body that starts on its own and names nothing | validator | `CAD_IR_INVALID` |
| a feature that both starts a body and adds to one | contract | |
| a body that is both the target and a tool | contract | |
| the same body twice as a tool | contract | |
| a boolean with no tools | contract | |
| a boolean that produces a result | contract | |
| a boolean whose target no feature produces | validator | `FEATURE_RESULT_UNAVAILABLE` |
| a boolean running before its tool exists | validator | `FEATURE_RESULT_UNAVAILABLE` / `FEATURE_ORDER_INVALID` |
| an intersection of bodies that do not touch | engine | `BOOLEAN_EMPTY` |
| a subtraction that removes everything | engine | `BOOLEAN_EMPTY` |
| a blend or boolean naming a body nothing built | engine | `FEATURE_RESULT_UNAVAILABLE`, listing what exists |

## What the claim had to learn

With booleans, **what the part is can no longer be read off feature types alone.** A
block extruded and then subtracted is a hole on the drawing; before this it counted as a
lump of material and its opening counted not at all, so a document that drilled its hole
with a boolean disagreed with an honest reading in two directions at once.

Now: a subtracted tool contributes an opening of its outline's kind and stops being a
lump, an intersected tool is neither, a kept tool is both, and a `union` changes nothing
because a welded rib is the same thing to a reader as a fused boss.

The bracket is the fixture that shows `solids` and `body_count` are different questions:
it declares **two bodies** and satisfies a claim of **three solids** — a plate, a rib and
a stud, which is what somebody counts looking at the drawing.

## Tests

| Suite | Count |
|---|---|
| `packages/build123d-adapter/tests/test_booleans.py` | 13 |
| `apps/api/tests/test_cad_ir_boolean.py` | 15 |
| `packages/build123d-adapter/tests/test_capabilities.py` | 30 |

Full runs: `616 passed, 1 skipped` (Python), `6 + 30 + 31 + 39` (.NET), schemas
generated-and-checked, OpenAPI compatibility valid.

## Not done, and why

**`experimental`.** A boolean is exactly the kind of operation where the kernel's answer
on tangential or coincident faces needs a body of evidence rather than one fixture, and
that is POSTMVP-013.

**No active-body statement.** P2.6 lists "active body" as a feature; here it is a rule
(the last body created or modified) rather than a field, because a document that states
which body is active has a second way to say `source_body` and the two could disagree.

**A body is not deleted on its own.** Bodies leave by being consumed by a boolean. A
`delete body` feature would be a way to build something and then hide it, which is a
document saying two things.
