"""The narrowed schema Codex is constrained to must stay a subset.

Two schemas describe CAD-IR 1.1: the canonical one, which says what the
version can express, and the MVP output profile, which says what this build
can construct. If the profile ever accepted something the canonical model
rejects, Codex would be told to produce documents the trusted validator then
refuses — a repair loop caused entirely by our own schemas disagreeing.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

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
    return json.loads((FIXTURES / f"{name}.v1_1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["plate", "plate-with-hole"])
def test_the_canonical_fixtures_satisfy_the_narrowed_profile(profile, name):
    """What the normalizer produces is what Codex is asked to produce."""
    assert list(profile.iter_errors(canonical_fixture(name))) == []


@pytest.mark.parametrize("name", ["plate", "plate-with-hole"])
def test_anything_the_profile_accepts_is_canonically_valid(profile, name):
    document = canonical_fixture(name)
    assert list(profile.iter_errors(document)) == []

    assert validate_canonical(document).schema_version == "1.1"


def test_the_profile_declares_the_same_version_as_the_canonical_schema():
    assert PROFILE["properties"]["schema_version"]["const"] == "1.1"
    assert PROFILE["properties"]["schema"]["const"] == "cad-ai/cad-ir"


@pytest.mark.parametrize(
    "mutation",
    [
        ("plane", "XZ"),
        ("direction", "-Z"),
    ],
)
def test_the_profile_is_narrower_than_the_canonical_model(profile, mutation):
    """The canonical model allows three planes and six directions because a
    later version will need them. The profile allows one of each, so Codex is
    never asked for geometry this adapter cannot build."""
    key, value = mutation
    document = canonical_fixture("plate")
    inputs = document["features"][0]["inputs"]
    if key == "plane":
        inputs["sketch"]["plane"] = value
    else:
        inputs["direction"] = value

    # Canonically valid...
    assert validate_canonical(document).schema_version == "1.1"
    # ...but outside what Codex may produce.
    assert list(profile.iter_errors(document)) != []


def test_the_profile_rejects_an_expression(profile):
    document = canonical_fixture("plate")
    document["features"][0]["inputs"]["distance"] = {"expr": "p_depth * 2"}

    assert list(profile.iter_errors(document)) != []
    with pytest.raises(CadIrValidationError):
        validate_canonical(document)
