"""The narrowed schema Codex is constrained to must stay a subset.

Two schemas describe CAD-IR: the canonical one, which says what the version
can express, and the output profile, which says what may be generated. If the profile ever accepted something the canonical model
rejects, Codex would be told to produce documents the trusted validator then
refuses — a repair loop caused entirely by our own schemas disagreeing.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cad_ir.canonical import CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical
from cad_ir.errors import CadIrValidationError

ROOT = Path(__file__).parents[3]
PROFILE = json.loads((ROOT / "schemas" / "cad-ir-mvp-output.schema.json").read_text(encoding="utf-8"))
FIXTURES = ROOT / "tests" / "fixtures" / "cad-ir"


@pytest.fixture(scope="module")
def profile() -> Draft202012Validator:
    Draft202012Validator.check_schema(PROFILE)
    return Draft202012Validator(PROFILE)


def canonical_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.v1_7.json").read_text(encoding="utf-8"))


def profile_shaped_document() -> dict:
    """A document exactly as the profile demands it: every listed property
    present, because strict mode has no optional ones."""
    return {
        "schema": "cad-ai/cad-ir",
        "schema_version": CAD_IR_VERSION,
        "document": {
            "units": "mm",
            "part_type": "single_part",
            "coordinate_system": "right_handed",
            "name": "plate",
        },
        "reference_geometry": [],
        "parameters": [
            {
                "id": "param.width",
                "type": "length",
                "value": 60.0,
                "unit": "mm",
                "name": "Width",
                "status": "confirmed",
                "provenance": {"confidence": 0.98},
            },
            {
                "id": "param.radius",
                "type": "length",
                "value": 2.5,
                "unit": "mm",
                "name": "Hole radius",
                "status": "confirmed",
                "provenance": {"confidence": 0.95},
            },
        ],
        "features": [
            {
                "id": "feature.base",
                "type": "solid.extrude",
                "enabled": True,
                "depends_on": [],
                "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "direction": "+Z",
                    "distance": 8.0,
                    "sketch": {
                        "id": "sketch.base",
                        "plane": {"on": "base", "plane": "XY"},
                        "outer": {
                            "type": "rectangle",
                            "center": [0.0, 0.0],
                            "width": {"parameter": "param.width"},
                            "height": 30.0,
                            "rotation_deg": 0.0,
                        },
                        "inner": [],
                        "construction": [],
                        "constraints": [],
                        "dimensions": [],
                    },
                },
            },
            {
                "id": "feature.hole",
                "type": "cut.extrude",
                "enabled": True,
                "depends_on": ["feature.base"],
                "produces": [],
                "inputs": {
                    "direction": "+Z",
                    "through_all": True,
                    "source_body": {"result": "body.main"},
                    "sketch": {
                        "id": "sketch.hole",
                        "plane": {"on": "base", "plane": "XY"},
                        "outer": {
                            "type": "circle",
                            "center": [-15.0, 0.0],
                            "radius": {"parameter": "param.radius"},
                        },
                        "inner": [],
                        "construction": [],
                        "constraints": [],
                        "dimensions": [],
                    },
                },
            },
        ],
        "expectations": [
            {
                "id": "expect.bounds",
                "type": "bounding_box",
                "size_mm": {"x": 60.0, "y": 30.0, "z": 8.0},
                "tolerance_mm": 0.05,
            },
            {"id": "expect.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {
            "generator": "drawing-agent",
            "generator_version": "0.4.0",
            "prompt_version": "drawing-mvp-2",
        },
    }


def test_a_document_shaped_by_the_profile_is_canonically_valid(profile):
    """The direction that matters. If the profile accepted something the
    canonical validator rejects, Codex would be told to produce documents the
    trusted gate then refuses — a repair loop caused by our own schemas
    disagreeing with each other."""
    document = profile_shaped_document()

    assert list(profile.iter_errors(document)) == []
    assert validate_canonical(document).schema_version == CAD_IR_VERSION


@pytest.mark.parametrize("name", ["plate", "plate-with-hole"])
def test_the_normalizer_output_is_canonically_valid(name):
    """The normalizer produces canonical documents, not profile-shaped ones:
    the profile constrains generation, and a migrated 0.1.0 document was never
    generated."""
    assert validate_canonical(canonical_fixture(name)).schema_version == CAD_IR_VERSION


def test_the_profile_declares_the_same_version_as_the_canonical_schema():
    assert PROFILE["properties"]["schema_version"]["const"] == CAD_IR_VERSION
    assert PROFILE["properties"]["schema"]["const"] == "cad-ai/cad-ir"


@pytest.mark.parametrize("mutation", [("plane", "XZ"), ("direction", "-Z")])
def test_the_profile_is_narrower_than_the_canonical_model(profile, mutation):
    """The canonical model allows three base planes and six directions because
    a later version will need them. The profile allows one of each, so Codex is
    never asked for geometry this adapter cannot build."""
    key, value = mutation
    document = profile_shaped_document()
    inputs = document["features"][0]["inputs"]
    if key == "plane":
        inputs["sketch"]["plane"] = {"on": "base", "plane": value}
    else:
        inputs["direction"] = value

    assert validate_canonical(document).schema_version == CAD_IR_VERSION
    assert list(profile.iter_errors(document)) != []


def test_the_profile_rejects_an_expression(profile):
    document = profile_shaped_document()
    document["features"][0]["inputs"]["distance"] = {"expr": "param.width * 2"}

    assert list(profile.iter_errors(document)) != []
    with pytest.raises(CadIrValidationError):
        validate_canonical(document)


# --- what the profile grew, and why each addition is safe ------------------
#
# POSTMVP-016. Everything below is a shape the *engine* has built since its own
# milestone and the *cycle* could not ask for, because the output profile offered
# one plate on XY with holes through it. Each is offered now for the same reason:
# every one of its fields is mandatory, so the dialect can state it without forcing
# the model to invent a value the canonical validator then refuses.


def with_features(*features: dict, **overrides) -> dict:
    """The profile-shaped document, with its feature list replaced."""
    document = profile_shaped_document()
    document["features"] = list(features)
    document.update(overrides)
    return document


def base_feature() -> dict:
    return profile_shaped_document()["features"][0]


def sketch_on(plane: dict, name: str, outer: dict) -> dict:
    return {
        "id": f"sketch.{name}",
        "plane": plane,
        "outer": outer,
        "inner": [],
        "construction": [],
        "constraints": [],
        "dimensions": [],
    }


def blind_cut() -> dict:
    return {
        "id": "feature.pocket",
        "type": "cut.extrude",
        "enabled": True,
        "depends_on": ["feature.base"],
        "produces": [],
        "inputs": {
            "direction": "+Z",
            "through_all": False,
            "distance": 3.0,
            "source_body": {"result": "body.main"},
            "sketch": sketch_on({"on": "base", "plane": "XY"}, "pocket",
                                {"type": "circle", "center": [10.0, 0.0], "radius": 4.0}),
        },
    }


def datum_and_boss() -> list[dict]:
    return [
        {
            "id": "feature.top",
            "type": "datum.plane.offset",
            "enabled": True,
            "depends_on": ["feature.base"],
            "produces": [{"id": "plane.top", "kind": "plane"}],
            "inputs": {"base": "XY", "offset_mm": 8.0, "flip": False},
        },
        {
            "id": "feature.boss",
            "type": "solid.extrude",
            "enabled": True,
            "depends_on": ["feature.base", "feature.top"],
            "produces": [],
            "inputs": {
                "direction": "+Z",
                "distance": 5.0,
                "sketch": sketch_on({"on": "datum", "plane": {"result": "plane.top"}}, "boss",
                                    {"type": "circle", "center": [0.0, 0.0], "radius": 6.0}),
            },
        },
    ]


def hole_and_pattern(pattern: dict) -> list[dict]:
    return [
        {
            "id": "feature.hole",
            "type": "cut.extrude",
            "enabled": True,
            "depends_on": ["feature.base"],
            "produces": [],
            "inputs": {
                "direction": "+Z",
                "through_all": True,
                "source_body": {"result": "body.main"},
                "sketch": sketch_on({"on": "base", "plane": "XY"}, "hole",
                                    {"type": "circle", "center": [-20.0, 0.0], "radius": 2.5}),
            },
        },
        {
            "id": "feature.repeat",
            "type": "feature.pattern",
            "enabled": True,
            "depends_on": ["feature.hole"],
            "produces": [],
            "inputs": {"of": "feature.hole", "pattern": pattern, "skip": []},
        },
    ]


LINEAR = {"kind": "linear", "direction": "+X", "spacing_mm": 20.0, "count": 3}
CIRCULAR = {"kind": "circular", "axis": "axis.z", "through": [0.0, 0.0, 0.0],
            "step_deg": 90.0, "count": 4}


@pytest.mark.parametrize(
    ("what", "features"),
    [
        ("a blind hole", [base_feature(), blind_cut()]),
        ("a boss on a datum plane", [base_feature(), *datum_and_boss()]),
        ("a linear pattern of holes", [base_feature(), *hole_and_pattern(LINEAR)]),
        ("a circular pattern of holes", [base_feature(), *hole_and_pattern(CIRCULAR)]),
    ],
)
def test_each_shape_the_profile_grew_is_canonically_valid(profile, what, features):
    """The direction that matters, for every new branch.

    A profile that accepted something the canonical validator refuses would tell the
    model to produce documents the trusted gate then rejects — a repair loop caused
    by our own schemas disagreeing.
    """
    document = with_features(*features)
    assert list(profile.iter_errors(document)) == [], what
    assert validate_canonical(document).schema_version == CAD_IR_VERSION


def test_a_cut_may_not_state_both_a_depth_and_through_all(profile):
    """The reason a blind hole is a second branch rather than an optional depth.

    The dialect has no optional properties and the contract forbids stating both, so
    one branch fixes `through_all` true and the other fixes it false. A document that
    tried to have it both ways is refused by the profile *and* by the validator.
    """
    document = with_features(base_feature(), blind_cut())
    document["features"][1]["inputs"]["through_all"] = True

    assert list(profile.iter_errors(document)) != []
    with pytest.raises(CadIrValidationError):
        validate_canonical(document)


def test_the_profile_still_refuses_what_the_dialect_cannot_state(profile):
    """Selectors did not arrive with the rest, and this is what keeps that true.

    A fillet's edges are named by predicates that are individually optional, which
    rule 4 cannot express — so the operation stays out of the cycle even though the
    engine has built it since POSTMVP-009.
    """
    document = with_features(base_feature(), {
        "id": "feature.round",
        "type": "feature.fillet",
        "enabled": True,
        "depends_on": ["feature.base"],
        "produces": [],
        "inputs": {
            "edges": {
                "id": "selector.corners", "kind": "edge", "from_result": "body.main",
                "cardinality": {"type": "exactly_n", "value": 4},
                "where": {"curve_type": "line", "direction_parallel_to": "axis.z"},
            },
            "radius": 3.0,
        },
    })

    # The canonical model has had this since 1.5; the profile has never offered it.
    assert validate_canonical(document).schema_version == CAD_IR_VERSION
    assert list(profile.iter_errors(document)) != []


#: The dialect the Codex structured-output API accepts, derived on 2026-07-28
#: from the 0.1.0 schema it had been accepting for months and from three real
#: rejections. Each rejection cost a full AI run, and the repair loop paid for
#: it three times before giving up, so the rules live here rather than being
#: rediscovered.
#:
#:   1. no `oneOf` — "'oneOf' is not permitted"
#:   2. every schema node declares a `type` — "schema must have a 'type' key"
#:   3. every array declares `items` — "array schema missing items"
#:   4. every object lists *all* its properties as required
#:   5. every object sets additionalProperties: false
#:
#: Rule 4 is the one with teeth: strict mode has no optional properties, so a
#: field kept "just in case" becomes a field the model is forced to invent.
UNSUPPORTED_KEYWORDS = (
    "oneOf",
    "allOf",
    "not",
    "contains",
    "minContains",
    "maxContains",
    "if",
    "then",
    "else",
    "patternProperties",
    "dependentSchemas",
    "propertyNames",
    "unevaluatedProperties",
    "unevaluatedItems",
)


def schema_nodes(node, path="$"):
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from schema_nodes(item, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return
    if any(key in node for key in ("type", "const", "enum", "properties", "items", "anyOf")):
        yield path, node
    for key, value in node.items():
        yield from schema_nodes(value, f"{path}.{key}")


def dialect_violations(schema) -> list[str]:
    found = []
    for path, node in schema_nodes(schema):
        if "type" not in node and "$ref" not in node and "anyOf" not in node:
            found.append(f"untyped: {path}")
        if node.get("type") == "array" and "items" not in node:
            found.append(f"array without items: {path}")
        if node.get("type") == "object" and "properties" in node:
            if set(node.get("required", [])) != set(node["properties"]):
                found.append(f"not every property is required: {path}")
            if node.get("additionalProperties") is not False:
                found.append(f"open object: {path}")
    for keyword in UNSUPPORTED_KEYWORDS:
        if any(keyword in node for _, node in schema_nodes(schema)):
            found.append(f"unsupported keyword: {keyword}")
    return found


def test_the_output_profile_stays_inside_the_structured_output_dialect():
    """This file is not just a JSON Schema; it is the response format Codex is
    constrained by. A keyword that dialect rejects fails every AI run for the
    job — which is exactly how these rules were learned."""
    assert dialect_violations(PROFILE) == []


def test_the_rules_are_the_ones_the_previously_accepted_schema_obeyed():
    """Derived, not guessed: the 0.1.0 schema the API accepted for months
    satisfies every rule above. If it did not, the rule would be wrong.

    Pinned as a fixture rather than read from git. A relative revision means
    something different after every commit, which is a test that changes its
    own subject.
    """
    accepted = json.loads(
        (ROOT / "tests" / "fixtures" / "schemas" / "cad-ir-mvp-output-0.1.0.accepted.json")
        .read_text(encoding="utf-8")
    )

    assert accepted["properties"]["schema_version"]["const"] == "0.1.0"
    assert dialect_violations(accepted) == []
