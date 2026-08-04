"""Fillet and chamfer, on real geometry.

POSTMVP-009. The first operations whose entire input is a selector, which changes
what the tests have to be about. A revolve that goes wrong produces a solid of the
wrong volume, and arithmetic catches it. A blend that goes wrong produces a solid
of the right volume with the round in the wrong place — so most of what is below is
about *which edges were named*, and the refusals matter more than the builds.

The volume of the fixture is arithmetic from the drawing, not from a previous run:

    60 × 40 × 10                       plate                    24 000
    − 4 × (1 − π/4) × 6² × 10          four R6 corners             309.0266
    − π × 5² × 10                      the Ø10 bore                785.3982
    − π × 24.75                        the countersink              77.7544
    − π × 22.6667                      the 2 mm deburr              71.2094
    = 22 756.6114
"""

from __future__ import annotations

import collections
import copy
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir_fixtures import fixture  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402
from conftest import pruned  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.topology import read_edges  # noqa: E402
from cad_engine_build123d.verify import Expectations, verify  # noqa: E402


PLATE = (60.0, 40.0, 10.0)
CORNER_RADIUS = 6.0
BORE_RADIUS = 5.0


def bracket() -> dict:
    return fixture("blended-bracket")


def built(value: dict):
    """`pruned` first: several tests here cut features out of the fixture or replace a
    referenced dimension with a literal, and CAD-IR 1.11 refuses a document that
    declares a dimension nothing drives. See `conftest.pruned`."""
    return build_part(validate_canonical(pruned(value)))


def feature(value: dict, name: str) -> dict:
    for item in value["features"]:
        if item["id"] == name:
            return item
    raise AssertionError(f"no feature {name} in the fixture")


def surfaces(part) -> collections.Counter:
    return collections.Counter(str(face.geom_type) for face in part.faces())


# --- the fixture -----------------------------------------------------------


def test_the_bracket_measures_what_the_drawing_says_it_should():
    part = built(bracket())
    corners = 4 * (1 - math.pi / 4) * CORNER_RADIUS**2 * PLATE[2]
    bore = math.pi * BORE_RADIUS**2 * PLATE[2]
    expected = PLATE[0] * PLATE[1] * PLATE[2] - corners - bore - math.pi * 24.75 - math.pi * (68 / 3)
    assert float(part.volume) == pytest.approx(expected, abs=1e-3)

    box = part.bounding_box().size
    # A fillet on a vertical edge and a chamfer on a bore rim both leave the
    # bounding box alone, which is exactly why the box cannot check either of them.
    assert (float(box.X), float(box.Y), float(box.Z)) == pytest.approx(PLATE, abs=1e-6)
    assert len(part.solids()) == 1


def test_the_blends_leave_the_faces_the_document_expects():
    part = built(bracket())
    counts = surfaces(part)
    assert counts["GeomType.CYLINDER"] == 5  # four R6 corners and the bore
    assert counts["GeomType.CONE"] == 2  # the countersink and the deburr chamfer
    radii = sorted(round(float(face.radius), 4) for face in part.faces()
                   if str(face.geom_type) == "GeomType.CYLINDER")
    assert radii == [5.0, 6.0, 6.0, 6.0, 6.0]


def test_the_document_and_the_reopened_files_agree():
    """Exported, reopened by a reader that did not build it, and measured."""
    document = validate_canonical(bracket())
    report = _report(build_part(document), document)
    assert report.valid, [item for item in report.checks if not item.passed]
    named = {item.name for item in report.checks}
    assert "surface_face_count[inv_corner_fillets]" in named
    assert "surface_face_count[inv_bore_chamfers]" in named


def _report(part, document):
    """Write both files and check them, the way the worker does."""
    import tempfile

    from cad_engine_build123d.adapter import _export

    directory = Path(tempfile.mkdtemp())
    _export(part, directory)
    return verify(directory / "model.step", directory / "model.stl", Expectations.of(document))


def test_a_missing_fillet_is_caught_by_nothing_but_the_face_count():
    """Turn the fillet off and the part is a plate with square corners.

    Its bounding box, body count and hole count are all still exactly what the
    document declares — a disabled feature is a legitimate document (ADR-021) and
    the point here is what the *expectations* can see. Only the face count notices.
    """
    value = bracket()
    feature(value, "feature.corners")["enabled"] = False
    document = validate_canonical(value)
    report = _report(build_part(document), document)
    failed = {item.name for item in report.checks if not item.passed}
    assert failed == {"surface_face_count[inv_corner_fillets]"}
    detail = next(item.detail for item in report.checks if not item.passed)
    assert "expected 4 cylindrical faces of radius 6.0, measured 0" in detail


def test_a_fillet_of_the_wrong_radius_is_caught_too():
    """A 4 mm round where the drawing says 6, and the part is otherwise perfect.

    Its bounding box, body count and hole count are all still right, because a
    corner fillet does not touch any of them. What is missing is four cylindrical
    faces of radius 6.
    """
    value = bracket()
    for parameter in value["parameters"]:
        if parameter["id"] == "corner_radius":
            parameter["value"] = 4.0
    document = validate_canonical(value)
    report = _report(build_part(document), document)
    failed = {item.name: item.detail for item in report.checks if not item.passed}
    assert list(failed) == ["surface_face_count[inv_corner_fillets]"]
    assert "measured 0" in failed["surface_face_count[inv_corner_fillets]"]


# --- which edges were named ------------------------------------------------


def test_convexity_tells_a_corner_from_the_root_of_a_boss():
    """The predicate that was in the contract and did nothing until 1.5.

    The lever plate is the fixture that has all four answers at once, which is why
    it is worth measuring rather than a box:

    - **concave**: the six edges where the hexagonal hub meets the plate, and the
      circle where the pin meets the hub. Seven roots, and rounding one is a
      strengthening fillet — the opposite operation from rounding a corner.
    - **convex**: everything on the outside of the part, including the rims of the
      two holes. A hole's rim being convex is the only surprise here, and it is
      right: it is a sharp outside corner, which is why chamfering one makes a
      countersink.
    - **tangent**: the four edges where the stadium's end-cap cylinders meet its
      straight sides. Smooth, so neither convex nor concave, and filleting one would
      ask the kernel to round something already round.
    - **nothing at all**: the three seams.
    """
    part = built(fixture("lever-plate"))
    edges = read_edges(part)
    found = collections.Counter(edge.convexity for edge in edges)
    assert found["concave"] == 7
    assert found["tangent"] == 4
    assert found[None] == 3
    assert found["convex"] == len(edges) - 14

    roots = [edge for edge in edges if edge.convexity == "concave"]
    assert collections.Counter(edge.curve_type for edge in roots) == {"line": 6, "circle": 1}
    # Every seam, and only a seam, has no answer.
    assert all(edge.is_seam for edge in edges if edge.convexity is None)


def test_a_seam_is_never_a_candidate():
    """OpenCascade's extra edge, and the only one that touches a single face.

    A plate with a bore has one; KOMPAS had none (ADR-023). It is not an edge of the
    part in any sense a drawing would recognise, so a selector must not be able to
    name one — and a document asking for "the straight edge of the bore" has to fail
    rather than chamfer a parametrisation artifact.
    """
    value = bracket()
    del value["features"][4]  # the countersink, whose reference face confuses nothing
    del value["features"][3]  # the deburr chamfer
    corners = feature(value, "feature.corners")
    corners["inputs"]["edges"]["cardinality"] = "exactly_one"
    corners["inputs"]["edges"]["where"] = {
        "curve_type": "line",
        "adjacent": {"contains_surface_types": ["cylindrical"], "face_count": 1},
    }
    value["expectations"] = [item for item in value["expectations"]
                             if item["id"] in ("inv_bbox", "inv_bodies")]
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "SELECTOR_NO_MATCH"
    assert "selector.corner_edges" in raised.value.safe_message


def test_a_selector_that_names_nothing_fails_with_its_narrowing():
    value = bracket()
    corners = feature(value, "feature.corners")
    corners["inputs"]["edges"]["where"]["length_mm"] = {"value": 999.0, "tolerance": 0.1}
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "SELECTOR_NO_MATCH"
    # The trace is what a repair agent reads: it says which clause emptied the set.
    assert "length_mm" in raised.value.safe_message


def test_a_count_the_part_does_not_have_is_a_refusal_rather_than_a_choice():
    """`exactly_n` is the document stating a number, so four matches is not three.

    Picking three of the four would produce a part with one square corner, which is
    the failure mode that looks like a modelling mistake and is really a selector
    quietly disagreeing with the document.
    """
    value = bracket()
    feature(value, "feature.corners")["inputs"]["edges"]["cardinality"] = {
        "type": "exactly_n",
        "value": 3,
    }
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "SELECTOR_AMBIGUOUS"


def test_a_predicate_this_engine_cannot_evaluate_is_refused_not_ignored():
    """`produced_by` needs a topology that remembers its history. OCC has none.

    Skipping it silently would leave the selector matching on its other clauses and
    taking whatever they happened to allow — which is how a fillet lands on the
    wrong edge with every stated predicate satisfied.
    """
    value = bracket()
    feature(value, "feature.corners")["inputs"]["edges"]["where"]["produced_by"] = "feature.plate"
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "SELECTOR_UNSUPPORTED_PREDICATE"
    assert "produced_by" in raised.value.safe_message


# --- what the kernel refuses ----------------------------------------------


def test_a_radius_larger_than_the_material_is_a_typed_failure():
    """A 25 mm round on a 40 mm plate: the kernel says no, and it is right.

    What matters is that it says no *with a code*. OpenCascade's own answer is a
    `ValueError` from inside the fillet algorithm, and a worker that let it through
    would report a crash where the truth is a document asking for something
    impossible.
    """
    value = bracket()
    for parameter in value["parameters"]:
        if parameter["id"] == "corner_radius":
            parameter["value"] = 25.0
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "BLEND_FAILED"
    assert raised.value.stage == "feature"
    assert "feature.corners" in raised.value.safe_message


def test_a_negative_radius_is_refused_before_the_kernel_is_asked():
    value = bracket()
    for parameter in value["parameters"]:
        if parameter["id"] == "corner_radius":
            parameter["value"] = -2.0
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "DIMENSION_OUT_OF_RANGE"


def test_a_blend_of_a_body_nothing_built_names_the_body():
    """The base extrusion turned off and the fillet left on.

    A valid document — a disabled feature is a document saying "not this one"
    (ADR-021) — and one no earlier operation could produce, because everything before
    a blend built its own geometry.

    Since CAD-IR 1.7 the refusal is more precise than it was: with bodies named, the
    problem is not "nothing exists" but "the body this selector names does not", and
    the message lists what was built instead.
    """
    value = bracket()
    value["features"] = [
        copy.deepcopy(feature(value, "feature.plate")),
        copy.deepcopy(feature(value, "feature.corners")),
    ]
    value["features"][0]["enabled"] = False
    value["features"][1]["depends_on"] = ["feature.plate"]
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "FEATURE_RESULT_UNAVAILABLE"
    assert "body.main" in raised.value.safe_message
    assert "No body has been built yet" in raised.value.safe_message


# --- the asymmetric chamfer -----------------------------------------------


def test_the_countersink_is_measured_from_the_face_the_document_names():
    """1.5 mm across the top face and 3 mm down the bore, not the other way round.

    Measured by where the cone starts: the mouth of a countersink measured 1.5 mm
    radially is Ø13, and one that took the two distances the other way round would
    be Ø16 and three times as deep.
    """
    part = built(bracket())
    cones = [face for face in part.faces() if str(face.geom_type) == "GeomType.CONE"]
    top = max(cones, key=lambda face: float(face.center().Z))
    box = top.bounding_box()
    assert float(box.size.X) == pytest.approx(2 * (BORE_RADIUS + 1.5), abs=1e-6)
    assert float(box.size.Z) == pytest.approx(3.0, abs=1e-6)


def test_a_reference_face_that_does_not_touch_the_edge_is_a_typed_failure():
    """The bottom face cannot say how far across the top one a chamfer reaches.

    build123d refuses this as well — "Some edges are not part of the face" — but as
    a bare `ValueError`. Ours names the selector, because the thing that is wrong is
    a sentence in the document.
    """
    value = bracket()
    sink = feature(value, "feature.countersink")
    sink["inputs"]["measured_from"]["where"]["normal"]["direction"] = "negative"
    sink["inputs"]["measured_from"]["where"]["position"]["extreme"] = "minimum"
    with pytest.raises(CadEngineError) as raised:
        built(value)
    assert raised.value.code == "SELECTOR_NO_MATCH"
    assert "not on that face" in raised.value.safe_message


def test_an_angle_and_a_distance_build_the_same_shape_as_two_distances():
    """The two spellings of an asymmetric chamfer, checked against each other.

    A 45° chamfer measured 3 mm across the face is the same cone as 3 mm and 3 mm,
    and the engine passes them to different kernel arguments — so if either spelling
    were wired to the wrong parameter the two volumes would differ.
    """
    two_distances = bracket()
    sink = feature(two_distances, "feature.countersink")
    sink["inputs"]["distance"] = 3.0
    sink["inputs"]["second_distance"] = 3.0

    with_angle = bracket()
    sink = feature(with_angle, "feature.countersink")
    sink["inputs"]["distance"] = 3.0
    del sink["inputs"]["second_distance"]
    sink["inputs"]["angle_deg"] = 45.0
    with_angle["parameters"] = [
        item for item in with_angle["parameters"] if item["id"] != "sink_down_bore"
    ]

    assert float(built(two_distances).volume) == pytest.approx(
        float(built(with_angle).volume), abs=1e-6
    )
