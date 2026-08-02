"""Normalisation is a translation, not a repair.

The tests that matter here are the ones about what it refuses. A migration
that quietly drops a recorded statement, folds a formula into a literal or
converts a unit is worse than one that stops and says so.
"""

import json
from pathlib import Path

import pytest

from cad_ir.canonical import CAD_IR_VERSION, MIGRATABLE_VERSIONS, DocumentMetadata
from cad_ir.errors import CadIrValidationError
from cad_ir.normalizer import NORMALIZER_VERSION, normalize

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "cad-ir"


def legacy(name: str = "plate-with-hole") -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def codes(callable_) -> set[str]:
    with pytest.raises(CadIrValidationError) as caught:
        callable_()
    return {issue.code for issue in caught.value.issues}


def test_the_existing_fixtures_migrate_without_changing_the_part():
    """The plate the confirmed MVP builds must survive the schema change with
    the same dimensions, the same hole and the same tolerances."""
    document = normalize(legacy()).document

    assert {parameter.id: parameter.value for parameter in document.parameters} == {
        "p_width": 40.0,
        "p_height": 20.0,
        "p_depth": 10.0,
        "p_hole_radius": 3.0,
    }
    assert [feature.type.value for feature in document.features] == ["solid.extrude", "cut.extrude"]
    assert document.features[1].depends_on == ["f_base"]
    assert document.features[1].inputs.through_all is True

    rectangle = document.features[0].inputs.sketch.outer
    assert rectangle.width.parameter == "p_width"
    circle = document.features[1].inputs.sketch.outer
    assert circle.radius.parameter == "p_hole_radius"

    expectations = {item.type: item for item in document.expectations}
    assert expectations["bounding_box"].size_mm.model_dump() == {"x": 40.0, "y": 20.0, "z": 10.0}
    assert expectations["bounding_box"].tolerance_mm == 0.05
    assert expectations["body_count"].value == 1
    assert expectations["through_hole_count"].value == 1


def test_normalising_twice_produces_identical_bytes():
    first = normalize(legacy())
    second = normalize(json.loads(first.canonical_json))

    assert second.canonical_json == first.canonical_json
    assert second.lineage.canonical_sha256 == first.lineage.canonical_sha256


def test_lineage_records_both_ends_of_the_translation():
    result = normalize(legacy())

    assert result.lineage.original_schema_version == "0.1.0"
    assert result.lineage.canonical_schema_version == CAD_IR_VERSION
    assert result.lineage.normalizer_version == NORMALIZER_VERSION
    assert result.lineage.original_sha256 != result.lineage.canonical_sha256
    assert len(result.lineage.original_sha256) == 64
    assert set(result.lineage.as_dict()) == {
        "original_schema_version",
        "canonical_schema_version",
        "original_sha256",
        "canonical_sha256",
        "normalizer_version",
    }


def test_the_original_hash_is_of_the_document_as_given():
    """Two byte-different spellings of the same 0.1.0 document hash the same,
    so a re-submission is recognisable, but a changed dimension is not."""
    document = legacy()
    reordered = dict(reversed(list(document.items())))
    assert normalize(reordered).lineage.original_sha256 == normalize(document).lineage.original_sha256

    changed = legacy()
    changed["parameters"][0]["value"] = 41.0
    assert normalize(changed).lineage.original_sha256 != normalize(document).lineage.original_sha256


def test_semantic_outputs_become_typed_results():
    document = normalize(legacy()).document

    assert [(item.id, item.kind.value) for item in document.features[0].produces] == [
        ("body.main", "solid_body"),
        ("face.f_base.end", "face"),
    ]


def test_a_bare_expression_becomes_a_parameter_reference():
    """Every expression 0.1.0 actually used was a parameter name."""
    document = normalize(legacy("plate")).document

    assert document.features[0].inputs.distance.parameter == "p_depth"


def test_real_arithmetic_is_refused_rather_than_folded_into_a_number():
    """Evaluating it would turn a parametric document into a literal one and
    lose the intent the document existed to record."""
    document = legacy("plate")
    document["features"][0]["inputs"]["distance"] = {"expr": "p_depth * 2"}

    assert codes(lambda: normalize(document)) == {"CAD_IR_MIGRATION_FAILED"}


def test_an_operation_1_1_cannot_express_stops_the_migration():
    document = legacy("plate")
    document["features"][0]["type"] = "hole"

    with pytest.raises(CadIrValidationError) as caught:
        normalize(document)
    assert caught.value.issues[0].code == "CAD_IR_MIGRATION_FAILED"
    assert "hole" in caught.value.issues[0].message


def test_a_recorded_assumption_is_never_silently_dropped():
    document = legacy("plate")
    document["assumptions"] = [{"parameter": "p_depth", "reason": "read from a side view"}]

    with pytest.raises(CadIrValidationError) as caught:
        normalize(document)
    assert caught.value.issues[0].code == "CAD_IR_MIGRATION_FAILED"
    assert "assumptions" in caught.value.issues[0].message


def test_an_unresolved_item_stops_the_migration():
    document = legacy("plate")
    document["unresolved"] = [{"question": "what is the depth?"}]

    assert codes(lambda: normalize(document)) == {"CAD_IR_MIGRATION_FAILED"}


def test_a_unit_other_than_millimetres_is_not_converted():
    """Converting a dimension during a schema migration is exactly the silent
    change this refuses to make."""
    document = legacy("plate")
    document["parameters"][0]["unit"] = "cm"

    assert codes(lambda: normalize(document)) == {"CAD_IR_MIGRATION_FAILED"}


def test_an_advisory_invariant_is_not_promoted_to_a_binding_expectation():
    document = legacy("plate")
    document["expected_invariants"][0]["severity"] = "warning"

    with pytest.raises(CadIrValidationError) as caught:
        normalize(document)
    assert "binding" in caught.value.issues[0].message


def test_an_unknown_version_has_no_migration_path():
    document = legacy("plate")
    document["schema_version"] = "0.9.0"

    assert codes(lambda: normalize(document)) == {"CAD_IR_VERSION_UNSUPPORTED"}


def test_a_document_with_no_version_is_rejected():
    document = legacy("plate")
    del document["schema_version"]

    assert codes(lambda: normalize(document)) == {"CAD_IR_VERSION_MISSING"}


def test_untyped_legacy_provenance_is_kept_as_a_note():
    document = normalize(legacy("plate")).document
    provenance = document.parameters[0].provenance

    assert provenance is not None
    assert provenance.confidence == 1.0
    assert provenance.note == '{"type": "fixture"}'


def test_the_caller_supplies_the_generator_because_only_it_knows():
    result = normalize(
        legacy("plate"),
        metadata=DocumentMetadata(
            generator="drawing-agent", generator_version="0.4.0", prompt_version="drawing-mvp-1"
        ),
    )

    assert result.document.metadata.generator == "drawing-agent"
    assert result.document.metadata.prompt_version == "drawing-mvp-1"
    # A different generator is a different document, and hashes differently.
    assert result.lineage.canonical_sha256 != normalize(legacy("plate")).lineage.canonical_sha256


def test_an_already_canonical_document_passes_through_unchanged():
    canonical = json.loads(normalize(legacy()).canonical_json)

    result = normalize(canonical)

    assert result.lineage.original_schema_version == CAD_IR_VERSION
    assert result.lineage.original_sha256 == result.lineage.canonical_sha256


def test_a_cut_is_linked_to_the_body_its_dependency_produced():
    """0.1.0 said which body a cut affected through depends_on; 1.1 says it
    with source_body. Deriving one from the other is a translation of something
    already stated, not an assumption."""
    document = normalize(legacy()).document

    assert document.features[1].inputs.source_body.result == "body.main"


def test_an_ambiguous_dependency_leaves_the_source_body_unset():
    """Two dependencies producing two bodies is not a question this can answer
    on the document's behalf."""
    document = legacy()
    document["features"][0]["semantic_outputs"] = ["body.main", "body.second"]

    normalized = normalize(document).document

    assert normalized.features[1].inputs.source_body is None


def test_every_version_the_contract_calls_migratable_actually_migrates():
    """The two lists that say which versions are readable must not disagree.

    `MIGRATABLE_VERSIONS` is what the validator quotes back when it tells a caller to
    normalise first, and the normalizer's own branch is what decides whether it can.
    They were kept in step by hand until 1.7 landed, at which point 1.6 stayed in the
    first list and never reached the second — so a 1.6 document was told to normalise
    and then refused as unsupported, by the same build, on the same run.

    Every version from 1.2 onwards is a relabelling, so a current document with its
    version field rewritten is a valid document of that version for this purpose.
    """
    canonical = json.loads(normalize(legacy()).canonical_json)

    for version in MIGRATABLE_VERSIONS:
        if version in ("0.1.0", "1.1"):
            # Genuinely different shapes, each with its own translation and its own
            # tests above. A relabelled canonical document is not one of them.
            continue
        result = normalize({**canonical, "schema_version": version})
        assert result.lineage.original_schema_version == version
        assert result.lineage.canonical_schema_version == CAD_IR_VERSION


def test_the_version_before_this_one_is_migratable():
    """Backward compatibility of at least one version, as POSTMVP-004 requires.

    Written as arithmetic on the current version rather than as a literal, because a
    literal is what let 1.6 fall out of the list in the first place.
    """
    major, minor = (int(part) for part in CAD_IR_VERSION.split("."))
    assert f"{major}.{minor - 1}" in MIGRATABLE_VERSIONS
