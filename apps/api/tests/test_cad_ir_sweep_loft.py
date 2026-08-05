"""CAD-IR 1.9: a profile that travels, and the material between sections.

Two operations in one version because they are one question asked twice: given a
profile, what carries it? A path, or the next profile along.

Each has a rule that is the operation's whole content, and both are here rather than in
the engine because both are about the document rather than about geometry:

- a loft's sections are the same kind of contour with the same number of vertices, so
  the correspondence between them is decided by the shapes rather than by the kernel;
- a sweep's path is stated *from* the profile, which is why it has no `distance` — how
  far the material goes is the path, said once.

Everything about where the path is and which way it leaves belongs to the engine, and
is checked there against the coordinates the document states (ADR-031).
"""

import pytest
from pydantic import ValidationError

from cad_ir.canonical import CAD_IR_SCHEMA, CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError
from cad_ir.loft import CutLoftInputs, LoftInputs
from cad_ir.shape_claim import OpeningClaim, ProfileKind, ShapeClaim, disagreements
from cad_ir.sweep import CutSweepInputs, SweepInputs, SweepPath


def sketch(name: str, outer: dict, plane: dict | None = None) -> dict:
    return {"id": f"sketch.{name}", "plane": plane or {"on": "base", "plane": "XY"},
            "outer": outer, "inner": [], "construction": [], "constraints": [],
            "dimensions": []}


def circle(radius: float) -> dict:
    return {"type": "circle", "center": [0.0, 0.0], "radius": radius}


def rectangle(side: float) -> dict:
    return {"type": "rectangle", "center": [0.0, 0.0], "width": side, "height": side,
            "rotation_deg": 0.0}


def polygon(sides: int) -> dict:
    return {"type": "regular_polygon", "center": [0.0, 0.0], "sides": sides,
            "circumradius": 20.0, "rotation_deg": 0.0}


STRAIGHT = {"id": "path.spine", "plane": "XZ",
            "segments": [{"type": "line", "start": [0.0, 0.0], "end": [0.0, 40.0]}]}


def swept(cut_from: str | None = None, depends: list[str] | None = None) -> dict:
    inputs: dict = {"sketch": sketch("section", circle(8.0)), "path": STRAIGHT}
    if cut_from:
        inputs["source_body"] = {"result": cut_from}
    return {"id": "feature.pipe", "type": "cut.sweep" if cut_from else "solid.sweep",
            "enabled": True, "depends_on": depends or [],
            "produces": [] if cut_from else [{"id": "body.main", "kind": "solid_body"}],
            "inputs": inputs}


DATUM = {"id": "feature.top", "type": "datum.plane.offset", "enabled": True,
         "depends_on": [], "produces": [{"id": "plane.top", "kind": "plane"}],
         "inputs": {"base": "XY", "offset_mm": 30.0, "flip": False}}
ON_TOP = {"on": "datum", "plane": {"result": "plane.top"}}


def lofted(sections: list[dict], ruled: bool = False) -> dict:
    return {"id": "feature.taper", "type": "solid.loft", "enabled": True,
            "depends_on": ["feature.top"],
            "produces": [{"id": "body.main", "kind": "solid_body"}],
            "inputs": {"sections": sections, "ruled": ruled}}


def document(features: list[dict]) -> dict:
    return {
        "schema": CAD_IR_SCHEMA, "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "travelled"},
        "parameters": [], "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 40.0, "y": 40.0, "z": 40.0}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def codes(value: dict) -> set[str]:
    with pytest.raises(CadIrValidationError) as raised:
        validate_canonical(value)
    return {issue.code for issue in raised.value.issues}


# --- sweep -----------------------------------------------------------------


def test_a_sweep_is_a_document_the_contract_accepts():
    parsed = validate_canonical(document([swept()]))

    assert str(parsed.features[0].inputs.path.plane) == "XZ"
    assert len(parsed.features[0].inputs.path.segments) == 1


def test_a_path_needs_at_least_one_segment():
    with pytest.raises(ValidationError):
        SweepPath(id="path.empty", plane="XZ", segments=[])


def test_a_sweep_states_no_distance_because_the_path_already_did():
    """How far the material goes is the path's own length, said once.

    A `distance` beside it would be a second way to say the same thing, and two ways to
    say one thing is one way for them to disagree.
    """
    assert "distance" not in SweepInputs.model_fields
    assert "distance" not in CutSweepInputs.model_fields
    assert "through_all" not in CutSweepInputs.model_fields


def test_a_swept_cut_names_the_body_it_cuts_and_starts_no_new_one():
    assert "new_body" in SweepInputs.model_fields
    assert "new_body" not in CutSweepInputs.model_fields


def test_a_sweep_cannot_both_start_a_body_and_add_to_one():
    with pytest.raises(ValidationError):
        SweepInputs(sketch=sketch("s", circle(8.0)), path=STRAIGHT, new_body=True,
                    source_body={"result": "body.main"})


def test_a_swept_cut_of_a_body_no_feature_builds_is_refused():
    assert "FEATURE_RESULT_UNAVAILABLE" in codes(document([swept(cut_from="body.absent")]))


# --- loft ------------------------------------------------------------------


def test_a_loft_between_two_sections_of_a_kind_is_accepted():
    parsed = validate_canonical(document([
        DATUM, lofted([sketch("base", circle(20.0)), sketch("tip", circle(8.0), ON_TOP)])]))

    assert len(parsed.features[1].inputs.sections) == 2
    assert parsed.features[1].inputs.ruled is False


def test_a_loft_needs_two_sections():
    with pytest.raises(ValidationError):
        LoftInputs(sections=[sketch("only", circle(20.0))])


@pytest.mark.parametrize(
    "first,second",
    [
        (circle(20.0), rectangle(20.0)),
        (rectangle(20.0), polygon(6)),
        (polygon(6), polygon(8)),
    ],
    ids=["round-to-square", "square-to-hexagon", "hexagon-to-octagon"],
)
def test_a_loft_refuses_sections_whose_correspondence_the_kernel_would_have_to_invent(
    first, second
):
    """The rule that carries the operation.

    The kernel always has an answer to "which point of this section meets which of
    that one" and never says what it was. A hexagon lofted into an octagon is a solid
    of plausible volume with two vertices fused somewhere nobody chose. So the sections
    have to be the same kind with the same count, and then the shapes decide.
    """
    with pytest.raises(ValidationError):
        LoftInputs(sections=[sketch("a", first), sketch("b", second, ON_TOP)])
    with pytest.raises(ValidationError):
        CutLoftInputs(sections=[sketch("a", first), sketch("b", second, ON_TOP)])

    assert "SCHEMA_INVALID" in codes(document([
        DATUM, lofted([sketch("a", first), sketch("b", second, ON_TOP)])]))


def test_a_loft_between_polygons_of_the_same_count_is_accepted():
    LoftInputs(sections=[sketch("a", polygon(6)), sketch("b", polygon(6), ON_TOP)])


def test_a_loft_refuses_a_section_with_an_island():
    """A hole in a section is a second correspondence nobody stated."""
    holed = {**sketch("a", circle(20.0)), "inner": [circle(5.0)]}
    with pytest.raises(ValidationError) as raised:
        LoftInputs(sections=[holed, sketch("b", circle(8.0), ON_TOP)])
    assert "island" in str(raised.value)


def test_a_loft_of_spelled_out_contours_matches_on_the_number_of_segments():
    def path_contour(segments: int) -> dict:
        points = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (10.0, 25.0)]
        used = points[:segments]
        return {"type": "path", "segments": [
            {"type": "line", "start": list(used[i]), "end": list(used[(i + 1) % len(used)])}
            for i in range(len(used))
        ]}

    LoftInputs(sections=[sketch("a", path_contour(4)), sketch("b", path_contour(4), ON_TOP)])
    with pytest.raises(ValidationError):
        LoftInputs(sections=[sketch("a", path_contour(4)),
                             sketch("b", path_contour(5), ON_TOP)])


# --- what they mean for the claim ------------------------------------------


def test_a_swept_solid_is_a_lump_of_material_the_claim_counts():
    """A reader counts lumps, not operations, so a sweep is one of them.

    Missing from that list, a new solid-making operation makes the claim quietly stop
    counting — a document with two swept bosses would satisfy a claim of one solid.
    """
    found = disagreements(
        validate_canonical(document([swept()])),
        ShapeClaim(profile=ProfileKind.CIRCLE, openings=[], solids=1),
    )
    assert found == []

    wrong = disagreements(
        validate_canonical(document([swept()])),
        ShapeClaim(profile=ProfileKind.CIRCLE, openings=[], solids=2),
    )
    assert [item.code for item in wrong] == ["SOLID_COUNT"]


def test_a_swept_cut_is_an_opening_the_claim_counts():
    value = document([
        {"id": "feature.block", "type": "solid.extrude", "enabled": True, "depends_on": [],
         "produces": [{"id": "body.main", "kind": "solid_body"}],
         "inputs": {"sketch": sketch("block", rectangle(60.0)), "direction": "+Z",
                    "distance": 20.0}},
        swept(cut_from="body.main", depends=["feature.block"]),
    ])
    stated = ShapeClaim(profile=ProfileKind.RECTANGLE,
                        openings=[OpeningClaim(kind="round", count=1)], solids=1)

    assert disagreements(validate_canonical(value), stated) == []


def test_a_lofts_outline_is_the_kind_every_one_of_its_sections_is():
    """Which is only true because mixed sections are refused, and that is the point.

    Had a round-to-square loft been allowed, a claim of `circle` would have been
    satisfied by a solid that ends as a square, and the claim would have said something
    about half a part.
    """
    value = document([DATUM, lofted([sketch("base", circle(20.0)),
                                     sketch("tip", circle(8.0), ON_TOP)])])

    assert disagreements(
        validate_canonical(value),
        ShapeClaim(profile=ProfileKind.CIRCLE, openings=[], solids=1),
    ) == []
    assert [item.code for item in disagreements(
        validate_canonical(value),
        ShapeClaim(profile=ProfileKind.RECTANGLE, openings=[], solids=1),
    )] == ["PROFILE_KIND"]


def test_neither_has_an_extrusion_thickness_for_a_claim_to_name():
    """A claim that names a thickness for a swept part has read the wrong drawing.

    Saying so is more useful than ignoring the field: a part with no extrusion has no
    dimension the word `thickness` refers to.
    """
    found = disagreements(
        validate_canonical(document([swept()])),
        ShapeClaim(profile=ProfileKind.CIRCLE, openings=[], solids=1, thickness="p_depth"),
    )
    assert [item.code for item in found] == ["THICKNESS_PARAMETER"]


# --- the rotation a section cannot record ----------------------------------
#
# The half of Gate P4 that ADR-031's kind-and-count rule left open. Measured on the
# engine before the rule was written, lofting a 40 x 40 square 30 mm to another
# 40 x 40 square:
#
#     0°   48 000.0000   a prism
#    15°   47 454.8132   a twist
#    45°   43 313.7085   a twist
#    90°   48 000.0000   a prism, and the document said a quarter turn
#
# Nothing is wrong with the kernel. A square turned 90° is the same set of points, so
# both readings fit the sections as stated and it picks one.


def square(side: float, rotation: float = 0.0) -> dict:
    return {"type": "rectangle", "center": [0.0, 0.0], "width": side, "height": side,
            "rotation_deg": rotation}


def oblong(width: float, height: float, rotation: float = 0.0) -> dict:
    return {"type": "rectangle", "center": [0.0, 0.0], "width": width, "height": height,
            "rotation_deg": rotation}


def turned(first: dict, second: dict) -> LoftInputs:
    return LoftInputs(sections=[sketch("a", first), sketch("b", second, ON_TOP)])


@pytest.mark.parametrize("rotation", [0.0, 15.0, 45.0, 89.9])
def test_a_rotation_inside_the_contours_symmetry_is_a_twist_the_sections_record(rotation):
    """Under a quarter turn, the two vertex sets differ and the pairing is decided."""
    turned(square(40.0), square(40.0, rotation))


@pytest.mark.parametrize("rotation", [90.0, 135.0, 180.0, 270.0])
def test_a_rotation_of_a_whole_symmetry_or_more_is_refused(rotation):
    """At and beyond the symmetry, the sections cannot say which of two solids is meant.

    90° and 180° are the same vertex set as 0°; 135° is the same as 45°. In every case
    the document states one rotation and the sections record another, so the kernel is
    left choosing — and it chooses silently.
    """
    with pytest.raises(ValidationError):
        turned(square(40.0), square(40.0, rotation))


def test_the_symmetry_is_the_contours_own_and_not_a_constant():
    """A square repeats every quarter turn; an oblong every half; a hexagon every 60°.

    An oblong turned 90° is a genuinely different pair of sections — it is the case a
    single constant would have refused wrongly.
    """
    turned(oblong(40.0, 20.0), oblong(40.0, 20.0, 90.0))
    with pytest.raises(ValidationError):
        turned(oblong(40.0, 20.0), oblong(40.0, 20.0, 180.0))

    turned(polygon(6), {**polygon(6), "rotation_deg": 30.0})
    with pytest.raises(ValidationError):
        turned(polygon(6), {**polygon(6), "rotation_deg": 60.0})


def test_a_contour_with_no_vertices_to_pair_is_not_affected():
    """A circle has no corners, so there is no correspondence to be undecided about."""
    LoftInputs(sections=[sketch("a", circle(20.0)), sketch("b", circle(8.0), ON_TOP)])


def test_a_rotation_stated_as_a_parameter_is_left_alone():
    """The check is arithmetic on numbers the document states.

    A rotation given as a name is a number this module never sees, and guessing at it
    would refuse documents on the strength of a value nobody here read.
    """
    LoftInputs(sections=[
        sketch("a", square(40.0)),
        sketch("b", {**square(40.0), "rotation_deg": {"parameter": "p_turn"}}, ON_TOP),
    ])
