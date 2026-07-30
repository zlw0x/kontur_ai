# TASK-POSTMVP-006: sketch primitives

## Why this milestone exists

CAD-IR 1.1 can express exactly two sketch shapes, a centred rectangle and a
circle, and only on the XY plane. Every part the service can build is therefore
a rectangular plate with round holes. That was the right bounded MVP; it is not
a service.

This milestone makes the sketch a real object: contours of lines and arcs given
by explicit coordinates, an outer profile with islands inside it, and a plane
that can be a base plane, an auxiliary plane, or a face named by a semantic
selector.

## Scope

**In:** point, line segment, circle, arc, rectangle, slot, regular polygon,
construction geometry, one outer contour, several inner contours, sketching on
a base plane, on an auxiliary plane, and on a planar face through a
POSTMVP-005 selector.

**Out, deferred to later milestones:** dimensional constraints, geometric
constraints, automatic sketch parameterisation, splines, ellipses, text,
projected geometry, DXF import, arbitrary formulas, open profiles for sweep,
islands nested more than one level deep, and automatic repair of
self-intersections. Constraints are POSTMVP-007.

Everything is built from explicit coordinates. There is no solver in this
milestone and nothing infers a dimension.

## KOMPAS API evidence

`scripts/probe_kompas_sketch.py` prints every member with its DispId. Four
things could only be learned from a live run against KOMPAS v22, and each one
changed the design.

**An arc is built from centre, radius and two angles.** `IArc` also exposes
X1/Y1/X2/Y2, and setting those instead leaves `Update()` returning false with
the radius at zero.

**`IArc.Direction` 0 sweeps anticlockwise from Angle1 to Angle2; 1 and −1 both
sweep clockwise.** This one cost a run. The first probe drew a slot with
`Direction=1`, it built, and that was taken as confirmation — but a slot with
both end caps reversed is still a closed contour, so the probe could not
discriminate. The acceptance part could: with `Direction=1` its Ø30 end caps
bulged inward and an 80 mm profile came out 61 mm. Settled by extruding a
half-disc bounded by its chord and reading which side of the chord the material
landed on.

**The offset plane is `Planes3D.Add(14)`.** 15 is by angle, 16 through three
points. The type library exports no named constant for any of them; found by
adding each type from 1 to 59 and asking which result casts to
`IPlane3DByOffset`. `Planes3D` lives on `IAuxiliaryGeomContainer` (DispId
14028), not on `IModelContainer`.

**A face for a sketch comes from a point.** API7 has no face collection —
POSTMVP-005 established that, which is why topology is measured through API5 —
so a face resolved by a selector cannot simply be looked up. But
`IPart7.FindObjectsByPoint(x, y, z, firstLevel)` returns an `object[]`, and on
the centre of a plate's top face one of the three entries casts to `IFace` with
`IsPlanar` true and `GetArea(1)` equal to 1200 mm² for a 40 × 30 face.

**A sketch on such a face extrudes normally.** A Ø12 boss on the selected top
face built and rebuilt.

**A base extrusion always makes a new body**, whatever the new material
touches. A second `Add(24)` over the first leaves two bodies at every
`OperationResult` value; only extrusion type 25 leaves one. So the first solid
extrusion is the base and every later one is a boss.

**Style is what separates profile geometry from geometry that is merely
present.** With a stray line at style 1 inside a closed rectangle the extrusion
fails; at every style from 2 to 8 it succeeds. Construction geometry is drawn at
style 7, `Вспомогательная`.

`IModelObject.Update` is DispId 503 and `IDrawingObject.Update` is 3004 — model
features and sketch entities are different objects and answer on different
identifiers.

## The face bridge, and why it verifies rather than trusts

A selector resolves against measured API5 descriptors and produces a face's
geometry, not a handle. Turning that into an API7 object means asking KOMPAS
what is at a point on the face — and a point derived from a face is only
*probably* on it: `ksSurface.GetPoint` at mid-parameter is on a trimmed planar
face for the shapes this build makes, but not for every shape it will ever
make.

So the bridge checks its answer. The face API7 returns must be planar, and its
area must match the area the selector measured. When it does not, the build
stops with a typed error rather than sketching on whatever was nearest. A
sketch placed on the wrong face produces a part that looks plausible, which is
the failure mode this whole line of work exists to remove.

## Design

### The illegal state is unrepresentable

A sketch has one `outer` contour and a list of `inner` contours. Islands nested
two levels deep are not rejected by a validator — they cannot be written down.

### Contours, and what expands into one

A contour is a closed region boundary. `path` is the general form, an ordered
list of line and arc segments. `circle`, `rectangle`, `slot` and
`regular_polygon` are whole contours in their own right and expand into a path
deterministically.

Expansion happens once, in the trusted parser, before anything reaches COM. The
adapter draws lines, arcs and circles and knows nothing about slots.

### Construction geometry is separate

Points, and lines, arcs and circles marked as construction, live in their own
list. They are never part of a profile, so no validation rule has to ask
whether a stray line was meant to close a contour. They exist because
POSTMVP-007 will need something to constrain against.

### Where geometric validation lives

In the adapter, in C#, before any COM object exists. The AI path runs Codex on
the worker and hands its CAD-IR straight to the adapter — the API's Python
validator never sees it — so a check that only existed in Python would not
protect the machine that runs KOMPAS.

Python keeps the canonical contract: the document shape, the feature graph and
the version. C# owns closure, degeneracy, self-intersection and nesting. This
is the same division already in place, and the reason is the same: the schema
says what the version can express, the adapter says what it can build.

Arcs are tessellated for the intersection and containment checks. That is an
approximation, deliberately: an exact arc–arc intersection test is a
disproportionate amount of numerically delicate code for a tolerance nothing
else in the pipeline is tighter than.

### Version

CAD-IR 1.2. The additions are additive, but a 1.1 document that uses a 1.2
entity is rejected rather than accepted: a document that lies about its version
is the beginning of a compatibility problem, not the end of one.

## Done

1. **CAD-IR 1.2 contracts** — `packages/cad-ir/cad_ir/sketch.py`, plus a `base.py`
   so selectors, sketches and the document form a layer rather than a cycle.
   1.1 became migratable, so one shape reaches the adapter.
2. **Expansion and geometric validation** — `SketchGeometry.cs` and
   `SketchValidator.cs`, with tests over every refusal: an unclosed contour, a
   gap below tolerance that is *not* healed, a zero-length segment, an arc whose
   endpoints disagree about its radius, a duplicate segment, a bow tie, an
   island outside the profile, an island straddling its edge, two overlapping
   islands, and two nested ones.
3. **Adapter** — `KompasSketchBuilder.cs` draws lines, arcs and circles;
   `KompasFaceBridge.cs` turns a resolved selector into an API7 face and
   verifies it by area; `KompasApi5Session.cs` holds one API5 object per build.
4. **Output profile** — generated by `scripts/generate_output_profile.py` so the
   dialect's rules hold by construction, and the compilation prompt emits 1.2.
5. **Real run** — `docs/acceptance/POSTMVP-006-sketch-primitives.md`, and
   `docs/adr/ADR-020-sketch-as-contours.md`.

The acceptance part is one body of 17 faces: a stadium profile of two lines and
two arcs, two circular islands, a hexagonal hub on an auxiliary plane, and a pin
on a face named by a POSTMVP-005 selector — the first thing in this service to
consume one. Every horizontal face's area matches the arithmetic to three
decimals.

Five defects came out of the real runs, all of them things that built or
exported successfully while being wrong: construction geometry needs the
construction style, `IArc.Direction` 0 is the anticlockwise one, a base
extrusion always makes a new body, one API5 object per build, and a mesh-derived
bounding box is inscribed. Each is written up in the acceptance document with
what was measured.

## Not done

- The drawing agent still extracts a rectangle and round holes. The IR and the
  adapter handle much more; reading an arbitrary outline off a scan is a vision
  problem and belongs to its own milestone.
- Auxiliary planes and face selectors are not offered to Codex, for the dialect
  reason above. Both reach the adapter through the manual API.
- Only the offset auxiliary plane is built. `Planes3D.Add(15)` and `Add(16)` are
  confirmed present and unused.
- Constraints, dimensions and auto-parameterisation are POSTMVP-007, as planned.
