"""Patterns and mirror, on real geometry.

POSTMVP-010. A pattern's whole value is that a count becomes something the document
*states* rather than something spread across six sets of coordinates — so the tests
are mostly about the count coming out right, and about the two ways it can quietly
come out wrong: an instance that landed on top of another, and an instance that never
happened.

The flange's volume is arithmetic from the drawing:

    120 × 80 × 8                       plate                    76 800
    − 4 × π × 4² × 8                   four Ø8 mounting holes    −1 608.4954
    − 6 × π × 3² × 8                   six Ø6 bolt holes         −1 357.1680
    − 2 × (π × 5² + 2 × 5 × 20) × 8    two mirrored slots        −4 456.6371
    = 69 377.6995
"""

from __future__ import annotations

import collections
import copy
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical_validator import validate_canonical  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.topology import read_faces  # noqa: E402
from cad_engine_build123d.verify import Expectations, verify  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "cad-ir"

PLATE = (120.0, 80.0, 8.0)


def flange() -> dict:
    return json.loads((FIXTURES / "patterned-flange.v1_9.json").read_text("utf-8"))


def built(value: dict):
    return build_part(validate_canonical(value))


def feature(value: dict, name: str) -> dict:
    for item in value["features"]:
        if item["id"] == name:
            return item
    raise AssertionError(f"no feature {name} in the fixture")


def radii(part) -> collections.Counter:
    return collections.Counter(
        round(float(face.radius), 3)
        for face in part.faces()
        if str(face.geom_type) == "GeomType.CYLINDER"
    )


def report(document):
    import tempfile

    from cad_engine_build123d.adapter import _export

    directory = Path(tempfile.mkdtemp())
    _export(build_part(document), directory)
    return verify(directory / "model.step", directory / "model.stl", Expectations.of(document))


# --- the fixture -----------------------------------------------------------


def test_the_flange_has_the_holes_three_patterns_should_have_made():
    """Four, six and two, from one hole, one hole and one slot."""
    part = built(flange())
    assert radii(part) == {4.0: 4, 3.0: 6, 5.0: 4}  # slot end caps come in pairs
    assert len(part.solids()) == 1

    slot = math.pi * 25 + 2 * 5 * 20
    expected = (
        PLATE[0] * PLATE[1] * PLATE[2]
        - 4 * math.pi * 16 * 8
        - 6 * math.pi * 9 * 8
        - 2 * slot * 8
    )
    assert float(part.volume) == pytest.approx(expected, abs=1e-3)


def test_a_grid_is_a_pattern_of_a_pattern():
    """Two instances crossed with two, and no third operation to test.

    The row is a linear pattern of one hole; the grid is a linear pattern of the row.
    The outer one copies everything the inner one produced, the original included,
    which is why four holes come out of two counts of two.
    """
    value = flange()
    assert feature(value, "feature.mount_grid")["inputs"]["of"] == "feature.mount_row"
    part = built(value)
    # Through the engine's own descriptors, because a hole's centre is the one thing
    # build123d's default `center()` does not give: for a cylinder it returns a point
    # *on* the surface, so a Ø8 hole at x = -50 reads as x = -54.
    corners = [
        (round(face.centroid[0], 3), round(face.centroid[1], 3))
        for face in read_faces(part)
        if face.surface_type == "cylindrical" and abs(face.radius_mm - 4.0) < 1e-6
    ]
    assert sorted(corners) == [(-50.0, -30.0), (-50.0, 30.0), (50.0, -30.0), (50.0, 30.0)]


def test_a_circular_pattern_puts_every_instance_on_the_circle():
    """Six holes at 60°, so every one of them is 25 mm from the axis."""
    bolts = [
        face
        for face in read_faces(built(flange()))
        if face.surface_type == "cylindrical" and abs(face.radius_mm - 3.0) < 1e-6
    ]
    assert len(bolts) == 6
    for face in bolts:
        assert math.hypot(face.centroid[0], face.centroid[1]) == pytest.approx(25.0, abs=1e-6)
    angles = sorted(
        round(math.degrees(math.atan2(face.centroid[1], face.centroid[0])) % 360, 3)
        for face in bolts
    )
    assert angles == [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]


def test_a_mirror_reflects_and_keeps_the_original():
    part = built(flange())
    slots = [
        face
        for face in read_faces(part)
        if face.surface_type == "cylindrical" and abs(face.radius_mm - 5.0) < 1e-6
    ]
    assert sorted({round(face.centroid[0], 3) for face in slots}) == [-45.0, 45.0]


def test_the_document_and_the_reopened_file_agree_on_every_count():
    """Twelve holes, and the expectation that says so was written by the drawing.

    A pattern is the one operation whose mistake is a *count*, and the genus of the
    mesh is a count derived by a reader that did not build it.
    """
    checked = report(validate_canonical(flange()))
    assert checked.valid, [item for item in checked.checks if not item.passed]
    assert checked.mesh.genus == 12


# --- the ways a count goes wrong -------------------------------------------


def test_a_pattern_that_repeats_one_fewer_is_caught_by_the_face_count():
    value = flange()
    feature(value, "feature.bolt_circle")["inputs"]["pattern"]["count"] = 5
    failed = {
        item.name: item.detail for item in report(validate_canonical(value)).checks
        if not item.passed
    }
    assert "surface_face_count[inv_bolt_holes]" in failed
    assert "measured 5" in failed["surface_face_count[inv_bolt_holes]"]
    # And the hole count, independently, off the mesh.
    assert "through_hole_count" in failed


def test_instances_that_coincide_collapse_and_the_geometry_cannot_tell():
    """Twelve instances 60° apart is six holes drilled twice.

    Worth knowing exactly because it is the one pattern mistake no measurement can
    catch: the part is byte-for-byte the part the document should have described, so
    the volume, the face counts and the mesh genus all agree with a document that
    asked for twice as many holes. What disagrees is the shape claim, which counts
    what the document *states* — see `test_cad_ir_pattern.py`.

    Twelve at 30° is the honest version of the same count, and it does produce twelve.
    """
    value = flange()
    bolt = feature(value, "feature.bolt_circle")["inputs"]["pattern"]
    bolt["count"] = 12
    bolt["step_deg"] = 30.0
    assert radii(built(value))[3.0] == 12

    bolt["step_deg"] = 60.0
    coincident = built(value)
    assert radii(coincident)[3.0] == 6
    # Every check passes, which is the point being recorded.
    assert report(validate_canonical(value)).valid


def test_a_skipped_instance_is_the_one_the_document_named():
    """Five of six holes, and the gap is where the document says it is."""
    value = flange()
    feature(value, "feature.bolt_circle")["inputs"]["skip"] = [3]
    part = built(value)
    angles = sorted(
        round(math.degrees(math.atan2(float(f.center().Y), float(f.center().X))) % 360)
        for f in part.faces()
        if str(f.geom_type) == "GeomType.CYLINDER" and abs(float(f.radius) - 3.0) < 1e-6
    )
    assert angles == [0, 60, 120, 240, 300]


def test_a_pattern_of_a_boss_adds_material_rather_than_removing_it():
    """A cut stays a cut and an addition stays an addition.

    The tool is a solid either way, so a pattern that lost track of which it was
    would produce lumps where the drawing shows holes — and the volume is what says
    which happened.
    """
    value = flange()
    value["features"] = [
        copy.deepcopy(feature(value, "feature.plate")),
        {
            "id": "feature.pad", "type": "solid.extrude", "enabled": True,
            "depends_on": ["feature.plate"], "produces": [],
            "inputs": {
                "direction": "+Z", "distance": 5.0,
                "sketch": {
                    "id": "sketch.pad", "plane": {"on": "datum", "plane": {"result": "plane.top"}},
                    "outer": {"type": "circle", "center": [-40.0, 0.0], "radius": 6.0},
                    "inner": [], "construction": [], "constraints": [], "dimensions": [],
                },
            },
        },
        {
            "id": "feature.pads", "type": "feature.pattern", "enabled": True,
            "depends_on": ["feature.pad"], "produces": [],
            "inputs": {
                "of": "feature.pad",
                "pattern": {"kind": "linear", "direction": "+X", "spacing_mm": 40.0, "count": 3},
                "skip": [],
            },
        },
    ]
    value["features"].insert(1, {
        "id": "feature.top_plane", "type": "datum.plane.offset", "enabled": True,
        "depends_on": ["feature.plate"],
        "produces": [{"id": "plane.top", "kind": "plane"}],
        "inputs": {"base": "XY", "offset_mm": {"parameter": "plate_thickness"}, "flip": False},
    })
    value["features"][2]["depends_on"] = ["feature.plate", "feature.top_plane"]
    value["expectations"] = [
        item for item in flange()["expectations"] if item["id"] in ("inv_bbox", "inv_bodies")
    ]
    value["expectations"][0]["size_mm"]["z"] = 13.0

    part = built(value)
    expected = PLATE[0] * PLATE[1] * PLATE[2] + 3 * math.pi * 36 * 5
    assert float(part.volume) == pytest.approx(expected, abs=1e-3)
    assert len(part.solids()) == 1


# --- what it refuses -------------------------------------------------------


def test_a_pattern_of_a_datum_plane_is_refused():
    """A plane is not material, and repeating one repeats nothing."""
    value = flange()
    value["features"].insert(1, {
        "id": "feature.helper", "type": "datum.plane.offset", "enabled": True,
        "depends_on": ["feature.plate"],
        "produces": [{"id": "plane.helper", "kind": "plane"}],
        "inputs": {"base": "XY", "offset_mm": 4.0, "flip": False},
    })
    feature(value, "feature.mount_row")["inputs"]["of"] = "feature.helper"
    feature(value, "feature.mount_row")["depends_on"] = ["feature.helper"]
    # Caught by the contract, before the engine is reached: the document can be read
    # to see that a plane is not material.
    from cad_ir.errors import CadIrValidationError

    with pytest.raises(CadIrValidationError) as raised:
        built(value)
    assert {issue.code for issue in raised.value.issues} == {"UNSUPPORTED_FEATURE_SET"}


def test_a_mirror_about_a_datum_plane_says_it_is_not_built_yet():
    """Refused rather than quietly reflected about a base plane instead.

    A mirror about the wrong plane is a part nobody can tell apart from the right one
    by reading the document, which is the whole argument for refusing.
    """
    value = flange()
    value["features"].insert(1, {
        "id": "feature.helper", "type": "datum.plane.offset", "enabled": True,
        "depends_on": ["feature.plate"],
        "produces": [{"id": "plane.helper", "kind": "plane"}],
        "inputs": {"base": "YZ", "offset_mm": 10.0, "flip": False},
    })
    mirror = feature(value, "feature.slot_mirror")
    mirror["inputs"]["pattern"] = {"kind": "mirror", "plane": {"result": "plane.helper"}}
    mirror["depends_on"] = ["feature.slot", "feature.helper"]
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "UNSUPPORTED_FEATURE"
    assert "not built yet" in raised.value.safe_message


def test_a_spacing_that_resolves_to_zero_is_refused_before_the_kernel():
    value = flange()
    for parameter in value["parameters"]:
        if parameter["id"] == "mount_pitch_x":
            parameter["value"] = 0.0
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "DIMENSION_OUT_OF_RANGE"
    assert "land on the original" in raised.value.safe_message


def test_a_pattern_with_nothing_built_yet_says_so():
    value = flange()
    value["features"] = [
        copy.deepcopy(feature(value, "feature.plate")),
        copy.deepcopy(feature(value, "feature.mount_hole")),
        copy.deepcopy(feature(value, "feature.mount_row")),
    ]
    value["features"][0]["enabled"] = False
    value["features"][1]["enabled"] = False
    value["features"][2]["enabled"] = False
    value["expectations"] = [
        item for item in flange()["expectations"] if item["id"] in ("inv_bbox", "inv_bodies")
    ]
    # Nothing enabled at all is a document that builds no solid, which is its own
    # refusal; the pattern-specific one needs the plate off and the pattern on, and
    # the canonical validator refuses that (a pattern of a disabled source). What is
    # left for the engine is the case the contract cannot see: no solid yet at all.
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "UNSUPPORTED_FEATURE_SET"
