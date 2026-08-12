"""What a modelled thread costs, and whether the document can aim its own profile.

    .venv-cad/Scripts/python.exe scripts/probe_build123d_thread.py

Gate P3 names one thing this repository had never measured: *modeled threads pass a
manifold check*. Until CAD-IR 1.14 a thread was not expressible at all; now it is a
profiled section swept along a helix and subtracted, which is composition rather than a
new operation -- so what is left is whether it works, what it costs, and whether the
corpus can state a number about it.

The second question is the one that decided an engine change. A helical path puts the
section on the plane the path starts on (`SketchOnPathStart`, ADR-040), and that plane's
*normal* is fixed by the path. Its **in-plane frame is not stated by anything** --
build123d picks one. A circular section cannot tell. A V profile is nothing but a
direction, so if the choice is not the drawing's, a thread document cannot aim its own
flanks.

Nothing here changes CAD-IR. It is written to be read beside the numbers it prints.
"""

from __future__ import annotations

import math
import os
import pathlib
import sys
import tempfile
import time

from build123d import (
    Cylinder,
    Helix,
    Location,
    Plane,
    Polyline,
    Vector,
    Wire,
    export_stl,
    make_face,
    sweep,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "packages", "build123d-adapter"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "packages", "cad-ir"))

from cad_engine_build123d.sweeps import helix_section_plane  # noqa: E402
from cad_engine_build123d.verify import _edge_facts, _parse_stl, topology_of  # noqa: E402

# An M20 x 2.5 external thread, ISO 60 degrees. The sharp V's height is pitch*sqrt(3)/2
# and a real thread cuts 5/8 of it; the width at that depth is 2*d*tan30 = 5*pitch/8.
MAJOR, PITCH = 20.0, 2.5
DEPTH = PITCH * math.sqrt(3) / 2 * 5 / 8
WIDTH = 2 * DEPTH * math.tan(math.radians(30.0))


def line(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 68 - len(title)))


def vee(width: float, depth: float):
    """The thread's section: along the screw in x, depth radially inward in y."""
    return make_face(Polyline((width / 2, 0.0), (0.0, -depth), (-width / 2, 0.0),
                              close=True))


def tool_volume(pitch: float, height: float, radius: float, depth: float,
                width: float) -> float:
    """`A*L*(1 - kappa*u_bar)` -- Pappus with the first-moment correction.

    The volume element of a tube is `(1 - u*kappa) du dv ds`, so the correction is the
    section's first moment about the path. A helix has constant curvature
    `kappa = r/(r^2 + c^2)` with `c = pitch/2pi` and its normal points at the axis, so a
    triangle whose apex is inward has `u_bar = depth/3`.

    A round section is centred on the path, so `u_bar = 0` and the whole correction
    vanishes -- which is why ADR-040's spring never had to know about any of this.
    """
    c = pitch / (2 * math.pi)
    curvature = radius / (radius * radius + c * c)
    length = (height / pitch) * math.hypot(2 * math.pi * radius, pitch)
    return (width * depth / 2) * length * (1 - curvature * depth / 3)


def mesh_facts(solid, label: str) -> None:
    """Gate P3's actual bar: does the delivered mesh close?"""
    directory = tempfile.mkdtemp()
    name = os.path.join(directory, "thread.stl")
    started = time.monotonic()
    export_stl(solid, name)
    elapsed = time.monotonic() - started
    triangles = _parse_stl(pathlib.Path(name).read_bytes())
    open_edges, flipped = _edge_facts(triangles)
    print(f"  {label:30} {len(triangles):7} triangles  open {open_edges:4}  "
          f"flipped {flipped:3}  brep genus {topology_of(solid).genus:3}  "
          f"{os.path.getsize(name) / 1024:7.0f} KiB  export {elapsed:5.2f}s")


def main() -> int:  # noqa: PLR0915 - a probe is a list of measurements
    print("build123d thread probe -- Gate P3's manifold check, measured")

    # ------------------------------------------- 1. where does the section's x point?
    line("1. the frame `SketchOnPathStart` hands a section")
    for pitch, radius in ((2.0, 10.0), (1.5, 6.0), (10.0, 20.0)):
        helix = Wire(Helix(pitch=pitch, height=pitch * 3, radius=radius).edges())
        inherited = Plane(origin=helix @ 0, z_dir=helix % 0)
        chosen = helix_section_plane(helix, Vector(0, 0, 1))
        start = helix @ 0
        radial = Vector(float(start.X), float(start.Y), 0.0).normalized()
        print(f"  pitch {pitch:5.2f} r {radius:5.1f}")
        print(f"    build123d picks x {tuple(round(float(v), 4) for v in inherited.x_dir)}"
              f"   x . radial {float(inherited.x_dir.dot(radial)):+.6f}"
              f"   x . axis {float(inherited.x_dir.dot(Vector(0, 0, 1))):+.6f}")
        print(f"    the engine builds x {tuple(round(float(v), 4) for v in chosen.x_dir)}"
              f"   y {tuple(round(float(v), 4) for v in chosen.y_dir)}")
    print("  -> build123d's rule is 'project whichever global axis is least parallel to")
    print("     the normal', which happens to give the axis here and gave +X for another")
    print("     direction in the 3D-path probe. A heuristic, not a convention. The engine")
    print("     projects the *helix's own axis* instead: x along the screw, y radially")
    print("     out, which is the frame a drawing draws a thread profile in.")

    # ------------------------------------ 2. and what happens when the aim is wrong
    line("2. the same section aimed the other way cuts a different thread")
    turns = 6.0
    helix = Wire(Helix(pitch=PITCH, height=PITCH * turns, radius=MAJOR / 2).edges())
    plane = helix_section_plane(helix, Vector(0, 0, 1))
    blank = Cylinder(MAJOR / 2, PITCH * turns).moved(Location((0, 0, PITCH * turns / 2)))
    for label, section in (
        ("apex radially inward (-y)", vee(WIDTH, DEPTH)),
        ("apex along the screw (-x)",
         make_face(Polyline((0.0, WIDTH / 2), (-DEPTH, 0.0), (0.0, -WIDTH / 2),
                            close=True))),
    ):
        tool = sweep(plane * section, helix, is_frenet=True)
        cut = blank - tool
        print(f"  {label:28} tool {float(tool.volume):9.4f}   "
              f"removed {float(blank.volume) - float(cut.volume):9.4f}")
    print("  -> half the material, from the same three numbers, with no error. The")
    print("     drawing's depth is nowhere in the part. Which way the flanks point is")
    print("     the whole of a thread, and until the frame was built here the document")
    print("     had no way to find out what it had said.")

    # ------------------------------------------------ 3. the frame twists as it goes
    line("3. the default frame twists the section, progressively")
    for count in (1.0, 3.0, 6.0, 12.0):
        wire = Wire(Helix(pitch=PITCH, height=PITCH * count, radius=MAJOR / 2).edges())
        section = helix_section_plane(wire, Vector(0, 0, 1)) * vee(WIDTH, DEPTH)
        closed = tool_volume(PITCH, PITCH * count, MAJOR / 2, DEPTH, WIDTH)
        frenet = float(sweep(section, wire, is_frenet=True).volume)
        corrected = float(sweep(section, wire, is_frenet=False).volume)
        print(f"  {count:5.1f} turns   corrected {corrected:9.4f}  Frenet {frenet:9.4f}  "
              f"closed {closed:9.4f}   drift {100 * abs(corrected - closed) / closed:6.3f}%"
              f"  Frenet err {100 * abs(frenet - closed) / closed:.4f}%")
    print("  -> OpenCascade's default keeps the section from twisting relative to a")
    print("     *fixed* direction, which round a helix means twisting relative to the")
    print("     path's own normal. It accumulates, it is invisible to a round section,")
    print("     and under Frenet the closed form is exact at every turn count.")

    # ------------------------------------------------- 4. Gate P3's manifold check
    line("4. the gate's own question: does the delivered mesh close?")
    for count in (2.0, 6.0, 12.0):
        wire = Wire(Helix(pitch=PITCH, height=PITCH * count, radius=MAJOR / 2).edges())
        section = helix_section_plane(wire, Vector(0, 0, 1)) * vee(WIDTH, DEPTH)
        started = time.monotonic()
        tool = sweep(section, wire, is_frenet=True)
        body = Cylinder(MAJOR / 2, PITCH * count).moved(
            Location((0, 0, PITCH * count / 2))
        )
        part = body - tool
        built = time.monotonic() - started
        print(f"  M{MAJOR:g}x{PITCH:g}, {count:g} turns   built in {built:5.2f}s   "
              f"volume {float(part.volume):11.4f}")
        mesh_facts(part, f"  {count:g} turns")

    # ----------------------------- 5. an internal thread, and the order of the cuts
    line("5. an internal thread: three orders, three different answers")
    bore, count = 16.0, 4.0
    wire = Wire(Helix(pitch=PITCH, height=PITCH * count + 4, radius=bore / 2).edges())
    # The V points outward, into the material, and its base is carried a little into
    # the void so the tool *crosses* the bore surface instead of touching it. A tool
    # that meets a surface tangentially is the degenerate case for every kernel.
    groove = sweep(
        helix_section_plane(wire, Vector(0, 0, 1))
        * make_face(Polyline((WIDTH / 2, -0.2), (0.0, DEPTH), (-WIDTH / 2, -0.2),
                             close=True)),
        wire, is_frenet=True,
    )
    shell = Cylinder(bore / 2 + 6.0, PITCH * count).moved(
        Location((0, 0, PITCH * count / 2)))
    hole = Cylinder(bore / 2, PITCH * count + 4).moved(
        Location((0, 0, PITCH * count / 2)))
    plain = shell - hole
    print(f"  the plain hollow nut          {float(plain.volume):11.4f}")
    for label, nut in (
        ("(shell - groove) - bore", (shell - groove) - hole),
        ("shell - bore - groove", shell - hole - groove),
        ("shell - (bore + groove)", shell - (hole + groove)),
    ):
        print(f"  {label:30} {float(nut.volume):11.4f}")
        mesh_facts(nut, f"  {label}")
    print("  -> one clean part, one where the groove silently did nothing (the volume")
    print("     is the plain nut's, to the digit), and one mesh with 14 324 open edges.")
    print("     The same three solids. CAD-IR applies features in the document's own")
    print("     order (ADR-028), so this is the document's decision and nothing tells")
    print("     it which order is the right one.")

    return 0


if __name__ == "__main__":  # pragma: no cover - a probe
    raise SystemExit(main())
