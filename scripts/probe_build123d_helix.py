"""What a helix actually does in this kernel, before CAD-IR is asked to describe one.

    .venv-cad/Scripts/python.exe scripts/probe_build123d_helix.py

P4.3 is the wall the rest of stage P4 sits behind: a spring, an auger, a helical
groove and a real modelled thread all need a helical path, and a helical path needs a
way to say where a point is in space, which CAD-IR does not have. Everything above it
in `docs/GATE-P4-ANALYSIS.md` is marked "needs P4.3 first".

This probe does what P3.2's did for `extrude(until=…)` and what the KOMPAS probes did
before it: **ask the kernel rather than the documentation**, and find the failure
modes before the contract is written around them. The rule this repository has
arrived at four times is that this kernel's failure mode is a plausible answer, so
the questions here are mostly "does it lie, and how".

Nothing here changes CAD-IR. It is written to be read beside the numbers it prints.
"""

from __future__ import annotations

import math
import sys

from build123d import (
    Axis,
    Circle,
    Helix,
    Plane,
    Rectangle,
    Solid,
    Vector,
    sweep,
)


def line(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 66 - len(title)))


def describe(label: str, solid, expected: float | None = None) -> None:
    """One part, measured the way the corpus measures: volume, topology, validity."""
    try:
        volume = float(solid.volume)
        faces, edges, vertices = len(solid.faces()), len(solid.edges()), len(solid.vertices())
        # `is_valid` is a *property* in build123d 0.11.1 and calling it raises
        # `TypeError: 'bool' object is not callable`, which looks like a geometry
        # failure and is not. It cost twenty minutes in the P3.2 investigation.
        valid = bool(solid.is_valid)
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"  {label:34} RAISED {type(error).__name__}: {error}")
        return
    note = ""
    if expected is not None:
        note = f"  closed form {expected:.4f}  diff {abs(volume - expected):.3e}"
    print(f"  {label:34} vol {volume:12.4f}  {faces:2}/{edges:2}/{vertices:2}  "
          f"valid={valid}{note}")


def swept(section, path, label: str, expected: float | None = None) -> None:
    try:
        solid = sweep(section, path, is_frenet=True)
    except Exception as error:  # noqa: BLE001
        print(f"  {label:34} RAISED {type(error).__name__}: {error}")
        return
    describe(label, solid, expected)


def main() -> int:
    print("build123d helix probe — what P4.3 would have to describe")

    # ---------------------------------------------------------------- the helix itself
    line("1. what a Helix is made of")
    for turns, pitch, radius in ((1, 10.0, 20.0), (3, 10.0, 20.0), (3, 4.0, 20.0)):
        helix = Helix(pitch=pitch, height=pitch * turns, radius=radius)
        length = helix.length
        # A helix of radius r and pitch p over n turns has arc length
        # n * sqrt((2*pi*r)^2 + p^2) -- the hypotenuse of the unrolled turn.
        closed = turns * math.hypot(2 * math.pi * radius, pitch)
        print(f"  pitch {pitch:5.1f} turns {turns}  length {length:10.4f}  "
              f"closed form {closed:10.4f}  diff {abs(length - closed):.3e}  "
              f"edges {len(helix.edges())}")

    # A helix is one edge whatever its length, which matters for the topology oracle:
    # the sweep formulas in GATE-P4-ANALYSIS count faces per *path segment*.
    line("2. a swept spring, against Pappus")
    for turns in (1, 2, 3):
        pitch, radius, wire = 10.0, 20.0, 2.0
        helix = Helix(pitch=pitch, height=pitch * turns, radius=radius)
        section = Plane(origin=helix @ 0, z_dir=helix % 0) * Circle(wire)
        # Pappus is exact when the centroid rides the path and the section stays
        # perpendicular to it: area x length.
        swept(section, helix, f"spring, {turns} turn(s)",
              expected=math.pi * wire**2 * helix.length)

    line("3. the section's own plane: does orientation change the answer?")
    helix = Helix(pitch=10.0, height=30.0, radius=20.0)
    perpendicular = Plane(origin=helix @ 0, z_dir=helix % 0) * Circle(2.0)
    flat = Plane.XY * Circle(2.0)
    swept(perpendicular, helix, "section on the path's normal",
          expected=math.pi * 4.0 * helix.length)
    swept(flat, helix, "section left on XY", expected=math.pi * 4.0 * helix.length)

    line("4. a square section — does it twist with the path?")
    helix = Helix(pitch=10.0, height=30.0, radius=20.0)
    square = Plane(origin=helix @ 0, z_dir=helix % 0) * Rectangle(4.0, 4.0)
    swept(square, helix, "square section, frenet", expected=16.0 * helix.length)
    try:
        solid = sweep(square, helix, is_frenet=False)
        describe("square section, no frenet", solid, expected=16.0 * helix.length)
    except Exception as error:  # noqa: BLE001
        print(f"  {'square section, no frenet':34} RAISED {type(error).__name__}: {error}")

    line("5. self-intersection: a pitch too small for the wire")
    radius, wire = 20.0, 2.0
    for pitch in (10.0, 4.0, 3.9, 2.0):
        helix = Helix(pitch=pitch, height=pitch * 2, radius=radius)
        section = Plane(origin=helix @ 0, z_dir=helix % 0) * Circle(wire)
        # Turns touch when the pitch equals twice the wire radius. Below that the
        # solid passes through itself, and the question is whether it says so.
        swept(section, helix, f"pitch {pitch:4.1f} (touch at {2 * wire:.1f})",
              expected=math.pi * wire**2 * helix.length)

    line("6. a left-hand helix, and a thread's actual shape")
    for hand in (True, False):
        helix = Helix(pitch=6.0, height=18.0, radius=10.0, lefthand=hand)
        section = Plane(origin=helix @ 0, z_dir=helix % 0) * Circle(1.0)
        swept(section, helix, f"lefthand={hand}",
              expected=math.pi * 1.0 * helix.length)

    line("7. cutting a groove: does the tool reach the material it should?")
    blank = Solid.make_cylinder(10.0, 30.0)
    helix = Helix(pitch=6.0, height=18.0, radius=10.0)
    section = Plane(origin=helix @ 0, z_dir=helix % 0) * Circle(1.0)
    try:
        tool = sweep(section, helix, is_frenet=True)
        grooved = blank - tool
        # The groove removes at most the tool's own volume; less where the tool
        # leaves the blank. Reported rather than predicted -- what is being asked is
        # whether the subtraction is well-formed at all.
        describe("cylinder minus helical tool", grooved)
        print(f"  {'':34} blank {blank.volume:.4f}  tool {tool.volume:.4f}  "
              f"removed {blank.volume - grooved.volume:.4f}")
    except Exception as error:  # noqa: BLE001
        print(f"  {'cylinder minus helical tool':34} RAISED {type(error).__name__}: {error}")

    line("8. what a document would have to state")
    helix = Helix(pitch=10.0, height=30.0, radius=20.0)
    start, end = helix @ 0, helix @ 1
    print(f"  start {tuple(round(float(v), 4) for v in (start.X, start.Y, start.Z))}")
    print(f"  end   {tuple(round(float(v), 4) for v in (end.X, end.Y, end.Z))}")
    print(f"  tangent at 0 {tuple(round(float(v), 4) for v in helix % 0)}")
    print("  -> pitch, height, radius, hand and an axis. Five numbers and a direction,")
    print("     none of which is a point in space: a helix is describable without the")
    print("     general 3D-curve vocabulary P4.3 was assumed to need.")
    return 0


if __name__ == "__main__":  # pragma: no cover - a probe
    raise SystemExit(main())
