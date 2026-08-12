"""What is left of the roadmap, asked of the kernel rather than of the table.

    .venv-cad/Scripts/python.exe scripts/probe_build123d_remaining_stages.py

Four stages are still open on paper -- P5 surfaces, P6 sheet metal, P7 assemblies, and
the geometry half of P8 -- and every stage closed so far turned out to be smaller than
its description once somebody measured it. This probe asks the three questions that are
about geometry. The rest are about product and are decided in
`docs/TASK-POSTMVP-closing-the-remaining-stages.md`.

1. **P6.** Is a sheet-metal part expressible *today*? A folded flange of uniform
   thickness is a rectangular section carried along a path with bend radii, which
   CAD-IR 1.9 has had since sweep. If so, what is missing from P6 is the unfold, which
   is a different kind of computation and a different artifact.
2. **P7.** Can an interference between two placed bodies be measured? If the answer is
   an intersection volume, then an assembly needs no solver -- which is what ADR-022
   requires anyway: a constraint is an assertion about stated coordinates, never an
   instruction that produces them.
3. **P5.** What does the service actually lose when a shape stops being a solid? Every
   check it has -- volume, genus, closed manifold, body count, the shape claim -- is a
   question about a solid.

Nothing here changes CAD-IR.
"""

from __future__ import annotations

import math
import os
import pathlib
import sys
import tempfile

from build123d import (
    Box,
    Cylinder,
    Edge,
    Location,
    Plane,
    Pos,
    Rectangle,
    Vector,
    Wire,
    export_stl,
    extrude,
    make_face,
    sweep,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "packages", "build123d-adapter"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "packages", "cad-ir"))

from cad_ir.canonical import CAD_IR_VERSION  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.verify import _edge_facts, _parse_stl, topology_of  # noqa: E402


def flange_document(thickness: float, width: float, centre: float,
                    leg: float) -> dict:
    """A folded flange, as CAD-IR already says it: a rectangle carried round a bend."""
    return {
        "schema": "cad-ai/cad-ir", "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "flange"},
        "parameters": [],
        "features": [{
            "id": "feature.flange", "type": "solid.sweep", "enabled": True,
            "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
            "inputs": {
                "sketch": {"id": "sketch.section",
                           "plane": {"on": "base", "plane": "YZ"},
                           "outer": {"type": "rectangle", "center": [0.0, 0.0],
                                     "width": width, "height": thickness,
                                     "rotation_deg": 0.0},
                           "inner": [], "construction": [], "constraints": [],
                           "dimensions": []},
                "path": {"id": "path.spine", "plane": "XZ", "segments": [
                    {"type": "line", "start": [0.0, 0.0], "end": [leg - centre, 0.0]},
                    {"type": "arc", "start": [leg - centre, 0.0], "end": [leg, centre],
                     "center": [leg - centre, centre], "sweep": "ccw"},
                    {"type": "line", "start": [leg, centre],
                     "end": [leg, centre + (leg - centre)]}]}}}],
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 1.0, "y": 1.0, "z": 1.0}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1}],
        "metadata": {"generator": "probe", "generator_version": "1"},
    }


def line(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 68 - len(title)))


def mesh_facts(solid, label: str) -> None:
    directory = tempfile.mkdtemp()
    name = os.path.join(directory, "part.stl")
    export_stl(solid, name)
    triangles = _parse_stl(pathlib.Path(name).read_bytes())
    open_edges, flipped = _edge_facts(triangles)
    facts = topology_of(solid)
    print(f"  {label:36} {len(triangles):6} triangles  open {open_edges:3}  "
          f"flipped {flipped:3}  solids {facts.solids}  genus {facts.genus}")


def main() -> int:  # noqa: PLR0915 - a probe is a list of measurements
    print("build123d probe -- what is left of P5, P6 and P7")

    # ------------------------------------------------------------------ P6, geometry
    line("1. P6: a sheet-metal flange, with the operations that already exist")
    # A 2 mm sheet, 60 mm wide, folded 90 degrees at an inside radius of 3 mm: a
    # rectangle carried along a path of a run, an arc and a run. Uniform thickness is
    # not checked afterwards -- it is guaranteed by construction, because the section
    # never changes.
    thickness, width, inner, leg = 2.0, 60.0, 3.0, 40.0
    centre = inner + thickness / 2          # the line the sweep follows
    bent_length = 2 * (leg - centre) + (math.pi / 2) * centre
    flange = build_part(validate_canonical(flange_document(
        thickness, width, centre, leg)))
    print(f"  volume {float(flange.volume):10.4f}   "
          f"section x length {width * thickness * bent_length:10.4f}   "
          f"diff {abs(float(flange.volume) - width * thickness * bent_length):.3e}")
    mesh_facts(flange, "a 90-degree flange, 2 mm sheet")
    print("  -> a bend is a swept rectangle and uniform thickness is a property of the")
    print("     construction rather than a check. The folded solid needs nothing new.")
    print()
    print("     Built through the engine, and that matters. The same sweep written")
    print("     straight against build123d -- `Plane(origin, z_dir=path % 0)` -- comes")
    print("     back with 140 open edges and two faces the mesher skips, because a")
    print("     60 x 2 section is as sensitive to the in-plane frame as a thread's V is")
    print("     (ADR-040's amendment). The engine is safe from it because CAD-IR makes")
    print("     the document *state* the profile's plane instead of inheriting one.")

    line("2. P6: and what the flat pattern would have to be")
    # The flat length is the neutral line's, which is where the K-factor lives:
    #     L = leg + leg + (pi/2)(r + K*t) - 2*(r + t)
    # Nothing about the *folded* solid changes with K. It is a number about the blank.
    for k in (0.33, 0.42, 0.50):
        neutral = inner + k * thickness
        flat = 2 * (leg - (inner + thickness)) + (math.pi / 2) * neutral
        print(f"  K = {k:.2f}   neutral radius {neutral:5.3f}   flat length {flat:8.4f}"
              f"   folded volume {float(flange.volume):10.4f}")
    print("  -> three blanks, one solid. A K-factor changes nothing this service can")
    print("     measure on the delivered part, which puts it exactly where a thread")
    print("     designation is: a manufacturing note only a person can catch wrong.")

    # ------------------------------------------------------------------ P7, geometry
    line("3. P7: interference between two placed bodies")
    for gap, label in ((6.0, "clear of each other"), (-4.0, "overlapping by 4 mm")):
        left = Box(20.0, 20.0, 20.0)
        right = Pos(20.0 + gap, 0, 0) * Box(20.0, 20.0, 20.0)
        common = left & right
        volume = sum(float(piece.volume) for piece in common.solids())
        print(f"  {label:22} centre distance {20.0 + gap:6.2f}   "
              f"intersection volume {volume:9.4f}")
    print("  -> an interference is an intersection volume, which is arithmetic on")
    print("     bodies the document already places. No solver, which is what ADR-022")
    print("     requires: a constraint asserts what the coordinates say, never produces")
    print("     them. A mate is therefore a stated placement plus an assertion.")

    line("4. P7: what a per-part delivery would cost")
    left = Box(20.0, 20.0, 20.0)
    right = Pos(30.0, 0, 0) * Cylinder(8.0, 20.0)
    for name, body in (("component A", left), ("component B", right)):
        mesh_facts(body, name)
    print("  -> each body already exports on its own. What P7 adds is packaging and a")
    print("     second artifact vocabulary, not geometry.")

    # ------------------------------------------------------------------ P5, the loss
    line("5. P5: what a surface costs the checks this service has")
    plate = extrude(Plane.XY * Rectangle(60.0, 40.0), 8.0)
    skin = max(plate.faces(), key=lambda f: float(f.center().Z))
    print(f"  the solid   volume {float(plate.volume):10.4f}   "
          f"solids {topology_of(plate).solids}   genus {topology_of(plate).genus}")
    try:
        print(f"  one face    area   {float(skin.area):10.4f}   volume "
              f"{float(skin.volume):10.4f}")
    except Exception as error:  # noqa: BLE001
        print(f"  one face    RAISED {type(error).__name__}: {error}")
    directory = tempfile.mkdtemp()
    name = os.path.join(directory, "skin.stl")
    try:
        export_stl(skin, name)
        triangles = _parse_stl(pathlib.Path(name).read_bytes())
        open_edges, _ = _edge_facts(triangles)
        print(f"  one face as STL   {len(triangles):4} triangles   open edges "
              f"{open_edges}")
    except Exception as error:  # noqa: BLE001
        print(f"  one face as STL   RAISED {type(error).__name__}: {error}")
    print("  -> a surface has an area and no volume, and its mesh is open by")
    print("     definition. Volume, genus, `closed_manifold_mesh`, `body_count` and")
    print("     every expectation in the contract are questions about a solid. Admitting")
    print("     surfaces means delivering a part none of them can check.")

    line("6. P5: the one surface operation that ends in a solid")
    # `thicken` is the exception: it takes a face and gives a solid, so everything
    # downstream still works. Measured, because "the API is stable" is a claim.
    try:
        from build123d import thicken

        skinned = thicken(skin, amount=3.0)
        print(f"  thicken(face, 3)   volume {float(skinned.volume):10.4f}   "
              f"expected {60.0 * 40.0 * 3.0:10.4f}")
        mesh_facts(skinned, "a thickened face")
    except Exception as error:  # noqa: BLE001
        print(f"  thicken   RAISED {type(error).__name__}: {error}")
    print("  -> and CAD-IR has no way to *state* a surface to thicken, so even this one")
    print("     needs the whole vocabulary the rest of P5 is refused for.")

    return 0


if __name__ == "__main__":  # pragma: no cover - a probe
    raise SystemExit(main())
