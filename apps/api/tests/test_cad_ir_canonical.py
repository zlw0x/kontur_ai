"""CAD-IR 1.1 canonical form.

The hash is the point of this module: it is what will let a later stage say
"this is the part we already built" rather than rebuilding it, and what lets
two versions of the same document be compared. So most of these tests are
about what must and must not change it.
"""

import json
import pytest
from pydantic import ValidationError

from cad_ir.canonical import (
    CAD_IR_SCHEMA,
    CAD_IR_VERSION,
    CadIrDocument,
    ParameterStatus,
    canonical_json,
)


def document(**overrides) -> dict:
    return {
        "schema": CAD_IR_SCHEMA,
        "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "name": "plate"},
        "parameters": [
            {"id": "param.width", "type": "length", "value": 60.0, "unit": "mm"},
            {"id": "param.depth", "type": "length", "value": 8.0, "unit": "mm"},
        ],
        "features": [
            {
                "id": "feature.base",
                "type": "solid.extrude",
                "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "sketch": {
                        "id": "sketch.base",
                        "plane": {"on": "base", "plane": "XY"},
                        "outer": {
                            "type": "rectangle",
                            "center": [0.0, 0.0],
                            "width": {"parameter": "param.width"},
                            "height": 30.0,
                        },
                    },
                    "direction": "+Z",
                    "distance": {"parameter": "param.depth"},
                },
            }
        ],
        "expectations": [{"id": "expect.bodies", "type": "body_count", "value": 1}],
        "metadata": {"generator": "fixture", "generator_version": "1.0"},
        **overrides,
    }


def test_a_document_declares_its_own_schema_and_version():
    parsed = CadIrDocument(**document())

    assert parsed.ir_schema == CAD_IR_SCHEMA
    assert parsed.schema_version == CAD_IR_VERSION
    assert parsed.canonical_dict()["schema"] == CAD_IR_SCHEMA


def test_a_future_version_is_refused_rather_than_read_optimistically():
    with pytest.raises(ValidationError):
        CadIrDocument(**document(schema_version="1.8"))
    with pytest.raises(ValidationError):
        CadIrDocument(**document(schema_version="0.1.0"))
    with pytest.raises(ValidationError):
        CadIrDocument(**document(schema="something-else"))


def test_the_canonical_hash_is_stable_across_key_order_and_round_trips():
    first = CadIrDocument(**document())
    shuffled = dict(reversed(list(document().items())))

    assert CadIrDocument(**shuffled).canonical_sha256() == first.canonical_sha256()
    assert CadIrDocument(**first.canonical_dict()).canonical_sha256() == first.canonical_sha256()
    assert CadIrDocument(**json.loads(first.canonical_json())).canonical_sha256() == (
        first.canonical_sha256()
    )


def test_an_omitted_optional_field_hashes_the_same_as_an_absent_one():
    """A document that leaves `name` out and one that has never had it are the
    same part; serialising nulls would make them different."""
    without = document()
    without["document"] = {"units": "mm"}
    explicit_null = document()
    explicit_null["document"] = {"units": "mm", "name": None}

    assert CadIrDocument(**without).canonical_sha256() == (
        CadIrDocument(**explicit_null).canonical_sha256()
    )
    assert "null" not in CadIrDocument(**without).canonical_json()


def test_changing_geometry_changes_the_hash():
    baseline = CadIrDocument(**document()).canonical_sha256()

    wider = document()
    wider["parameters"][0]["value"] = 61.0
    assert CadIrDocument(**wider).canonical_sha256() != baseline

    renamed = document()
    renamed["features"][0]["id"] = "feature.base_plate"
    assert CadIrDocument(**renamed).canonical_sha256() != baseline


def test_the_generator_metadata_is_part_of_the_document_but_the_model_is_not():
    """ADR-017: model and CLI version live on the AI run. If they were in here,
    an identical part would change hash whenever the model changed."""
    parsed = CadIrDocument(**document())
    blob = parsed.canonical_json()

    assert "generator" in blob
    with pytest.raises(ValidationError):
        CadIrDocument(
            **document(metadata={"generator": "a", "generator_version": "1", "model": "gpt-5.6-terra"})
        )


def test_identifiers_must_be_readable_and_stable():
    for bad in ("Feature.Base", "feature base", "9feature", "f", "феатура", "feature/base"):
        broken = document()
        broken["features"][0]["id"] = bad
        with pytest.raises(ValidationError):
            CadIrDocument(**broken)


def test_a_parameter_must_carry_the_canonical_unit_for_its_type():
    for parameter_type, unit in (("length", "cm"), ("length", None), ("angle", "mm"), ("count", "mm")):
        broken = document()
        broken["parameters"][0] = {
            "id": "param.width",
            "type": parameter_type,
            "value": 1.0,
            "unit": unit,
        }
        with pytest.raises(ValidationError):
            CadIrDocument(**broken)

    fine = document()
    fine["parameters"][0] = {"id": "param.angle", "type": "angle", "value": 45.0, "unit": "deg"}
    fine["features"][0]["inputs"]["sketch"]["outer"]["width"] = 60.0
    assert CadIrDocument(**fine).parameters[0].unit == "deg"


def test_a_count_parameter_must_be_whole_and_a_boolean_must_be_zero_or_one():
    broken = document()
    broken["parameters"][0] = {"id": "param.holes", "type": "count", "value": 2.5}
    with pytest.raises(ValidationError):
        CadIrDocument(**broken)

    broken["parameters"][0] = {"id": "param.flag", "type": "boolean", "value": 7}
    with pytest.raises(ValidationError):
        CadIrDocument(**broken)


def test_only_the_operations_this_version_expresses_are_accepted():
    for unsupported in ("hole", "revolve_add", "solid.revolve", "surface.loft", "extrude_add"):
        broken = document()
        broken["features"][0]["type"] = unsupported
        with pytest.raises(ValidationError):
            CadIrDocument(**broken)


def test_execution_details_cannot_be_expressed_at_all():
    """The schema is closed, so a COM handle or a face index has nowhere to go
    even before the semantic validator looks for one."""
    for injected in ({"edge_index": 17}, {"com_handle": "0x1234"}, {"script": "powershell.exe"}):
        broken = document()
        broken["features"][0]["inputs"].update(injected)
        with pytest.raises(ValidationError):
            CadIrDocument(**broken)


def test_a_cut_must_say_how_deep_it_goes_exactly_once():
    def cut(**inputs) -> dict:
        broken = document()
        broken["features"].append(
            {
                "id": "feature.hole",
                "type": "cut.extrude",
                "depends_on": ["feature.base"],
                "inputs": {
                    "sketch": {
                        "id": "sketch.hole",
                        "plane": {"on": "base", "plane": "XY"},
                        "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 2.5},
                    },
                    "direction": "+Z",
                    **inputs,
                },
            }
        )
        return broken

    assert len(CadIrDocument(**cut(through_all=True)).features) == 2
    assert len(CadIrDocument(**cut(distance=8.0)).features) == 2
    with pytest.raises(ValidationError):
        CadIrDocument(**cut())
    with pytest.raises(ValidationError):
        CadIrDocument(**cut(through_all=True, distance=8.0))


def test_canonical_json_is_byte_stable_for_equal_content():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_json({"a": 1.0}) == '{"a":1.0}'


def test_reference_geometry_is_declared_but_empty_in_this_version():
    """The slot exists so 1.2 can fill it without moving anything; accepting
    entries now would mean accepting a shape nothing validates."""
    broken = document()
    broken["reference_geometry"] = [{"id": "plane.offset", "type": "offset_plane"}]
    with pytest.raises(ValidationError):
        CadIrDocument(**broken)


def test_parameter_status_survives_into_the_canonical_form():
    unresolved = document()
    unresolved["parameters"][0]["status"] = "unresolved"

    parsed = CadIrDocument(**unresolved)
    assert parsed.parameters[0].status is ParameterStatus.UNRESOLVED
    assert '"status":"unresolved"' in parsed.canonical_json()
