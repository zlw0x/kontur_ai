# P3.4: a modelled thread, and the frame nobody had chosen — the investigation

**Date:** 2026-08-12 · **Status:** measured; the engine changed, CAD-IR did not.
**Probe:** `scripts/probe_build123d_thread.py`, build123d 0.11.1 / OpenCascade 7.9.3.1.1

Gate P3 asks for one thing this repository had never measured:

> **Gate P3:** корпуса, крышки и печатные детали строятся без ручного вмешательства;
> **modeled threads проходят manifold check**.

Until CAD-IR 1.14 a thread was not expressible at all, so the clause could not be tested.
Now it is — a profiled section swept along a helix and subtracted — and the answer is
**yes, with one engine change that had to come first**.

The change is not about threads. It is about a frame that no document could see, and a
round section could not tell was there.

---

## 1. A helix's section had a frame nobody chose

`SketchOnPathStart` (ADR-040) says "wherever the path starts, across it", and the
engine built that plane as `Plane(origin=wire @ 0, z_dir=wire % 0)`. That fixes the
plane's **normal** and leaves its in-plane frame to build123d, whose rule is to project
whichever global axis is least parallel to the normal:

```text
pitch  2.00 r 10.0   build123d picks x (0.0000, -0.0318, 0.9995)   x·radial -0.000000   x·axis +0.999494
pitch  1.50 r  6.0   build123d picks x (0.0000, -0.0398, 0.9992)   x·radial +0.000000   x·axis +0.999209
pitch 10.00 r 20.0   build123d picks x (-0.000, -0.0793, 0.9968)   x·radial -0.000000   x·axis +0.996849
```

For a helix that happens to give the axis. For the 3D-path probe's directions it gave the
projection of **+X**. It is a heuristic, not a convention, and a document that drew a
profile in it would be drawing in a frame that belongs to a library version.

**A circular section cannot tell**, which is exactly why 1.14 never had to ask. A
thread's flanks are nothing *but* a direction:

```text
apex radially inward (-y)    tool 380.8933   removed 374.1876
apex along the screw (-x)    tool 398.8554   removed 188.3405
```

Half the material, from the same three numbers, with no error and no difference the
document can see. The drawing's depth is nowhere in the part.

So the engine builds the frame from the path itself (`helix_section_plane`): **x is the
helix's own axis projected into the section plane, y is radially outward.** It cannot be
exactly the axis — the plane is perpendicular to a tangent that leans by the lead angle —
and the projection is the nearest thing the geometry allows. That is the frame a drawing
draws a thread profile in: along the screw, and depth measured inward.

Nothing in CAD-IR changes. Every existing document that uses `path_start` carries a
circular section, which is invariant under the whole question.

---

## 2. The default framing twists the section as it travels

The second half, and the one with a number that grows.

```text
 1.0 turns   corrected  63.5154   Frenet  63.4822   closed  63.4822   drift 0.052%
 3.0 turns   corrected 191.3526   Frenet 190.4463   closed 190.4466   drift 0.476%
 6.0 turns   corrected 387.4932   Frenet 380.8933   closed 380.8931   drift 1.733%
12.0 turns   corrected 797.9363   Frenet 761.7851   closed 761.7862   drift 4.745%
```

OpenCascade's default is a *corrected* frame, which keeps the section from twisting
relative to a **fixed** direction — and round a helix that means twisting relative to the
path's own normal, progressively. Under Frenet the closed form is exact at every turn
count (`Frenet err ≤ 0.0002%`).

The closed form is Pappus with the first-moment correction, which is the other thing a
round section hid:

```text
V = A·L·(1 − κ·ū)      κ = r/(r² + c²),  c = pitch/2π,  ū = depth/3
```

The volume element of a tube is `(1 − uκ) du dv ds`, so the correction is the section's
first moment about the path. A circle is **centred on the path**, so `ū = 0` and the
whole correction vanishes — ADR-040's spring never had to know it existed. A V with its
apex inward does.

So the helical branch sweeps with `is_frenet=True`. It stays on that branch rather than
becoming the engine's default: Frenet is well defined here because a helix has no point
of zero curvature, and a path with a straight run does.

---

## 3. Gate P3's own question

An M20 × 2.5 external thread, ISO 60°, cut 5H/8 deep — a blank and a helical cut, which
is **composition and not a new operation**:

```text
M20x2.5,  2 turns   built in 0.13s   volume  1450.5265    2284 triangles   0 open   0 flipped   genus 0   112 KiB
M20x2.5,  6 turns   built in 0.38s   volume  4338.2014   10186 triangles   0 open   0 flipped   genus 0   497 KiB
M20x2.5, 12 turns   built in 1.68s   volume  8669.7027   11830 triangles   0 open   0 flipped   genus 0   578 KiB
```

**The manifold check passes.** It costs a second and half a megabyte at twelve turns,
which is worth knowing before anybody offers threads on a real part but is not a wall.

`feature.thread` is not added, and the rule is POSTMVP-011's: an operation earns its
place only when it says what composition cannot. A thread is a `solid.extrude` and a
`cut.sweep` along a helix, and every number in it is one the drawing gives.

---

## 4. The order of the cuts is the whole part

The sharpest thing the probe found, and it is about booleans rather than about threads.
Three ways of writing the same nut out of the same three solids:

```text
(shell − groove) − bore    3953.2440    6072 triangles      0 open   genus 1
shell − bore − groove      4146.9023    1008 triangles      0 open   genus 1
shell − (bore + groove)    6157.5215   21908 triangles  14324 open   genus 2
```

The first is the part. The second is **the plain hollow nut, to the digit** — 4146.9023
is what the shell minus the bore measures on its own, so the groove did nothing and said
nothing. The third is a mesh nobody can print.

CAD-IR applies features in the document's own order (ADR-028), so this is the document's
decision, and nothing in the contract tells it which order is right. Only the second is
**silent**: the third fails `closed_manifold_mesh` on every build, which is a check that
already runs.

One detail is worth keeping because it costs 193 open edges on its own: an internal
groove whose base lies exactly **on** the bore's surface meets it tangentially, and a
tool that touches a surface rather than crossing it is the degenerate case for every
kernel. The base is carried 0.2 mm into the void instead. That is not inventing a
clearance the drawing did not give — the groove's depth and width are unchanged — it is
how a tool is made to break a surface at all.

---

## 5. What is left of P3.4, and it is not geometry

The roadmap splits threads in two:

1. `thread.designation` — a **callout**, and this is the one that is genuinely missing.
   POSTMVP-011 said so when it refused `feature.hole`: "what is genuinely missing is a
   thread callout, which is a manufacturing note rather than geometry." It is still true
   and it is still not built.
2. `thread.modeled` — real helical geometry, **measured above and needing no contract
   change at all**.

A callout is a contract change of a different kind from every one before it: it states
something no measurement of the delivered solid can check. M20×2.5-6g is not a shape —
the same part carries it whether the tolerance class is right or wrong, and whether the
hand is right or wrong. It belongs beside `hand` in ADR-040's argument: **a property of
the part that only a person can catch being wrong.**

That makes its place in the pipeline clear rather than obvious: the reading stage has to
lift it off the drawing, the claim has to carry it so the compiled document can be
compared against what was read, and the operator's page has to show it — because the
moderation queue is the only thing that can catch it. Building it is a CAD-IR version,
and it is the next one this line needs.

**What is deliberately not next**: P3.5's high-level features (pocket, keyway, groove,
O-ring groove, slot, boss, standoff, vent, cable gland). Every one compiles into
operations the contract already has, which is exactly the argument POSTMVP-011 used
against hole families and POSTMVP-022 used against a rib. They would be a second way to
say what CAD-IR says once, and every extra type is another thing to validate.

---

## Reproducing

```bash
.venv-cad/Scripts/python.exe scripts/probe_build123d_thread.py
```

Committed, like the helix and 3D-path probes, because its numbers are the argument. The
same caution as both: `Shape.is_valid` is a **property** in build123d 0.11.1 and calling
it raises `TypeError: 'bool' object is not callable`.
