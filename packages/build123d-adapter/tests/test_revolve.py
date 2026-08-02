"""Revolve, on real geometry.

ENGINE-MIG-006, second half, and the first operation this service has that never
existed on KOMPAS. There is no earlier run to compare against, so every number
here is arithmetic from the drawing: a revolved annulus is π(R² − r²)h and a
partial one is that times the fraction of a turn. An engine that got the sweep
wrong would still produce a plausible solid, and only the volume would notice.

The refusals matter as much as the builds. A profile that straddles its axis
sweeps through itself, and OpenCascade's answer is `StdFail_NotDone` raised from
inside the kernel — no code, no stage, nothing about the document, and it escapes
the worker's typed-error contract as a crash. The engine has to decide before the
kernel does.
"""

from __future__ import annotations

import collections
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build, build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.topology import read_edges, read_faces  # noqa: E402
from cad_engine_build123d.verify import Expectations, verify  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "cad-ir"

#: The flanged bushing, dimension by dimension, as the fixture states it.
BORE, BODY, FLANGE = 8.0, 12.0, 18.0
FLANGE_THICKNESS, HEIGHT = 5.0, 30.0
GROOVE_FLOOR, GROOVE_LOW, GROOVE_HIGH = 11.0, 15.0, 20.0


def ring(outer: float, inner: float, height: float) -> float:
    return math.pi * (outer**2 - inner**2) * height


def bushing() -> dict:
    return json.loads((FIXTURES / "bushing.v1_8.json").read_text("utf-8"))


def document(value: dict):
    return validate_canonical(value)


# --- the fixture ----------------------------------------------------------


@pytest.fixture(scope="module")
def bush():
    return build_part(document(bushing()))


def test_the_bushing_is_one_solid_of_the_volume_the_drawing_implies(bush):
    """Flange, plus body, less the groove turned out of it."""
    expected = (
        ring(FLANGE, BORE, FLANGE_THICKNESS)
        + ring(BODY, BORE, HEIGHT - FLANGE_THICKNESS)
        - ring(BODY, GROOVE_FLOOR, GROOVE_HIGH - GROOVE_LOW)
    )
    assert len(bush.solids()) == 1
    assert float(bush.volume) == pytest.approx(expected, abs=1e-3)


def test_the_bushing_has_the_faces_a_turned_part_has(bush):
    """Five flats and five cylinders, and no more.

    The count is the check that the groove cut where it was meant to: a cut that
    missed the body would leave the wall in one piece and nine faces, and a cut
    that went through it would leave the part in two.
    """
    counted = collections.Counter(face.surface_type for face in read_faces(bush))
    assert dict(counted) == {"planar": 5, "cylindrical": 5}


def test_every_horizontal_face_is_the_annulus_the_drawing_states(bush):
    areas: dict[float, float] = collections.defaultdict(float)
    for face in read_faces(bush):
        if face.surface_type == "planar" and face.normal is not None:
            if abs(abs(face.normal[2]) - 1.0) < 1e-9:
                areas[round(face.centroid[2], 3)] += face.area_mm2

    assert areas.keys() == {0.0, FLANGE_THICKNESS, GROOVE_LOW, GROOVE_HIGH, HEIGHT}
    assert areas[0.0] == pytest.approx(ring(FLANGE, BORE, 1.0), abs=1e-3)
    assert areas[FLANGE_THICKNESS] == pytest.approx(ring(FLANGE, BODY, 1.0), abs=1e-3)
    assert areas[GROOVE_LOW] == pytest.approx(ring(BODY, GROOVE_FLOOR, 1.0), abs=1e-3)
    assert areas[GROOVE_HIGH] == pytest.approx(ring(BODY, GROOVE_FLOOR, 1.0), abs=1e-3)
    assert areas[HEIGHT] == pytest.approx(ring(BODY, BORE, 1.0), abs=1e-3)


def test_every_closed_cylinder_carries_its_seam(bush):
    """The divergence from KOMPAS, on a part made entirely of cylinders.

    Five cylindrical faces, all of them closed, so five seam edges and ten
    circles. Recorded here as well as in the parity suite because a turned part
    is where the difference is largest.
    """
    edges = read_edges(bush)
    seams = [edge for edge in edges if edge.adjacent_face_count == 1]
    assert len(seams) == 5
    assert len(edges) == 15


def test_the_bushing_exports_and_verifies(tmp_path):
    parsed = document(bushing())
    outcome = build(parsed, tmp_path)
    assert [artifact.kind for artifact in outcome.artifacts] == ["STEP", "STL"]
    report = verify(tmp_path / "model.step", tmp_path / "model.stl", Expectations.of(parsed))
    failed = [check for check in report.checks if not check.passed]
    assert report.valid, "; ".join(f"{check.name}: {check.detail}" for check in failed)
    # The bore is a through hole, and the verifier derives that from the mesh
    # rather than from the document that asked for it.
    assert report.mesh.genus == 1


# --- how far round --------------------------------------------------------


def revolved(angle: float, both: bool = False, **inputs) -> dict:
    """A plain tube, so a volume is a fraction of a turn and nothing else."""
    value = bushing()
    value["features"] = [value["features"][0]]
    feature = value["features"][0]
    feature["inputs"]["sketch"]["outer"] = {
        "type": "rectangle",
        "id": "profile.section",
        "center": [(BODY + BORE) / 2, HEIGHT / 2],
        "width": BODY - BORE,
        "height": HEIGHT,
    }
    feature["inputs"]["angle_deg"] = angle
    feature["inputs"]["both_directions"] = both
    feature["inputs"].update(inputs)
    return value


@pytest.mark.parametrize("angle", [90.0, 180.0, 270.0, 360.0])
def test_a_partial_revolve_sweeps_exactly_the_angle_it_states(angle):
    part = build_part(document(revolved(angle)))
    assert float(part.volume) == pytest.approx(
        ring(BODY, BORE, HEIGHT) * angle / 360.0, abs=1e-3
    )


def test_both_directions_sweeps_half_each_way_rather_than_twice_as_far():
    """The same solid as a one-way sweep, turned back by half the angle.

    Checked by volume and by placement: the volume says it did not sweep twice,
    and the symmetry about the plane the profile started in says it went both
    ways rather than one way with an offset.
    """
    one_way = build_part(document(revolved(90.0)))
    split = build_part(document(revolved(90.0, both=True)))

    assert float(split.volume) == pytest.approx(float(one_way.volume), abs=1e-6)

    box = split.bounding_box()
    # The profile lies in the XZ plane, so a symmetric sweep reaches as far to
    # −Y as to +Y. A one-way sweep of 90° reaches +Y only.
    assert float(box.min.Y) == pytest.approx(-float(box.max.Y), abs=1e-6)
    assert float(one_way.bounding_box().min.Y) == pytest.approx(0.0, abs=1e-6)


# --- what the engine refuses ----------------------------------------------


def crossing_profile() -> dict:
    """A section straddling x = 0: half the part would sweep through the other."""
    value = revolved(360.0)
    value["features"][0]["inputs"]["sketch"]["outer"] = {
        "type": "rectangle",
        "id": "profile.section",
        "center": [0.0, HEIGHT / 2],
        "width": 20.0,
        "height": HEIGHT,
    }
    return value


def test_a_profile_that_crosses_its_axis_is_refused_before_the_kernel_sees_it():
    with pytest.raises(CadEngineError) as refused:
        build_part(document(crossing_profile()))
    assert refused.value.code == "REVOLVE_PROFILE_CROSSES_AXIS"
    assert refused.value.stage == "feature"


def test_a_profile_that_only_touches_its_axis_is_allowed():
    """A solid shaft is drawn from the centre line outwards, and it is a part."""
    value = revolved(360.0)
    value["features"][0]["inputs"]["sketch"]["outer"] = {
        "type": "rectangle",
        "id": "profile.section",
        "center": [BODY / 2, HEIGHT / 2],
        "width": BODY,
        "height": HEIGHT,
    }
    part = build_part(document(value))
    assert float(part.volume) == pytest.approx(math.pi * BODY**2 * HEIGHT, abs=1e-3)


def test_an_arc_that_bulges_across_the_axis_is_caught_though_its_ends_are_clear():
    """The case a check on segment endpoints alone would pass.

    Both ends of the arc sit at x = 2, and the semicircle between them reaches
    x = −8. Nothing about the endpoints says so.
    """
    value = revolved(360.0)
    value["features"][0]["inputs"]["sketch"]["outer"] = {
        "type": "path",
        "id": "profile.section",
        "segments": [
            {"type": "line", "start": [2.0, 0.0], "end": [2.0, 10.0]},
            {
                "type": "arc",
                "start": [2.0, 10.0],
                "end": [2.0, 0.0],
                "center": [2.0, 5.0],
                "sweep": "ccw",
            },
        ],
    }
    with pytest.raises(CadEngineError) as refused:
        build_part(document(value))
    assert refused.value.code == "REVOLVE_PROFILE_CROSSES_AXIS"


@pytest.mark.parametrize("reach", [0.001, 1.0, 1000.0])
def test_the_verdict_does_not_depend_on_how_long_the_centre_line_is_drawn(reach):
    """A centre line is a line, not a segment: its length says nothing.

    The side of the axis a point falls on is found from a cross product, which
    scales with the axis's length. Divided by that length it is a distance, and
    the same profile gets the same answer whether the drawing's centre line is a
    micron long or a metre.
    """
    value = crossing_profile()
    value["features"][0]["inputs"]["axis"] = {
        "kind": "points",
        "axis": {"start": [0.0, 0.0], "end": [0.0, reach]},
    }
    with pytest.raises(CadEngineError) as refused:
        build_part(document(value))
    assert refused.value.code == "REVOLVE_PROFILE_CROSSES_AXIS"


def test_an_axis_whose_points_coincide_once_resolved_is_refused():
    """The contract compares the two points as written; parameters can still
    collapse them, and a zero-length axis is not an axis."""
    value = revolved(360.0)
    value["features"][0]["inputs"]["axis"] = {
        "kind": "points",
        "axis": {"start": [{"parameter": "groove_lower_z"}, 0.0], "end": [15.0, 0.0]},
    }
    with pytest.raises(CadEngineError) as refused:
        build_part(document(value))
    assert refused.value.code == "REVOLVE_AXIS_INVALID"


def test_a_cut_revolve_with_nothing_to_cut_is_refused():
    value = revolved(360.0)
    value["features"][0]["type"] = "cut.revolve"
    with pytest.raises(CadEngineError) as refused:
        build_part(document(value))
    assert refused.value.code == "UNSUPPORTED_FEATURE_SET"


def test_an_angle_named_by_a_parameter_out_of_range_is_refused_by_the_engine():
    """The contract checks a literal angle; a parameter reference reaches the
    engine unchecked, and it is the engine's business to refuse it."""
    value = revolved(360.0)
    value["parameters"].append(
        {
            "id": "sweep_angle",
            "type": "angle",
            "unit": "deg",
            "status": "confirmed",
            "value": 540.0,
        }
    )
    value["features"][0]["inputs"]["angle_deg"] = {"parameter": "sweep_angle"}
    with pytest.raises(CadEngineError) as refused:
        build_part(document(value))
    assert refused.value.code == "DIMENSION_OUT_OF_RANGE"
