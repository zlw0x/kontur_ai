"""A misread shape is the failure no geometric check can catch.

A wrong outline compiles into a valid document, builds, and measures exactly what
it claims to measure — every expectation passes, and the part is wrong. The only
thing that can catch it is a statement about the shape made *before* the document
exists, by the stage that looked at the drawing, which the document is then
compared against.

So the tests that matter here are the ones where the document is perfectly valid
and still not the part. The ones where a claim agrees matter too, for a different
reason: a check that fires on a correct document is worse than no check, because
the repair loop will spend a run trying to fix something that was right.
"""

import json
from pathlib import Path

import pytest
from cad_ir.canonical_validator import validate_canonical
from cad_ir.shape_claim import ShapeClaim, disagreements

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir"


def document(name: str):
    return validate_canonical(json.loads((FIXTURES / name).read_text("utf-8")))


def codes(name: str, **claim) -> list[str]:
    return [item.code for item in disagreements(document(name), ShapeClaim(**claim))]


# --- the fixtures agree with what they are ---------------------------------


@pytest.mark.parametrize(
    ("name", "claim"),
    [
        ("plate.v1_9.json", {"profile": "rectangle", "thickness": "p_depth"}),
        (
            "plate-with-hole.v1_9.json",
            {
                "profile": "rectangle",
                "openings": [{"kind": "round", "count": 1}],
                "thickness": "p_depth",
            },
        ),
        (
            "constrained-plate.v1_9.json",
            {
                "profile": "rectangle",
                "openings": [{"kind": "round", "count": 2}],
                "thickness": "wall_thickness",
            },
        ),
        (
            "lever-plate.v1_9.json",
            {
                "profile": "closed_profile",
                "openings": [{"kind": "round", "count": 2}],
                "solids": 3,
            },
        ),
        (
            "bushing.v1_9.json",
            {"profile": "closed_profile", "openings": [{"kind": "profiled", "count": 1}]},
        ),
        (
            "blended-bracket.v1_9.json",
            {
                "profile": "rectangle",
                "openings": [{"kind": "round", "count": 1}],
                "thickness": "plate_thickness",
            },
        ),
    ],
)
def test_every_fixture_agrees_with_an_honest_reading_of_it(name, claim):
    assert disagreements(document(name), ShapeClaim(**claim)) == []


def test_a_blend_is_not_part_of_what_the_part_is():
    """What CAD-IR 1.5 had to decide, and the answer the vocabulary already gives.

    A fillet does not change the outline, the openings or the number of solids, so a
    claim has nothing to say about one — and the bracket, which carries a fillet and
    two chamfers, is claimed exactly as the plate it started as. Making a rounded
    corner contradict a `rectangle` claim would be the claim describing the document
    rather than the part.

    The cost is recorded rather than hidden: a fillet the drawing shows and the
    document omits is invisible to the claim. What catches that is the
    `surface_face_count` expectation, which is a statement about a measurement and
    belongs on the other side of the boundary.
    """
    value = json.loads((FIXTURES / "blended-bracket.v1_9.json").read_text("utf-8"))
    claim = ShapeClaim(
        profile="rectangle",
        openings=[{"kind": "round", "count": 1}],
        thickness="plate_thickness",
    )
    assert disagreements(validate_canonical(value), claim) == []

    without_blends = dict(value)
    without_blends["features"] = [
        feature for feature in value["features"] if not feature["type"].startswith("feature.")
    ]
    without_blends["expectations"] = [
        item for item in value["expectations"] if item["type"] != "surface_face_count"
    ]
    assert disagreements(validate_canonical(without_blends), claim) == []


def test_a_named_shape_written_the_long_way_is_still_that_shape():
    """The false positive this had on its first run.

    `constrained-plate` writes its rectangle as a four-segment path, because its
    sides need names for the constraints to reference. Refusing that would make the
    claim an instruction about how to write CAD-IR rather than a statement about
    the part.
    """
    assert codes(
        "constrained-plate.v1_9.json",
        profile="rectangle",
        openings=[{"kind": "round", "count": 2}],
    ) == []
    assert codes("plate.v1_9.json", profile="rectangle") == []


# --- and disagree with a misreading ----------------------------------------


def test_a_stadium_outline_read_as_a_rectangle_is_caught():
    """The catch the leniency above must not cost.

    Accepting a path for a named shape without looking at it would let this pass —
    which is exactly the misread the claim exists for. A rectangle is four straight
    sides; the lever plate's outline is two sides and two end caps.
    """
    found = disagreements(
        document("lever-plate.v1_9.json"),
        ShapeClaim(profile="rectangle", openings=[{"kind": "round", "count": 2}], solids=3),
    )
    assert [item.code for item in found] == ["PROFILE_KIND"]
    assert "2 straight segment(s) and 2 arc(s)" in found[0].built


def test_a_different_named_shape_is_caught_outright():
    assert codes("plate.v1_9.json", profile="circle") == ["PROFILE_KIND"]
    assert codes("plate.v1_9.json", profile="slot") == ["PROFILE_KIND"]


def test_a_hole_that_was_not_read_off_the_drawing_is_caught():
    assert codes(
        "constrained-plate.v1_9.json",
        profile="rectangle",
        openings=[{"kind": "round", "count": 3}],
    ) == ["OPENING_COUNT"]
    # And the other way: the drawing was read as having none, and the document
    # drills two.
    assert codes("constrained-plate.v1_9.json", profile="rectangle") == ["OPENING_COUNT"]


def test_an_opening_of_the_wrong_kind_is_caught():
    """Two round holes read as two slots is a document that builds the wrong part
    and passes every measurement it declares."""
    assert codes(
        "constrained-plate.v1_9.json",
        profile="rectangle",
        openings=[{"kind": "slot", "count": 2}],
    ) == ["OPENING_COUNT"]


def test_a_hole_counts_whether_it_is_an_island_or_a_cut():
    """The same hole on a drawing, two ways to write it.

    `plate-with-hole` cuts; `constrained-plate` uses islands. A claim that
    distinguished them would contradict a document that was right.
    """
    assert codes(
        "plate-with-hole.v1_9.json", profile="rectangle", openings=[{"kind": "round", "count": 1}]
    ) == []
    assert codes(
        "constrained-plate.v1_9.json",
        profile="rectangle",
        openings=[{"kind": "round", "count": 2}],
    ) == []


def test_a_boss_nobody_read_is_caught():
    assert codes(
        "lever-plate.v1_9.json",
        profile="closed_profile",
        openings=[{"kind": "round", "count": 2}],
    ) == ["SOLID_COUNT"]


def test_a_thickness_that_lost_its_name_is_caught():
    """A literal where a parameter was read is a part nobody can change later
    without editing geometry."""
    assert codes("plate.v1_9.json", profile="rectangle", thickness="p_width") == [
        "THICKNESS_PARAMETER"
    ]

    literal = json.loads((FIXTURES / "plate.v1_9.json").read_text("utf-8"))
    literal["features"][0]["inputs"]["distance"] = 10.0
    found = disagreements(
        validate_canonical(literal), ShapeClaim(profile="rectangle", thickness="p_depth")
    )
    assert [item.code for item in found] == ["THICKNESS_PARAMETER"]
    assert "lost its name" in found[0].detail


def test_a_thickness_claimed_for_a_revolve_says_so_rather_than_being_ignored():
    found = disagreements(
        document("bushing.v1_9.json"),
        ShapeClaim(
            profile="closed_profile",
            openings=[{"kind": "profiled", "count": 1}],
            thickness="bush_height",
        ),
    )
    assert [item.code for item in found] == ["THICKNESS_PARAMETER"]
    assert "not an extrusion" in found[0].detail


def test_a_claim_that_names_no_thickness_checks_nothing_about_it():
    """A reader that could not find the depth on the drawing says nothing, and
    saying nothing must not be read as saying the document is wrong."""
    assert codes("plate.v1_9.json", profile="rectangle") == []


# --- what it deliberately does not do -------------------------------------


def test_a_disabled_feature_is_not_part_of_the_shape():
    """A document saying "not this one" is not building it."""
    value = json.loads((FIXTURES / "lever-plate.v1_9.json").read_text("utf-8"))
    for feature in value["features"]:
        if feature["id"] == "feature.pin":
            feature["enabled"] = False
    assert disagreements(
        validate_canonical(value),
        ShapeClaim(
            profile="closed_profile", openings=[{"kind": "round", "count": 2}], solids=2
        ),
    ) == []


def test_nothing_measured_is_compared():
    """The claim comes from a stage that never saw a coordinate.

    Doubling every dimension leaves the part a different size and the same shape,
    and a shape claim has nothing to say about it. Checking sizes here would be the
    document checking itself — the bounding-box expectation is where a size is
    checked, against a number the drawing stated.
    """
    value = json.loads((FIXTURES / "plate.v1_9.json").read_text("utf-8"))
    for parameter in value["parameters"]:
        parameter["value"] *= 2
    assert disagreements(
        validate_canonical(value), ShapeClaim(profile="rectangle", thickness="p_depth")
    ) == []


def test_a_document_that_builds_nothing_is_named_as_such():
    value = json.loads((FIXTURES / "plate.v1_9.json").read_text("utf-8"))
    value["features"][0]["enabled"] = False
    found = disagreements(validate_canonical(value), ShapeClaim(profile="rectangle"))
    assert [item.code for item in found] == ["NO_SOLID"]


# --- how deep an opening goes ----------------------------------------------
#
# POSTMVP-016. Until the output profile offered blind cuts, every opening the cycle
# could produce went right through and a depth could not be got wrong. Now it can,
# and nothing else catches it: `through_hole_count` is written by the same stage that
# chose the depth, so it agrees with whatever that stage decided.


def plate_with(hole: dict, **extra) -> dict:
    """A 60 × 40 × 8 plate with one opening, however the document spells it."""
    return {
        "schema": "cad-ai/cad-ir",
        "schema_version": "1.9",
        "document": {"units": "mm"},
        "parameters": [
            {"id": "thickness", "type": "length", "value": 8.0, "unit": "mm",
             "status": "confirmed"}
        ],
        "features": [
            {
                "id": "feature.plate", "type": "solid.extrude", "enabled": True,
                "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "direction": "+Z", "distance": {"parameter": "thickness"},
                    "sketch": {
                        "id": "sketch.plate", "plane": {"on": "base", "plane": "XY"},
                        "outer": {"type": "rectangle", "center": [0.0, 0.0],
                                  "width": 60.0, "height": 40.0},
                        "inner": extra.get("islands", []),
                    },
                },
            },
            *([hole] if hole else []),
        ],
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 60.0, "y": 40.0, "z": 8.0}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def hole(**depth) -> dict:
    inputs = {
        "direction": "+Z",
        "source_body": {"result": "body.main"},
        "sketch": {
            "id": "sketch.hole", "plane": {"on": "base", "plane": "XY"},
            "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 5.0},
        },
        **depth,
    }
    return {"id": "feature.hole", "type": "cut.extrude", "enabled": True,
            "depends_on": ["feature.plate"], "produces": [], "inputs": inputs}


THROUGH = hole(through_all=True)
BLIND = hole(distance=3.0)


def claim_for(document: dict, **opening) -> list[str]:
    return [
        item.code
        for item in disagreements(
            validate_canonical(document),
            ShapeClaim(profile="rectangle", openings=[{"kind": "round", **opening}]),
        )
    ]


def test_a_hole_read_as_blind_agrees_with_a_document_that_stops():
    assert claim_for(plate_with(BLIND), count=1, through=False) == []


def test_a_hole_read_as_through_agrees_with_a_document_that_goes_through():
    assert claim_for(plate_with(THROUGH), count=1, through=True) == []


def test_a_blind_hole_where_the_drawing_shows_one_through_is_caught():
    """The failure the depth field exists for.

    Both documents are valid, both build, and both measure exactly what they declare —
    including their own `through_hole_count`, which the compilation stage wrote to match
    the depth it chose. The drawing is the only thing that says which was meant.
    """
    found = disagreements(
        validate_canonical(plate_with(BLIND)),
        ShapeClaim(profile="rectangle",
                   openings=[{"kind": "round", "count": 1, "through": True}]),
    )
    assert [item.code for item in found] == ["OPENING_COUNT"]
    assert "through round" in found[0].claimed
    assert "0" in found[0].built


def test_a_through_hole_where_the_drawing_shows_a_pocket_is_caught():
    found = disagreements(
        validate_canonical(plate_with(THROUGH)),
        ShapeClaim(profile="rectangle",
                   openings=[{"kind": "round", "count": 1, "through": False}]),
    )
    assert [item.code for item in found] == ["OPENING_COUNT"]
    assert "blind" in found[0].claimed


def test_a_reader_that_could_not_see_the_depth_agrees_with_either():
    """Silence is not a claim.

    The check exists for a drawing that plainly shows a pocket, not to punish a reader
    for admitting the section view did not settle it.
    """
    assert claim_for(plate_with(BLIND), count=1) == []
    assert claim_for(plate_with(THROUGH), count=1) == []


def test_an_island_in_the_profile_goes_through_by_construction():
    """A hole drawn into the base sketch is the full depth of the extrusion.

    Nothing states it, so it is read off the shape of the document rather than a field:
    an island in a solid profile cannot be a pocket.
    """
    document = plate_with(None, islands=[{"type": "circle", "center": [0.0, 0.0],
                                          "radius": 5.0}])
    assert claim_for(document, count=1, through=True) == []
    assert claim_for(document, count=1, through=False) == ["OPENING_COUNT"]


def test_a_patterned_pocket_counts_every_instance_as_blind():
    """The two checks meet: a pattern multiplies, and the depth still holds."""
    document = plate_with(BLIND)
    document["features"].append({
        "id": "feature.row", "type": "feature.pattern", "enabled": True,
        "depends_on": ["feature.hole"], "produces": [],
        "inputs": {"of": "feature.hole",
                   "pattern": {"kind": "linear", "direction": "+X",
                               "spacing_mm": 15.0, "count": 3},
                   "skip": []},
    })
    assert claim_for(document, count=3, through=False) == []
    assert claim_for(document, count=3, through=True) == ["OPENING_COUNT"]
