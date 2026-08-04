"""Sweep and loft, on real geometry.

POSTMVP-018. The golden corpus builds eight of these and measures the arithmetic;
what is here is the part that cannot be a corpus case — the measurements that *justify*
the contract, kept as tests so the justification cannot rot into prose.

Four of them, and every one is a document OpenCascade builds without complaint:

- a path 30 mm from the profile builds the part at the profile anyway;
- a path at 45° sweeps the profile's projection, so a Ø16 tube 56.57 mm long comes back
  with the volume of a 40 mm one;
- a bend tighter than the profile passes through itself, reports `is_valid`, and matches
  Pappus to the last bit — only the exported mesh knows;
- two loft sections in one plane produce a closed solid of volume zero.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical import CAD_IR_VERSION  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.verify import _edge_facts, _parse_stl  # noqa: E402

RADIUS = 8.0
STRAIGHT = 50.0
BEND = 30.0


# --- documents -------------------------------------------------------------


def sketch(name: str, outer: dict, plane: dict | None = None) -> dict[str, Any]:
    return {"id": f"sketch.{name}", "plane": plane or {"on": "base", "plane": "XY"},
            "outer": outer, "inner": [], "construction": [], "constraints": [],
            "dimensions": []}


def circle(radius: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "circle", "center": list(centre), "radius": radius}


def rectangle(width: float, height: float) -> dict[str, Any]:
    return {"type": "rectangle", "center": [0.0, 0.0], "width": width, "height": height,
            "rotation_deg": 0.0}


def line(start, end) -> dict[str, Any]:
    return {"type": "line", "start": list(start), "end": list(end)}


def arc(start, end, centre, sweep: str = "cw") -> dict[str, Any]:
    return {"type": "arc", "start": list(start), "end": list(end), "center": list(centre),
            "sweep": sweep}


def spine(*segments: dict, plane: str = "XZ") -> dict[str, Any]:
    return {"id": "path.spine", "plane": plane, "segments": list(segments)}


def pipe(path: dict, outer: dict | None = None, plane: dict | None = None) -> dict[str, Any]:
    return {"id": "feature.pipe", "type": "solid.sweep", "enabled": True, "depends_on": [],
            "produces": [{"id": "body.main", "kind": "solid_body"}],
            "inputs": {"sketch": sketch("section", outer or circle(RADIUS), plane),
                       "path": path}}


def document(features: list[dict], size=(1.0, 1.0, 1.0)) -> dict[str, Any]:
    return {
        "schema": "cad-ai/cad-ir", "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "swept"},
        "parameters": [], "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": size[0], "y": size[1], "z": size[2]}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def built(value: dict):
    return build_part(validate_canonical(value))


def refusal(value: dict) -> CadEngineError:
    with pytest.raises(CadEngineError) as raised:
        built(value)
    return raised.value


# --- what the kernel does, measured ----------------------------------------


def test_the_kernel_ignores_where_the_path_is_and_anchors_it_at_the_profile():
    """Why a path must start at the origin of its own plane.

    A circle at the origin swept along a path from (30, 0, 0) comes back *at the
    origin*: OpenCascade takes the path's shape and direction and puts the sweep where
    the profile stands. So a document could state a path 30 mm away and get a part 30 mm
    from where its own coordinates say it is. CAD-IR 1.9 answers by making the path
    relative — there is no absolute position left to disagree with.
    """
    from build123d import Circle, Edge, Plane, sweep

    profile = (Plane.XY * Circle(RADIUS)).faces()[0]
    away = sweep(profile, path=Edge.make_line((30, 0, 0), (30, 0, 40)))

    assert away.bounding_box().max.X == pytest.approx(RADIUS)  # not 38
    assert float(away.volume) == pytest.approx(math.pi * RADIUS**2 * 40)

    assert refusal(document([pipe(spine(line((30.0, 0.0), (30.0, 40.0))))])).code == (
        "SWEEP_PATH_NOT_AT_ORIGIN"
    )


def test_a_path_at_an_angle_sweeps_the_profile_projected_rather_than_the_profile():
    """Why perpendicularity is required, in the number it costs.

    A Ø16 circle swept along a 45° line of length 40√2 comes back at π·8²·**40** — the
    axial height, not the distance travelled. The kernel swept a skewed prism whose true
    cross-section is 1/√2 of the circle the drawing dimensions. Volume, section and
    length are all wrong, and the document says none of it.
    """
    from build123d import Circle, Edge, Plane, sweep

    profile = (Plane.XY * Circle(RADIUS)).faces()[0]
    skewed = sweep(profile, path=Edge.make_line((0, 0, 0), (40, 0, 40)))

    travelled = 40 * math.sqrt(2)
    assert float(skewed.volume) == pytest.approx(math.pi * RADIUS**2 * 40)
    assert float(skewed.volume) != pytest.approx(math.pi * RADIUS**2 * travelled)

    error = refusal(document([pipe(spine(line((0.0, 0.0), (40.0, 40.0))))]))
    assert error.code == "SWEEP_PROFILE_NOT_PERPENDICULAR"
    assert "45.000°" in error.safe_message


def test_a_bend_tighter_than_the_profile_builds_valid_and_tears_the_mesh():
    """Why the bend check is in front of the kernel rather than left to the verifier.

    A Ø16 pipe round a 4 mm bend has its inner wall pass through itself. `is_valid` is
    `True`, the volume matches Pappus exactly, and the only thing that notices is the
    exported mesh — 69 open edges, reported as a torn STL rather than as the document
    asking for a bend it has no room for.
    """
    from build123d import Circle, Edge, Plane, Wire, export_stl, sweep

    profile = (Plane.XY * Circle(RADIUS)).faces()[0]
    up = Edge.make_line((0, 0, 0), (0, 0, 40))
    tight = Edge.make_three_point_arc(
        (0, 0, 40), (4 - 4 * math.cos(math.radians(45)), 0, 40 + 4 * math.sin(math.radians(45))),
        (4, 0, 44))
    torn = sweep(profile, path=Wire([up, tight]))

    assert torn.is_valid
    assert float(torn.volume) == pytest.approx(math.pi * RADIUS**2 * (40 + 4 * math.pi / 2))

    directory = Path(tempfile.mkdtemp())
    export_stl(torn, str(directory / "m.stl"))
    open_edges, _ = _edge_facts(_parse_stl((directory / "m.stl").read_bytes()))
    assert open_edges > 0

    error = refusal(document([pipe(spine(line((0.0, 0.0), (0.0, 40.0)),
                                         arc((0.0, 40.0), (4.0, 44.0), (4.0, 40.0))))]))
    assert error.code == "SWEEP_BEND_TIGHTER_THAN_PROFILE"


def test_two_sections_in_one_plane_loft_into_a_solid_of_no_thickness():
    """Why coplanar sections are refused rather than left to the body count.

    The result is one solid, closed, and zero. A `body_count` of 1 passes it and the
    mesh check passes it; there is nothing there.
    """
    from build123d import Plane, Rectangle, loft

    flat = loft([(Plane.XY * Rectangle(40, 40)).faces()[0],
                 (Plane.XY * Rectangle(16, 16)).faces()[0]])
    assert float(flat.volume) == pytest.approx(0.0)
    assert len(flat.solids()) == 1


# --- what the operations do ------------------------------------------------


def test_a_sweep_measures_the_area_it_carries_times_the_distance_it_travels():
    """Pappus, and it is exact — including round the bend.

    The profile's centroid sits on the path, so the distance the centroid travels *is*
    the path length. That is what makes a sweep checkable against a drawing instead of
    against a previous run.
    """
    part = built(document([pipe(spine(
        line((0.0, 0.0), (0.0, STRAIGHT)),
        arc((0.0, STRAIGHT), (BEND, STRAIGHT + BEND), (BEND, STRAIGHT))))],
        size=(BEND + RADIUS, 2 * RADIUS, STRAIGHT + BEND + RADIUS)))

    assert float(part.volume) == pytest.approx(
        math.pi * RADIUS**2 * (STRAIGHT + BEND * math.pi / 2), abs=1e-9
    )
    box = part.bounding_box()
    assert (round(box.max.X, 6), round(box.max.Z, 6)) == (BEND, STRAIGHT + BEND + RADIUS)


def test_a_bend_is_measured_against_the_profile_on_the_side_it_turns_towards():
    """An off-centre profile has two different reaches, and each bend uses its own.

    A rectangle 40 wide sitting 15 mm off the path reaches 35 mm one way and 5 mm the
    other. A 10 mm bend away from the bulk is fine; the same bend towards it is not. A
    single "circumradius" test would have refused both, which is a correct document
    turned away.
    """
    wide = {"type": "rectangle", "center": [15.0, 0.0], "width": 40.0, "height": 10.0,
            "rotation_deg": 0.0}
    # Bending towards −x, away from the bulk of the profile: reach that way is 5 mm.
    away = document([pipe(spine(line((0.0, 0.0), (0.0, 30.0)),
                                arc((0.0, 30.0), (-10.0, 40.0), (-10.0, 30.0), "ccw")),
                          outer=wide)],
                    size=(45.0, 10.0, 75.0))
    assert float(built(away).volume) > 0

    towards = document([pipe(spine(line((0.0, 0.0), (0.0, 30.0)),
                                   arc((0.0, 30.0), (10.0, 40.0), (10.0, 30.0))),
                             outer=wide)])
    assert refusal(towards).code == "SWEEP_BEND_TIGHTER_THAN_PROFILE"


def test_a_swept_cut_removes_what_it_sweeps_and_nothing_else():
    """A half-round channel across a plate: exactly half the swept cylinder is material."""
    width, depth, thickness, groove = 100.0, 60.0, 20.0, 3.0
    plate = {"id": "feature.plate", "type": "solid.extrude", "enabled": True,
             "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
             "inputs": {"sketch": sketch("plate", {"type": "rectangle",
                                                   "center": [width / 2, 0.0],
                                                   "width": width, "height": depth,
                                                   "rotation_deg": 0.0}),
                        "direction": "+Z", "distance": thickness}}
    channel = {"id": "feature.groove", "type": "cut.sweep", "enabled": True,
               "depends_on": ["feature.plate"], "produces": [],
               "inputs": {"sketch": sketch("groove", circle(groove, (0.0, thickness)),
                                           {"on": "base", "plane": "YZ"}),
                          "path": spine(line((0.0, 0.0), (width, 0.0)), plane="XY"),
                          "source_body": {"result": "body.main"}}}

    part = built(document([plate, channel], size=(width, depth, thickness)))
    assert float(part.volume) == pytest.approx(
        width * depth * thickness - math.pi * groove**2 * width / 2, abs=1e-6
    )


def test_ruled_and_smooth_are_different_parts_between_the_same_three_sections():
    """Which is why `ruled` is stated rather than defaulted at the kernel."""
    def spool(ruled: bool) -> dict[str, Any]:
        def datum(fid: str, result: str, offset: float, depends: list[str]) -> dict[str, Any]:
            return {"id": fid, "type": "datum.plane.offset", "enabled": True,
                    "depends_on": depends, "produces": [{"id": result, "kind": "plane"}],
                    "inputs": {"base": "XY", "offset_mm": offset, "flip": False}}
        return document([
            datum("feature.waist", "plane.waist", 30.0, []),
            datum("feature.top", "plane.top", 60.0, ["feature.waist"]),
            {"id": "feature.spool", "type": "solid.loft", "enabled": True,
             "depends_on": ["feature.waist", "feature.top"],
             "produces": [{"id": "body.main", "kind": "solid_body"}],
             "inputs": {"ruled": ruled, "sections": [
                 sketch("base", rectangle(40.0, 40.0)),
                 sketch("waist", rectangle(16.0, 16.0),
                        {"on": "datum", "plane": {"result": "plane.waist"}}),
                 sketch("tip", rectangle(40.0, 40.0),
                        {"on": "datum", "plane": {"result": "plane.top"}})]}},
        ], size=(40.0, 40.0, 60.0))

    straight = float(built(spool(True)).volume)
    curved = float(built(spool(False)).volume)

    # Ruled is two truncated pyramids end to end, exactly.
    prismatoid = 30.0 / 3 * (1600.0 + math.sqrt(1600.0 * 256.0) + 256.0)
    assert straight == pytest.approx(2 * prismatoid, abs=1e-6)
    assert curved != pytest.approx(straight, abs=1.0)


def test_a_loft_between_sections_in_one_plane_is_refused_by_name():
    def flat() -> dict[str, Any]:
        return document([{
            "id": "feature.taper", "type": "solid.loft", "enabled": True, "depends_on": [],
            "produces": [{"id": "body.main", "kind": "solid_body"}],
            "inputs": {"ruled": False, "sections": [sketch("base", rectangle(40.0, 40.0)),
                                                    sketch("tip", rectangle(16.0, 16.0))]},
        }])

    error = refusal(flat())
    assert error.code == "LOFT_SECTIONS_COPLANAR"
    assert "no thickness" in error.safe_message


# --- the fixture -----------------------------------------------------------


def duct() -> dict:
    from cad_ir_fixtures import fixture

    return fixture("transition-duct")


def test_the_transition_duct_is_the_arithmetic_of_its_drawing():
    """One document, both operations, and the two of them fused without a boolean.

    A square mouth lofted down to a throat, and the throat carried up and round a bend.
    The sweep names no body, so it joins the one being built — which is what a drawing
    of a duct means and why nothing here says `union`. The two share exactly the plane
    the throat sits in, so the volume is the sum of two closed forms with nothing to
    subtract.

        transition   40/3 × (60² + 60·30 + 30²)
        riser        30² × (50 + 25·π/2)
    """
    part = build_part(validate_canonical(duct()))

    transition = 40.0 / 3 * (3600.0 + math.sqrt(3600.0 * 900.0) + 900.0)
    riser = 900.0 * (50.0 + 25.0 * math.pi / 2)
    assert float(part.volume) == pytest.approx(transition + riser, abs=1e-6)
    assert len(part.solids()) == 1

    box = part.bounding_box().size
    assert (round(box.X, 6), round(box.Y, 6), round(box.Z, 6)) == (60.0, 60.0, 130.0)


def test_the_transition_duct_verifies_after_a_round_trip_through_step_and_stl():
    """Reopened and measured, and the mesh is one closed surface.

    Worth asserting on this part in particular: a sweep round a bend is where a torn
    mesh comes from, and a fused loft-and-sweep is where a body count of two would come
    from if `clean()` had left the shared face behind.
    """
    from cad_engine_build123d.adapter import _export
    from cad_engine_build123d.verify import Expectations, verify

    document = validate_canonical(duct())
    directory = Path(tempfile.mkdtemp())
    _export(build_part(document), directory)
    report = verify(directory / "model.step", directory / "model.stl",
                    Expectations.of(document))

    assert report.valid, [item for item in report.checks if not item.passed]


def test_the_topology_oracle_catches_the_tear_that_the_solid_alone_denies():
    """Two counts of one integer, and the disagreement is the finding.

    The self-intersecting sweep above is the case that makes the oracle worth having.
    Asked about it separately, each half of the delivered pair gives a confident and
    incompatible answer:

        the STEP   a tidy genus-0 solid — 4 faces, 5 edges, `is_valid` true
        the STL    genus −45, with 69 open edges

    Neither is checkable against the other by reading a document, and neither on its
    own is obviously wrong: plenty of correct parts are genus 0, and a mesh fault
    normally reads as an exporter problem. It is the *mismatch* that says the solid is
    not one, and nothing the document states is involved in noticing.

    Built through build123d directly, because the engine refuses this document before
    the kernel sees it (`SWEEP_BEND_TIGHTER_THAN_PROFILE`) — the oracle is the second
    line, for the tear nobody predicted.
    """
    from build123d import Circle, Edge, Plane, Wire, sweep

    from cad_engine_build123d.adapter import _export
    from cad_engine_build123d.verify import Expectations, topology_of, verify

    profile = (Plane.XY * Circle(RADIUS)).faces()[0]
    torn = sweep(profile, path=Wire([
        Edge.make_line((0, 0, 0), (0, 0, 40)),
        Edge.make_three_point_arc(
            (0, 0, 40),
            (4 - 4 * math.cos(math.radians(45)), 0, 40 + 4 * math.sin(math.radians(45))),
            (4, 0, 44)),
    ]))

    facts = topology_of(torn)
    assert facts.genus == 0  # the B-rep is sure the part is fine

    directory = Path(tempfile.mkdtemp())
    _export(torn, directory)
    report = verify(directory / "model.step", directory / "model.stl", Expectations())

    failed = {item.name for item in report.checks if not item.passed}
    assert "topology_agrees_with_mesh" in failed
    assert report.brep is not None and report.brep.genus == 0
    assert report.mesh is not None and report.mesh.genus != 0
