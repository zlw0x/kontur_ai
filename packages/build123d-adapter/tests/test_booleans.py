"""More than one body, and the booleans between them.

POSTMVP-012. The point of the milestone is that a body is a *named* thing: created by
name, targeted by name, combined by name. So the tests are about which body a feature
touched, and the ones that matter most are where there are two bodies and only one
should have changed.

The bracket's volume is arithmetic from the drawing:

    80 × 40 × 10                 the plate                        32 000
    + 20 × 20 × 10               the rib's half outside the plate  +4 000
    − π × 8² × 10                the bore punched through it       −2 010.6193
    + π × 8² × 24                the stud, kept as its own body    +4 825.4862
    = 38 814.8670
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical import CAD_IR_VERSION  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.verify import Expectations, verify  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "cad-ir"


def bracket() -> dict:
    return json.loads((FIXTURES / "boolean-bracket.v1_11.json").read_text("utf-8"))


def built(value: dict):
    return build_part(validate_canonical(value))


def feature(value: dict, name: str) -> dict:
    for item in value["features"]:
        if item["id"] == name:
            return item
    raise AssertionError(f"no feature {name}")


def report(document):
    import tempfile

    from cad_engine_build123d.adapter import _export

    directory = Path(tempfile.mkdtemp())
    _export(build_part(document), directory)
    return verify(directory / "model.step", directory / "model.stl", Expectations.of(document))


STUD = math.pi * 64 * 24
BORE = math.pi * 64 * 10


# --- the fixture -----------------------------------------------------------


def test_the_bracket_is_two_bodies_of_the_volume_the_drawing_implies():
    part = built(bracket())
    assert len(part.solids()) == 2
    expected = 80 * 40 * 10 + 20 * 20 * 10 - BORE + STUD
    assert float(part.volume) == pytest.approx(expected, abs=1e-3)


def test_the_delivered_step_carries_both_bodies():
    """Two solids in one file, and the verifier counts them.

    A compound rather than a fused solid: bodies that were never combined are separate
    on purpose, and fusing them at export time would be the engine overruling the
    document.
    """
    document = validate_canonical(bracket())
    checked = report(document)
    assert checked.valid, [item for item in checked.checks if not item.passed]
    counted = next(item for item in checked.checks if item.name == "solid_body_count")
    assert "measured 2" in counted.detail


def test_the_multi_body_mesh_still_counts_its_through_holes():
    """Euler's formula needs the component count once a part has two bodies.

    With `c` assumed to be 1, two lumps with a single through hole between them read as
    genus 0 — a hole the document declared and the mesh could not find. Nothing about
    the geometry changed; the arithmetic had a wrong constant in it.
    """
    assert report(validate_canonical(bracket())).mesh.genus == 1


def test_two_bodies_with_no_holes_are_genus_zero():
    """The version of the same check that would have gone negative."""
    value = bracket()
    value["features"] = [
        copy.deepcopy(feature(value, "feature.plate")),
        copy.deepcopy(feature(value, "feature.stud")),
    ]
    value["expectations"] = [
        {"id": "inv_bbox", "type": "bounding_box",
         "size_mm": {"x": 80.0, "y": 128.0, "z": 24.0}, "tolerance_mm": 0.05},
        {"id": "inv_bodies", "type": "body_count", "value": 2},
        {"id": "inv_holes", "type": "through_hole_count", "value": 0},
    ]
    checked = report(validate_canonical(value))
    assert checked.mesh.genus == 0
    assert checked.valid, [item for item in checked.checks if not item.passed]


# --- which body was touched ------------------------------------------------


def test_a_united_tool_stops_being_a_body_of_its_own():
    """The rib is welded on, so the part has the plate and the stud and no rib."""
    part = built(bracket())
    volumes = sorted(round(float(solid.volume), 3) for solid in part.solids())
    assert volumes == [round(STUD, 3), round(32000 + 4000 - BORE, 3)]


def test_a_kept_tool_stays_a_body():
    value = bracket()
    feature(value, "feature.bore")["inputs"]["keep_tools"] = True
    part = built(value)
    # The plate, the stud, and now the punch as well.
    assert len(part.solids()) == 3


def test_a_dropped_tool_is_gone_and_a_later_selector_cannot_name_it():
    """A name is never reused, and a consumed body's name resolves to nothing.

    The alternative — a stale name falling through to whatever body took its place —
    is how a fillet lands on the wrong lump of metal.
    """
    value = bracket()
    value["features"].append({
        "id": "feature.round", "type": "feature.fillet", "enabled": True,
        "depends_on": ["feature.bore"], "produces": [],
        "inputs": {
            "edges": {
                "id": "selector.gone", "kind": "edge", "from_result": "body.punch",
                "cardinality": "one_or_more",
                "where": {"curve_type": "circle"},
            },
            "radius": 1.0,
        },
    })
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "FEATURE_RESULT_UNAVAILABLE"
    assert "body.punch" in raised.value.safe_message
    assert "body.main" in raised.value.safe_message  # what *does* exist


def test_a_cut_reaches_only_the_body_it_names():
    """Two bodies, one cut, and the other body untouched.

    Before 1.7 every cut removed material from the single running solid, so a document
    with `source_body` was believed rather than obeyed. The stud is where that shows:
    the cut passes straight through where it stands and leaves it alone.
    """
    value = bracket()
    value["parameters"].append(
        {"id": "slit_width", "type": "length", "unit": "mm", "value": 4.0,
         "status": "confirmed", "name": "Slit width"}
    )
    value["features"].append({
        "id": "feature.slit", "type": "cut.extrude", "enabled": True,
        "depends_on": ["feature.plate", "feature.bore"], "produces": [],
        "inputs": {
            "direction": "+Z", "through_all": True,
            "source_body": {"result": "body.main"},
            "sketch": {
                "id": "sketch.slit", "plane": {"on": "base", "plane": "XY"},
                "outer": {"type": "rectangle", "center": [0.0, 100.0], "width": 4.0,
                          "height": 200.0, "rotation_deg": 0.0},
                "inner": [], "construction": [], "constraints": [], "dimensions": [],
            },
        },
    })
    part = built(value)
    stud = min(part.solids(), key=lambda solid: float(solid.volume))
    # The slit runs right through the stud's footprint and the stud is whole.
    assert float(stud.volume) == pytest.approx(STUD, abs=1e-3)


def test_a_blend_reaches_only_the_body_its_selector_names():
    value = bracket()
    value["features"].append({
        "id": "feature.round_stud", "type": "feature.fillet", "enabled": True,
        "depends_on": ["feature.stud"], "produces": [],
        "inputs": {
            "edges": {
                "id": "selector.stud_rim", "kind": "edge", "from_result": "body.stud",
                "cardinality": {"type": "exactly_n", "value": 2},
                "where": {"curve_type": "circle", "convexity": "convex"},
            },
            "radius": 2.0,
        },
    })
    part = built(value)
    stud = min(part.solids(), key=lambda solid: float(solid.volume))
    plate = max(part.solids(), key=lambda solid: float(solid.volume))
    assert float(stud.volume) < STUD  # rounded, so smaller
    assert float(plate.volume) == pytest.approx(32000 + 4000 - BORE, abs=1e-3)


# --- the three operations --------------------------------------------------


def test_an_intersection_keeps_only_what_both_bodies_occupy():
    """The operation the fixture does not use, on two overlapping blocks."""
    value = _two_blocks("intersect")
    part = built(value)
    assert len(part.solids()) == 1
    # 40 × 40 × 10 overlapping a block offset 20 in x: a 20 × 40 × 10 lens.
    assert float(part.volume) == pytest.approx(20 * 40 * 10, abs=1e-6)


def test_an_intersection_of_bodies_that_do_not_touch_is_refused():
    """The kernel returns an empty shape rather than failing.

    A document that meant something else would otherwise get a part with a body of no
    volume in it, which passes `body_count` and fails nothing.
    """
    value = _two_blocks("intersect", offset=200.0)
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "BOOLEAN_EMPTY"
    assert "do not overlap" in raised.value.safe_message


def test_a_subtraction_that_removes_everything_is_refused():
    value = _two_blocks("subtract", offset=0.0, tool_size=60.0)
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "BOOLEAN_EMPTY"


def _two_blocks(op: str, offset: float = 20.0, tool_size: float = 40.0) -> dict:
    """Two overlapping blocks and one boolean between them."""
    def block(fid: str, body: str, centre: float, size: float, deps: list[str]) -> dict:
        inputs = {
            "direction": "+Z", "distance": 10.0,
            "sketch": {
                "id": f"sketch.{body.split('.')[-1]}", "plane": {"on": "base", "plane": "XY"},
                "outer": {"type": "rectangle", "center": [centre, 0.0], "width": size,
                          "height": 40.0, "rotation_deg": 0.0},
                "inner": [], "construction": [], "constraints": [], "dimensions": [],
            },
        }
        if deps:
            inputs["new_body"] = True
        return {
            "id": fid, "type": "solid.extrude", "enabled": True, "depends_on": deps,
            "produces": [{"id": body, "kind": "solid_body"}], "inputs": inputs,
        }

    return {
        "schema": "cad-ai/cad-ir",
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm"},
        "parameters": [],
        "features": [
            block("feature.first", "body.first", 0.0, 40.0, []),
            block("feature.second", "body.second", offset, tool_size, ["feature.first"]),
            {
                "id": "feature.combine", "type": "feature.boolean", "enabled": True,
                "depends_on": ["feature.first", "feature.second"], "produces": [],
                "inputs": {"op": op, "target": {"result": "body.first"},
                           "tools": [{"result": "body.second"}], "keep_tools": False},
            },
        ],
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 40.0, "y": 40.0, "z": 10.0}, "tolerance_mm": 100.0},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def test_a_boolean_naming_a_body_nothing_built_says_what_does_exist():
    value = bracket()
    feature(value, "feature.weld_rib")["inputs"]["tools"] = [{"result": "body.rib"}]
    feature(value, "feature.rib")["enabled"] = False
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "FEATURE_RESULT_UNAVAILABLE"
    assert "Bodies so far" in raised.value.safe_message
