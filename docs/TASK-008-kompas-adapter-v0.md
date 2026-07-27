# TASK-008: trusted KompasAdapter v0

## Scope

The deterministic MVP handler builds a rectangular prism and optional
contained circular through-holes from validated CAD-IR:

```text
center_rectangle on XY -> base extrude in +Z
  -> zero or more circle cuts -> model.m3d + model.step + model.stl
```

The accepted surface is deliberately narrow. The first enabled feature must
be one `extrude_add` with one `center_rectangle`. It may be followed by up to
19 `extrude_cut` features, each containing one circle fully inside the base
rectangle. Other feature sets, planes and directions return typed
`UNSUPPORTED_*` errors before COM activation.

## Safety properties

- no generated code or scripts are executed;
- CAD dimensions are finite, positive where required and bounded;
- output uses fixed names `model.m3d`, `model.step`, and `model.stl`;
- every KOMPAS call runs on a dedicated STA thread;
- pre-existing KOMPAS processes are never terminated;
- result metadata includes size and SHA-256;
- fake CAD is available for CI and does not require KOMPAS.

## Real-machine evidence

On 2026-07-27, `run-job` consumed
`tests/fixtures/cad-ir/plate-with-hole.json` and returned:

```json
{"status":"COMPLETED","adapter":"kompas-api7","artifacts":3}
```

The adapter created a 61,025-byte M3D, an 11,819-byte STEP, and a
14,554-byte STL. Independent mesh validation measured one closed manifold
body, bounding box `[40, 20, 10]`, 84 non-degenerate triangles, and genus 1
for the one requested through-hole. No orphan KOMPAS process remained.

## Automated evidence

`CadAi.KompasAdapter.Tests` covers valid base/cut plan extraction, hole
containment, unresolved parameters, unsupported features and checksummed fake
artifacts. `CadAi.GeometryValidation.Tests` covers valid and malformed STL
paths. Real KOMPAS is intentionally excluded from CI.
