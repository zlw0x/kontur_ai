"""What a path that leaves its plane actually does in this kernel.

    .venv-cad/Scripts/python.exe scripts/probe_build123d_3d_path.py

P4.3 is the last wall of stage P4 and the roadmap lists five things behind it: a 3D
polyline, a 3D spline, a cylindrical/conical helix, an intersection or projected
curve, and imported points. `docs/GATE-P4-ANALYSIS.md` calls it "a new coordinate
vocabulary in CAD-IR; the largest single piece of P4", and the helix investigation
already took three of P4.4's four templates out from behind it by measuring instead
of inheriting the sentence.

This probe asks the same question of what is left. The rule this repository has
arrived at five times is that **this kernel's failure mode is a plausible answer**, so
most of the questions are "does it lie, and how" — and one is upstream of the kernel
entirely: *do the numbers a document would state determine the part?* For a spline
they do not, and that is the finding this probe exists for.

Nothing here changes CAD-IR. It is written to be read beside the numbers it prints.
"""

from __future__ import annotations

import math
import time

from build123d import (
    Box,
    Circle,
    Cylinder,
    Edge,
    Helix,
    Plane,
    Rectangle,
    Vector,
    Wire,
    sweep,
)
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer


def line(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 68 - len(title)))


def describe(label: str, solid, expected: float | None = None) -> None:
    try:
        volume = float(solid.volume)
        faces, edges, vertices = len(solid.faces()), len(solid.edges()), len(solid.vertices())
        # `is_valid` is a *property* in build123d 0.11.1; calling it raises
        # `TypeError: 'bool' object is not callable`, which reads like a geometry
        # failure and is not. Noted in the helix probe for the same reason.
        valid = bool(solid.is_valid)
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"  {label:34} RAISED {type(error).__name__}: {error}")
        return
    note = ""
    if expected is not None:
        note = f"  closed form {expected:11.4f}  diff {abs(volume - expected):.3e}"
    print(f"  {label:34} vol {volume:12.4f}  {faces:2}/{edges:2}/{vertices:2}  "
          f"valid={valid}{note}")


def swept(section, path, label: str, expected: float | None = None, **kwargs) -> None:
    try:
        solid = sweep(section, path, **kwargs)
    except Exception as error:  # noqa: BLE001
        print(f"  {label:34} RAISED {type(error).__name__}: {error}")
        return
    describe(label, solid, expected)


def wrap_turns(curve, samples: int = 4000) -> float:
    """How many times a curve goes round the Z axis, by walking it.

    Measured rather than assumed, because section 8 turns on the answer being
    something other than `height / pitch`.
    """
    total, previous = 0.0, None
    for index in range(samples + 1):
        point = curve @ (index / samples)
        angle = math.atan2(float(point.Y), float(point.X))
        if previous is not None:
            step = angle - previous
            while step > math.pi:
                step -= 2 * math.pi
            while step < -math.pi:
                step += 2 * math.pi
            total += step
        previous = angle
    return total / (2 * math.pi)


# --- the path the whole probe is built around -------------------------------------
#
# A pipe run of the shape a drawing actually gives: straight lengths and bend radii,
# with the two bends in *different planes*. That is the smallest path that is
# genuinely three-dimensional — everything CAD-IR 1.9 can say lies in one plane.
#
#   A (0,0,0)  --+X, 30-->  B (30,0,0)
#   B          --bend R20 in XY, +X to +Y-->  C (50,20,0)
#   C          --+Y, 30-->  D (50,50,0)
#   D          --bend R20 in YZ, +Y to +Z-->  E (50,70,20)
#   E          --+Z, 30-->  F (50,70,50)
#
# Length = 30 + (pi/2)(20) + 30 + (pi/2)(20) + 30 = 90 + 20*pi.

RUN = 30.0
BEND = 20.0
PATH_LENGTH = 3 * RUN + 2 * (math.pi / 2) * BEND


def pipe_run() -> Wire:
    a, b = Vector(0, 0, 0), Vector(RUN, 0, 0)
    c = Vector(RUN + BEND, BEND, 0)
    d = Vector(RUN + BEND, BEND + RUN, 0)
    e = Vector(RUN + BEND, BEND + RUN + BEND, BEND)
    f = Vector(RUN + BEND, BEND + RUN + BEND, BEND + RUN)
    return Wire(
        [
            Edge.make_line(a, b),
            Edge.make_tangent_arc(b, Vector(1, 0, 0), c),
            Edge.make_line(c, d),
            Edge.make_tangent_arc(d, Vector(0, 1, 0), e),
            Edge.make_line(e, f),
        ]
    )


def planar_run() -> Wire:
    """The same lengths with both bends in one plane — 1.9 can already say this one."""
    a, b = Vector(0, 0, 0), Vector(RUN, 0, 0)
    c = Vector(RUN + BEND, BEND, 0)
    d = Vector(RUN + BEND, BEND + RUN, 0)
    e = Vector(RUN + 2 * BEND, BEND + RUN + BEND, 0)
    f = Vector(RUN + 2 * BEND + RUN, BEND + RUN + BEND, 0)
    return Wire(
        [
            Edge.make_line(a, b),
            Edge.make_tangent_arc(b, Vector(1, 0, 0), c),
            Edge.make_line(c, d),
            Edge.make_tangent_arc(d, Vector(0, 1, 0), e),
            Edge.make_line(e, f),
        ]
    )


def at_start(path, shape):
    """The section standing across the path where it starts."""
    return Plane(origin=path @ 0, z_dir=path % 0) * shape


def corner_direction(solid, at) -> tuple[float, ...]:
    """Which way the nearest planar face's corner points, from its own centre.

    A 10 x 6 section has its corner at (5, 3), so this direction says how the
    rectangle is turned in space — the one thing about a swept section that the
    document does not state.
    """
    face = min(solid.faces(), key=lambda f: float((f.center() - at).length))
    centre = face.center()
    corner = max((Vector(*tuple(v)) for v in face.vertices()),
                 key=lambda v: float((v - centre).length))
    return tuple(round(float(v), 4) for v in (corner - centre).normalized())


def main() -> int:  # noqa: PLR0915 - a probe is a list of measurements
    print("build123d 3D-path probe — what P4.3 would have to describe")

    # ---------------------------------------------------------------- 1. does it sweep
    line("1. a path that leaves its plane, against Pappus")
    path, flat = pipe_run(), planar_run()
    print(f"  path length {float(path.length):10.4f}  closed form {PATH_LENGTH:10.4f}  "
          f"diff {abs(float(path.length) - PATH_LENGTH):.3e}  edges {len(path.edges())}")

    # Pappus for a tube: the volume is area x length exactly, for *any* curve in space,
    # as long as the section's centroid rides the path and the section stays
    # perpendicular to it. The curvature correction is the section's first moment about
    # the path, which is zero when the centroid is on it — so torsion, which is the
    # whole difference between a 3D path and a planar one, drops out of the volume.
    swept(at_start(path, Circle(5.0)), path, "circle 5, 3D run",
          expected=math.pi * 25.0 * PATH_LENGTH)
    swept(at_start(flat, Circle(5.0)), flat, "circle 5, the same run kept planar",
          expected=math.pi * 25.0 * float(flat.length))

    # ---------------------------------------------------- 2. a section that has corners
    line("2. a square section: the volume cannot see the third dimension")
    swept(at_start(path, Rectangle(10.0, 6.0)), path, "10x6 section, 3D run",
          expected=60.0 * PATH_LENGTH)
    swept(at_start(flat, Rectangle(10.0, 6.0)), flat, "10x6 section, planar run",
          expected=60.0 * float(flat.length))

    line("3. which way is the far end of that section facing?")
    # The question the document has to answer and cannot. A section is placed at the
    # start; how it is carried round a path that leaves its plane is a choice, and the
    # only thing recording the choice is the built part.
    for frenet in (False, True):
        try:
            solid = sweep(at_start(path, Rectangle(10.0, 6.0)), path, is_frenet=frenet)
            print(f"  is_frenet={str(frenet):5}  vol {float(solid.volume):11.4f}  "
                  f"start corner {corner_direction(solid, path @ 0)}  "
                  f"end corner {corner_direction(solid, path @ 1)}")
        except Exception as error:  # noqa: BLE001
            print(f"  is_frenet={frenet} RAISED {type(error).__name__}: {error}")
    print("  -> the section is carried by the rotation that carries the tangent, which")
    print("     is deterministic and is composed from every bend before it. Nothing in")
    print("     the document states the far end's orientation and no measurement of the")
    print("     part disagrees with it.")

    line("4. is a section still swept as its projection if it is not across the path?")
    swept(Plane.YZ * Circle(5.0), path, "section perpendicular (Plane.YZ)",
          expected=math.pi * 25.0 * PATH_LENGTH)
    swept(Plane(origin=(0, 0, 0), z_dir=(1, 0, 1)) * Circle(5.0), path,
          "section tilted 45 deg", expected=math.pi * 25.0 * PATH_LENGTH)

    # -------------------------------------------------------- 5. the spline, on its own
    line("5. a spline: do the stated points determine the curve?")
    points = [(0, 0, 0), (30, 10, 0), (60, 0, 20), (90, 20, 20)]
    variants = [
        ("default", {}),
        ("scale=False", {"scale": False}),
        ("uniform parameters", {"parameters": [0.0, 1 / 3, 2 / 3, 1.0]}),
        ("tangents stated", {"tangents": [(1, 0, 0), (1, 0, 0)]}),
    ]
    for label, kwargs in variants:
        try:
            edge = Edge.make_spline([Vector(*p) for p in points], **kwargs)
            box = edge.bounding_box()
            print(f"  {label:20} length {float(edge.length):10.4f}  "
                  f"bbox y[{float(box.min.Y):7.3f},{float(box.max.Y):7.3f}] "
                  f"z[{float(box.min.Z):7.3f},{float(box.max.Z):7.3f}]")
        except Exception as error:  # noqa: BLE001
            print(f"  {label:20} RAISED {type(error).__name__}: {error}")
    print(f"  {'the points themselves':20} {'':17}  "
          f"bbox y[{0.0:7.3f},{20.0:7.3f}] z[{0.0:7.3f},{20.0:7.3f}]")
    print("  -> one point list, three lengths, and a curve that leaves the box its own")
    print("     points define. Neither the shape nor the envelope is stated by the")
    print("     numbers the document would carry.")

    line("6. a spline is at least the same curve twice")
    first = Edge.make_spline([Vector(*p) for p in points])
    second = Edge.make_spline([Vector(*p) for p in reversed(points)])
    print(f"  forwards {float(first.length):.10f}   backwards {float(second.length):.10f}"
          f"   diff {abs(float(first.length) - float(second.length)):.3e}")
    print("  -> reproducible, which is a different thing from determined. ADR-018 needs")
    print("     the second: a hash identifies a part only if the document does.")

    line("7. and what a swept spline is worth to an expectation")
    spline = Wire([Edge.make_spline([Vector(*p) for p in points])])
    swept(at_start(spline, Circle(4.0)), spline, "circle 4 along the spline",
          expected=math.pi * 16.0 * float(spline.length))
    print("  -> even against the kernel's *own* length the agreement is 1e-3 rather than")
    print("     the 1e-12 an analytic path gives, and that length is not a closed form")
    print("     at all: there is no number here the corpus could state from a drawing.")

    # ------------------------------------------------------------- 8. a conical helix
    line("8. a conical helix: `pitch` is not the drawing's pitch")
    for cone in (0.0, 5.0, 15.0, 30.0):
        helix = Helix(pitch=10.0, height=30.0, radius=20.0, cone_angle=cone)
        turns = wrap_turns(helix)
        # r(z) = r0 + z*tan(a), verified by sampling; with dz/dtheta = k,
        #   ds/dtheta = sqrt(r^2 + k^2 sec^2 a),  and  int sqrt(r^2+c^2) dr  has the
        # closed form (r sqrt(r^2+c^2) + c^2 asinh(r/c)) / 2.
        k = 30.0 / (2 * math.pi * turns)
        if cone == 0.0:
            closed = turns * math.hypot(2 * math.pi * 20.0, 10.0)
        else:
            tan_a = math.tan(math.radians(cone))
            c = k * math.hypot(1.0, tan_a)
            r0, r1 = 20.0, 20.0 + 30.0 * tan_a

            def anti(r: float, c: float = c) -> float:
                return (r * math.hypot(r, c) + c * c * math.asinh(r / c)) / 2

            closed = (anti(r1) - anti(r0)) / (k * tan_a)
        print(f"  cone {cone:5.1f} deg  turns {turns:8.5f}  z per turn {30.0 / turns:8.5f}"
              f"  length {float(helix.length):9.4f}  closed {closed:9.4f}  "
              f"diff {abs(float(helix.length) - closed):.3e}")
    print("  -> z per turn is `pitch * cos(cone_angle)`: the kernel measures the pitch")
    print("     along the cone's slant, and a drawing dimensions it along the axis. A")
    print("     document stating pitch 10 at 30 deg gets 3.464 turns where it drew 3.")

    # ------------------------------------------------- 9. what a 3D bend has to state
    line("9. stating a bend in space: which forms are unambiguous?")
    start, end = Vector(30, 0, 0), Vector(50, 20, 0)
    centre = Vector(30, 20, 0)
    tangent = Edge.make_tangent_arc(start, Vector(1, 0, 0), end)
    mid = Vector(30 + 20 * math.sin(math.pi / 4), 20 - 20 * math.cos(math.pi / 4), 0)
    three = Edge.make_three_point_arc(start, mid, end)
    print(f"  tangent arc (start, tangent, end)  length {float(tangent.length):9.4f}")
    print(f"  three-point arc                    length {float(three.length):9.4f}  "
          f"diff {abs(float(tangent.length) - float(three.length)):.3e}")
    print(f"  and the centre is derivable: |start-c| {float((start - centre).length):.4f}"
          f"  |end-c| {float((end - centre).length):.4f}")
    print("  -> a *tangent-continuous* arc is fixed by (start, incoming tangent, end),")
    print("     and 1.9 already requires tangency. So a bend in space needs no")
    print("     vocabulary a straight run does not need: a point with three components.")

    line("10. a bend no arc can make")
    for label, target in (("end straight ahead", Vector(60, 0, 0)),
                          ("end behind the start", Vector(-10, 0, 0))):
        try:
            edge = Edge.make_tangent_arc(Vector(30, 0, 0), Vector(1, 0, 0), target)
            print(f"  {label:22} length {float(edge.length):10.4f}")
        except Exception as error:  # noqa: BLE001
            print(f"  {label:22} RAISED {type(error).__name__}: {error}")

    # ------------------------------------------- 11. the check 1.9 has, and the one it has not
    line("11. a bend tighter than the profile, in space")
    tight = Wire(
        [
            Edge.make_line(Vector(0, 0, 0), Vector(30, 0, 0)),
            Edge.make_tangent_arc(Vector(30, 0, 0), Vector(1, 0, 0), Vector(34, 4, 0)),
            Edge.make_line(Vector(34, 4, 0), Vector(34, 34, 0)),
            Edge.make_tangent_arc(Vector(34, 34, 0), Vector(0, 1, 0), Vector(38, 38, 4)),
        ]
    )
    swept(at_start(tight, Circle(8.0)), tight, "R4 bend, section reaches 8",
          expected=math.pi * 64.0 * float(tight.length))
    print("  -> exactly as in the plane: valid, and Pappus agrees. `require_bends_clear"
          "_the_profile`")
    print("     is as necessary in space as it is in a plane, on the same arithmetic.")

    line("12. a path that comes back beside itself")
    # It has to be a *spiral*, and that is the finding. A U-turn cannot do it: two
    # tangent bends of radius R put the outgoing and returning runs 2R apart, and the
    # bend rule already requires R to clear the profile — so 2R >= 2 * reach and the
    # runs can never touch. What the per-bend check cannot see is a path that comes back
    # alongside a part of itself that is not its neighbour.
    #
    # Every bend here is R35 and the section reaches 30, so the bend rule is satisfied.
    # The last run is 25 mm from the first.
    def at(x: float, y: float) -> Vector:
        return Vector(x, y, 0)

    spiral = Wire(
        [
            Edge.make_line(at(0, 0), at(200, 0)),
            Edge.make_tangent_arc(at(200, 0), Vector(1, 0, 0), at(235, 35)),
            Edge.make_line(at(235, 35), at(235, 160)),
            Edge.make_tangent_arc(at(235, 160), Vector(0, 1, 0), at(200, 195)),
            Edge.make_line(at(200, 195), at(30, 195)),
            Edge.make_tangent_arc(at(30, 195), Vector(-1, 0, 0), at(-5, 160)),
            Edge.make_line(at(-5, 160), at(-5, 60)),
            Edge.make_tangent_arc(at(-5, 60), Vector(0, -1, 0), at(30, 25)),
            Edge.make_line(at(30, 25), at(150, 25)),
        ]
    )
    swept(at_start(spiral, Circle(30.0)), spiral, "spiral, runs 25 apart, section 30",
          expected=math.pi * 900.0 * float(spiral.length))
    swept(at_start(spiral, Circle(10.0)), spiral, "the same spiral, section 10",
          expected=math.pi * 100.0 * float(spiral.length))
    print("  -> the first is valid, one solid, and Pappus agrees to the digit, because")
    print("     the material counted twice is the material the formula counts twice.")
    print("     Its B-rep is genus 0 and its mesh is a closed manifold of genus 0 with")
    print("     zero open edges, so the POSTMVP-020 cross-check agrees with itself too.")
    print("     Every check this service has passes. And this is a *planar* path: the")
    print("     hole is in 1.9, and a spatial path only makes it easier to write by")
    print("     accident, because two views do not show the clearance between two runs.")

    line("13. and the one question that does catch it")
    for label, shape in (
        ("a plain block", Box(60, 40, 8)),
        ("a cylinder", Cylinder(20, 40)),
        ("the spiral, section 10", sweep(at_start(spiral, Circle(10.0)), spiral)),
        ("the spiral, section 30", sweep(at_start(spiral, Circle(30.0)), spiral)),
        ("tight bend R4, section 8", sweep(at_start(tight, Circle(8.0)), tight)),
        ("the same bend, section 2", sweep(at_start(tight, Circle(2.0)), tight)),
    ):
        analyzer = BOPAlgo_ArgumentAnalyzer()
        analyzer.SetShape1(shape.wrapped)
        analyzer.SelfInterMode = True
        analyzer.StopOnFirstFaulty = True
        started = time.monotonic()
        analyzer.Perform()
        print(f"  {label:30} self-intersects={str(analyzer.HasFaulty()):5}  "
              f"{time.monotonic() - started:.2f}s")
    print("  -> `BOPAlgo_ArgumentAnalyzer` with `SelfInterMode`. It is exact, it costs")
    print("     milliseconds, and it has no false positive on an ordinary part. It says")
    print("     only *that* the solid passes through itself, which is why it is a")
    print("     backstop rather than a replacement for the closed-form pre-checks: those")
    print("     name the mistake in numbers a repair loop can read.")

    return 0


if __name__ == "__main__":  # pragma: no cover - a probe
    raise SystemExit(main())
