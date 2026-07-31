"""An operation can be turned off without a release (ADR-021).

ENGINE-MIG-007 pays the debt ENGINE-MIG-006 left: the KOMPAS worker has had a
per-operation rollback switch since POSTMVP-006 and build123d shipped without
one.

These need no CAD library. Deciding what a document requires is a property of the
document, not of the kernel — the same split that keeps selector matching testable
apart from selector reading, and the reason a disabled operation can be refused
before any geometry exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cad_ir.canonical_validator import validate_canonical

from cad_engine_build123d import capabilities as caps
from cad_engine_build123d.errors import CadEngineError

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "cad-ir"


def document(name: str):
    return validate_canonical(json.loads((FIXTURES / name).read_text("utf-8")))


# --- what a document asks for ---------------------------------------------


def test_a_plain_plate_asks_for_the_plainest_things():
    needed = caps.requirements(document("plate.v1_4.json"))
    assert set(needed) == {
        caps.SOLID_RECTANGULAR_PRISM,
        caps.SKETCH_PLANE_BASE,
        caps.EXPORT_STEP,
        caps.EXPORT_STL,
        caps.VALIDATE_MANIFOLD,
        caps.VALIDATE_BOUNDING_BOX,
    }
    # No hole expectation, so nothing asks for the check that counts them.
    assert caps.VALIDATE_HOLE_COUNT not in needed


def test_the_lever_plate_asks_for_everything_it_actually_uses():
    """The hardest fixture: contours, arcs, islands, a datum plane, a selector."""
    needed = caps.requirements(document("lever-plate.v1_4.json"))
    assert set(needed) == {
        caps.SOLID_RECTANGULAR_PRISM,
        caps.SOLID_CONTOUR_PROFILE,
        caps.FEATURE_BOSS_ADDITIVE,
        caps.SKETCH_ARC,
        caps.SKETCH_ISLANDS,
        caps.SKETCH_CONSTRUCTION,
        caps.SKETCH_REGULAR_POLYGON,
        caps.SKETCH_PLANE_BASE,
        caps.SKETCH_PLANE_DATUM,
        caps.SKETCH_PLANE_FACE_SELECTOR,
        caps.EXPORT_STEP,
        caps.EXPORT_STL,
        caps.VALIDATE_MANIFOLD,
        caps.VALIDATE_BOUNDING_BOX,
        caps.VALIDATE_HOLE_COUNT,
    }


def test_a_second_additive_feature_is_a_boss_and_the_first_is_not():
    """The distinction the multi-body defect of POSTMVP-006 was about.

    Making the first solid and adding to one that already exists are different
    operations, and only the second can leave a part in two pieces.
    """
    assert caps.FEATURE_BOSS_ADDITIVE not in caps.requirements(document("plate.v1_4.json"))
    assert caps.FEATURE_BOSS_ADDITIVE in caps.requirements(document("lever-plate.v1_4.json"))


def test_the_bushing_asks_for_revolve_and_for_the_revolved_cut():
    needed = caps.requirements(document("bushing.v1_4.json"))
    assert caps.SOLID_REVOLVE in needed
    assert caps.CUT_REVOLVE in needed
    assert needed[caps.SOLID_REVOLVE] == "the revolve feature.bush"


def test_a_disabled_feature_asks_for_nothing():
    """A document saying "not this one" is not asking for the operation."""
    value = json.loads((FIXTURES / "bushing.v1_4.json").read_text("utf-8"))
    value["features"][1]["enabled"] = False
    assert caps.CUT_REVOLVE not in caps.requirements(validate_canonical(value))


@pytest.mark.parametrize(
    "name",
    ["plate.v1_4.json", "plate-with-hole.v1_4.json", "constrained-plate.v1_4.json",
     "lever-plate.v1_4.json", "bushing.v1_4.json"],
)
def test_no_fixture_asks_for_a_capability_this_engine_does_not_declare(name):
    """The invariant that makes a manifest honest.

    A requirement naming a key the manifest never publishes is a job the API can
    never schedule to anyone, and nothing else in the system would notice.
    """
    assert set(caps.requirements(document(name))) <= caps.ALL


# --- turning one off -------------------------------------------------------


def test_a_document_needing_a_disabled_operation_is_refused_whole():
    gate = caps.CapabilityGate.disabling([caps.SKETCH_ARC])
    with pytest.raises(CadEngineError) as refused:
        gate.require_all(caps.requirements(document("lever-plate.v1_4.json")))
    assert refused.value.code == "CAPABILITY_DISABLED"
    assert refused.value.stage == "cad-ir"
    assert "sketch.arc" in refused.value.safe_message


def test_every_blocked_capability_is_named_not_only_the_first():
    """An operator who turned off three operations should learn that in one run."""
    gate = caps.CapabilityGate.disabling(
        [caps.SKETCH_ARC, caps.SKETCH_ISLANDS, caps.SKETCH_REGULAR_POLYGON]
    )
    with pytest.raises(CadEngineError) as refused:
        gate.require_all(caps.requirements(document("lever-plate.v1_4.json")))
    for key in ("sketch.arc", "sketch.islands", "sketch.regular_polygon"):
        assert key in refused.value.safe_message


def test_turning_off_something_the_document_does_not_use_changes_nothing():
    gate = caps.CapabilityGate.disabling([caps.SKETCH_SLOT])
    gate.require_all(caps.requirements(document("plate.v1_4.json")))


def test_an_unknown_capability_is_refused_rather_than_ignored():
    """A typo in a rollback switch must not leave an operation quietly running."""
    with pytest.raises(CadEngineError) as refused:
        caps.CapabilityGate.disabling(["sketch.ark"])
    assert refused.value.code == "CAPABILITY_UNKNOWN"
    assert "sketch.ark" in refused.value.safe_message


def test_a_disabled_capability_is_published_as_disabled_rather_than_downgraded():
    """`disabled` is not a low rung on the maturity ladder.

    The API reads it as "no" outright, so the operation stops being scheduled
    instead of being scheduled reluctantly.
    """
    gate = caps.CapabilityGate.disabling([caps.SKETCH_SLOT])
    declarations = gate.declarations()
    assert declarations[caps.SKETCH_SLOT]["status"] == "disabled"
    assert declarations[caps.SKETCH_ARC]["status"] == "beta"
    assert set(declarations) == caps.ALL


def test_nothing_is_off_by_default():
    """A missing flag file must never be able to silently disable a service."""
    gate = caps.CapabilityGate.all_enabled()
    assert gate.disabled == frozenset()
    assert all(item["status"] != "disabled" for item in gate.declarations().values())


# --- honesty about maturity ------------------------------------------------


def test_revolve_is_experimental_and_therefore_not_leasable():
    """One fixture and one day.

    The API refuses an experimental capability on an ordinary claim, which is the
    correct answer while nothing in the service can produce a revolve document:
    the drawing agent cannot read a turned profile and the output profile does
    not offer the operation.
    """
    assert caps.DECLARED[caps.SOLID_REVOLVE].status == "experimental"
    assert caps.DECLARED[caps.CUT_REVOLVE].status == "experimental"


def test_nothing_on_a_two_milestone_old_engine_claims_to_be_stable():
    """The roadmap's bar for stable is ten positive and ten negative fixtures."""
    assert {declared.status for declared in caps.DECLARED.values()} == {"beta", "experimental"}


# --- the two engines use one vocabulary ------------------------------------


def kompas_keys() -> set[str]:
    """The .NET engine's capability keys, read from its own source.

    Read rather than duplicated. A copy of this list in Python would be a second
    place for the vocabulary to live, which is the failure this test exists to
    catch.
    """
    source = (ROOT / "packages" / "cad-engine-contracts" / "CadCapabilities.cs").read_text("utf-8")
    return set(re.findall(r'public const string \w+ = "([^"]+)";', source))


def test_the_two_engines_spell_the_same_operation_the_same_way():
    """The API schedules on these names.

    Two engines with different words for one operation means a job routed by
    capability cannot be routed at all — and the failure would look like a worker
    that is simply never compatible, with nothing saying why.

    Every difference below is deliberate and named. A new key on either side that
    is not in this list fails here, which is the point.
    """
    kompas = kompas_keys()
    build123d = set(caps.ALL)

    assert kompas - build123d == {
        # KOMPAS-native, and leaving the product with KOMPAS (ADR-023).
        "export.m3d",
    }
    assert build123d - kompas == {
        # CAD-IR 1.4, and deliberately never built on KOMPAS (ADR-024).
        "solid.revolve",
        "cut.revolve",
    }
