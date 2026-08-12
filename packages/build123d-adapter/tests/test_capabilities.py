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
from cad_ir_fixtures import fixture

from cad_ir.canonical_validator import validate_canonical

from cad_engine_build123d import capabilities as caps
from cad_engine_build123d.errors import CadEngineError

ROOT = Path(__file__).resolve().parents[3]


def document(name: str):
    """The named fixture, validated. `name` carries no version (`cad_ir_fixtures`)."""
    return validate_canonical(fixture(name))


# --- what a document asks for ---------------------------------------------


def test_a_plain_plate_asks_for_the_plainest_things():
    needed = caps.requirements(document("plate"))
    assert set(needed) == {
        caps.SOLID_RECTANGULAR_PRISM,
        caps.SKETCH_PLANE_BASE,
        caps.EXPORT_STEP,
        caps.EXPORT_STL,
        caps.VALIDATE_MANIFOLD,
        caps.VALIDATE_BOUNDING_BOX,
        caps.VALIDATE_TOPOLOGY,
    }
    # No hole expectation, so nothing asks for the check that counts them.
    assert caps.VALIDATE_HOLE_COUNT not in needed


def test_the_lever_plate_asks_for_everything_it_actually_uses():
    """The hardest fixture: contours, arcs, islands, a datum plane, a selector."""
    needed = caps.requirements(document("lever-plate"))
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
        caps.VALIDATE_TOPOLOGY,
        caps.VALIDATE_HOLE_COUNT,
    }


def test_a_second_additive_feature_is_a_boss_and_the_first_is_not():
    """The distinction the multi-body defect of POSTMVP-006 was about.

    Making the first solid and adding to one that already exists are different
    operations, and only the second can leave a part in two pieces.
    """
    assert caps.FEATURE_BOSS_ADDITIVE not in caps.requirements(document("plate"))
    assert caps.FEATURE_BOSS_ADDITIVE in caps.requirements(document("lever-plate"))


def test_the_bushing_asks_for_revolve_and_for_the_revolved_cut():
    needed = caps.requirements(document("bushing"))
    assert caps.SOLID_REVOLVE in needed
    assert caps.CUT_REVOLVE in needed
    assert needed[caps.SOLID_REVOLVE] == "the revolve feature.bush"


def test_a_disabled_feature_asks_for_nothing():
    """A document saying "not this one" is not asking for the operation."""
    value = fixture("bushing")
    value["features"][1]["enabled"] = False
    assert caps.CUT_REVOLVE not in caps.requirements(validate_canonical(value))


def test_the_bracket_asks_for_each_blend_separately():
    """A fillet, an equal-distance chamfer and an asymmetric one are three switches.

    Granularity follows the failure. An operator who has seen a chamfer come out
    the wrong way round wants to stop the asymmetric form — the one that has to
    decide which face its first distance belongs to — without stopping every
    chamfer, and without stopping fillets that have nothing to do with it.
    """
    needed = caps.requirements(document("blended-bracket"))
    assert caps.FEATURE_FILLET_CONSTANT in needed
    assert caps.FEATURE_CHAMFER_EQUAL in needed
    assert caps.FEATURE_CHAMFER_ASYMMETRIC in needed
    assert needed[caps.FEATURE_FILLET_CONSTANT] == "the fillet feature.corners"
    # The predicate gets its own key: it is a measurement this engine makes with a
    # dot product of its own, and if that is wrong what has to stop is every
    # selector that trusts it rather than every fillet.
    assert caps.SELECTOR_EDGE_CONVEXITY in needed
    assert caps.VALIDATE_SURFACE_FACE_COUNT in needed


def test_a_document_with_no_convexity_predicate_does_not_ask_for_one():
    value = fixture("blended-bracket")
    for feature in value["features"]:
        feature["inputs"].get("edges", {}).get("where", {}).pop("convexity", None)
    assert caps.SELECTOR_EDGE_CONVEXITY not in caps.requirements(validate_canonical(value))


def test_turning_off_convexity_refuses_the_document_before_any_geometry():
    gate = caps.CapabilityGate.disabling([caps.SELECTOR_EDGE_CONVEXITY])
    with pytest.raises(CadEngineError) as refused:
        gate.require_all(caps.requirements(document("blended-bracket")))
    assert refused.value.code == "CAPABILITY_DISABLED"
    assert "selector.edge.convexity" in refused.value.safe_message


def test_the_boolean_bracket_asks_for_a_key_per_operation():
    """Union, subtract and intersect fail differently and get different switches.

    A separate body is its own key as well: a part delivered as two lumps where one was
    meant is a different kind of wrong from a misplaced boss, and an operator may want
    to stop only that.
    """
    needed = caps.requirements(document("boolean-bracket"))
    assert caps.BOOLEAN_UNION in needed
    assert caps.BOOLEAN_SUBTRACT in needed
    assert caps.FEATURE_BODY_NEW in needed
    # Nothing intersects, so nothing asks for it.
    assert caps.BOOLEAN_INTERSECT not in needed
    assert needed[caps.BOOLEAN_UNION] == "the boolean feature.weld_rib"


def test_a_feature_that_starts_a_body_is_not_a_boss():
    """A boss fuses with what is there; a new body fuses with nothing.

    They were one key while there was one body, and conflating them now would mean
    turning off bosses stopped a document that never had one.
    """
    needed = caps.requirements(document("boolean-bracket"))
    assert caps.FEATURE_BOSS_ADDITIVE not in needed
    assert caps.FEATURE_BOSS_ADDITIVE in caps.requirements(document("lever-plate"))


def test_the_flange_asks_for_each_kind_of_pattern_separately():
    """Linear, circular and mirror are three switches.

    They fail in different ways — a spacing, an angle about an axis, a reflection —
    and an operator who has seen a bolt circle come out wrong wants to stop that
    without stopping the mounting holes.
    """
    needed = caps.requirements(document("patterned-flange"))
    assert caps.FEATURE_PATTERN_LINEAR in needed
    assert caps.FEATURE_PATTERN_CIRCULAR in needed
    assert caps.FEATURE_MIRROR in needed
    assert needed[caps.FEATURE_PATTERN_CIRCULAR] == "the pattern feature.bolt_circle"


def test_turning_off_one_kind_of_pattern_refuses_the_document_whole():
    gate = caps.CapabilityGate.disabling([caps.FEATURE_MIRROR])
    with pytest.raises(CadEngineError) as refused:
        gate.require_all(caps.requirements(document("patterned-flange")))
    assert refused.value.code == "CAPABILITY_DISABLED"
    assert "feature.mirror" in refused.value.safe_message


@pytest.mark.parametrize(
    "name",
    ["plate", "plate-with-hole", "constrained-plate",
     "lever-plate", "bushing", "blended-bracket",
     "patterned-flange", "boolean-bracket"],
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
        gate.require_all(caps.requirements(document("lever-plate")))
    assert refused.value.code == "CAPABILITY_DISABLED"
    assert refused.value.stage == "cad-ir"
    assert "sketch.arc" in refused.value.safe_message


def test_every_blocked_capability_is_named_not_only_the_first():
    """An operator who turned off three operations should learn that in one run."""
    gate = caps.CapabilityGate.disabling(
        [caps.SKETCH_ARC, caps.SKETCH_ISLANDS, caps.SKETCH_REGULAR_POLYGON]
    )
    with pytest.raises(CadEngineError) as refused:
        gate.require_all(caps.requirements(document("lever-plate")))
    for key in ("sketch.arc", "sketch.islands", "sketch.regular_polygon"):
        assert key in refused.value.safe_message


def test_turning_off_something_the_document_does_not_use_changes_nothing():
    gate = caps.CapabilityGate.disabling([caps.SKETCH_SLOT])
    gate.require_all(caps.requirements(document("plate")))


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


def test_the_corpus_is_what_promoted_the_operations_to_beta():
    """Every operation arrived `experimental` on one fixture; the corpus is the evidence.

    `experimental` means the API will not lease a job needing it. That was the right
    answer while an operation had one fixture and one day behind it, and the promotion
    was always meant to be a one-line change with a corpus behind it (POSTMVP-013/014):
    several sizes, closed-form arithmetic, named refusals, byte-identical repeats.

    What this asserts is the promotion **out of `experimental`**, not a particular
    destination. Some of these have since gone further — a revolve is built by three
    kinds of part in the corpus and is `stable` as of POSTMVP-028 — and which ones is
    measured in `test_corpus.py` rather than listed here, so this test does not have to
    be edited every time the corpus grows.
    """
    for key in (caps.SOLID_REVOLVE, caps.CUT_REVOLVE, caps.FEATURE_FILLET_CONSTANT,
                caps.FEATURE_CHAMFER_EQUAL, caps.FEATURE_PATTERN_LINEAR,
                caps.FEATURE_PATTERN_CIRCULAR, caps.FEATURE_MIRROR,
                caps.FEATURE_BODY_NEW, caps.BOOLEAN_UNION, caps.BOOLEAN_SUBTRACT,
                caps.BOOLEAN_INTERSECT, caps.SELECTOR_EDGE_CONVEXITY,
                caps.VALIDATE_SURFACE_FACE_COUNT):
        assert caps.DECLARED[key].status in {"beta", "stable"}, key


def test_the_one_operation_the_corpus_does_not_vary_stays_experimental():
    """An asymmetric chamfer's distinguishing question has no corpus case.

    Which face the first distance is measured from is the whole content of the
    operation, and the blended-bracket fixture exercises it once without varying it. An
    operation does not earn a promotion because its neighbours did.
    """
    assert caps.DECLARED[caps.FEATURE_CHAMFER_ASYMMETRIC].status == "experimental"


def test_a_status_is_one_of_three_words_and_nothing_else():
    """The vocabulary, and it is the only thing this test still fixes.

    It used to assert that **nothing** was `stable`, which was true while the corpus was
    42 cases across fifteen shapes and stopped being true when it reached Gate P2's bar
    — 100 models, 38 part types, all 100 deterministic
    (`docs/acceptance/POSTMVP-028-*`). Which keys earned it is not decided here: it is
    measured against the corpus by `test_corpus.py`, in both directions, so a
    declaration cannot run ahead of the evidence and the evidence cannot quietly outgrow
    a declaration.
    """
    assert {declared.status for declared in caps.DECLARED.values()} <= {
        "experimental", "beta", "stable"
    }
    assert "stable" in {declared.status for declared in caps.DECLARED.values()}


# --- there is only one vocabulary now --------------------------------------


def test_no_dotnet_file_declares_a_capability_key_of_its_own():
    """The drift this used to guard against is now unrepresentable.

    Until ENGINE-MIG-008 there were two engines and two lists of keys, and a test
    here read `CadCapabilities.cs` and asserted the only differences were
    deliberate. That file is gone with KOMPAS, and the worker asks the engine what
    it can build instead of carrying an answer.

    What is left worth checking is that it stays that way. A `const string ... =
    "solid.something"` reappearing on the .NET side would be the same second
    vocabulary under a new name, and the failure it produces is the one that is
    hardest to see: the API schedules an operation the worker then refuses.
    """
    declarations: list[str] = []
    for source in (ROOT / "packages").rglob("*.cs"):
        if "/obj/" in source.as_posix() or "/bin/" in source.as_posix():
            continue
        for name, value in re.findall(
            r'const string (\w+)\s*=\s*"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)"', source.read_text("utf-8")
        ):
            if value in caps.ALL:
                declarations.append(f"{source.relative_to(ROOT)}: {name} = {value}")
    assert not declarations, (
        "the .NET side declares capability keys again: " + "; ".join(declarations)
    )


# --- the chain, and the way it broke ---------------------------------------


def _sweep(kind: str, path: dict, fid: str = "feature.pipe",
           cut_from: str | None = None, depends: list[str] | None = None) -> dict:
    inputs: dict = {
        "sketch": {"id": "sketch.section",
                   "plane": {"on": "base", "plane": "YZ"},
                   "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 4.0},
                   "inner": [], "construction": [], "constraints": [], "dimensions": []},
        "path": path,
    }
    if cut_from:
        inputs["source_body"] = {"result": cut_from}
    return {"id": fid, "type": kind, "enabled": True, "depends_on": depends or [],
            "produces": ([{"id": "body.main", "kind": "solid_body"}]
                         if kind == "solid.sweep" else []),
            "inputs": inputs}


PLANAR_PATH = {"id": "path.spine", "plane": "XY",
               "segments": [{"type": "line", "start": [0.0, 0.0], "end": [40.0, 0.0]}]}
HELICAL_PATH = {"id": "path.helix", "plane": "XY", "pitch": 10.0, "height": 30.0,
                "radius": 20.0, "hand": "right"}
SPATIAL_PATH = {"id": "path.spine", "plane": "XY",
                "segments": [{"type": "line3", "start": [0.0, 0.0, 0.0],
                              "end": [40.0, 0.0, 0.0]}]}


def _document(features: list[dict]) -> dict:
    from cad_ir.canonical import CAD_IR_VERSION

    return validate_canonical({
        "schema": "cad-ai/cad-ir", "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "swept"},
        "parameters": [], "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": 1.0, "y": 1.0, "z": 1.0}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": 1},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    })


def test_a_swept_cut_asks_for_the_cut_key_whatever_kind_of_path_it_has():
    """The regression CAD-IR 1.14 introduced and 1.15 fixes.

    `feature.sweep.helix` was spliced into the middle of the `elif` chain that decides
    what a feature is, which broke the chain in two. The consequences were both silent:
    a **helical cut** required `feature.sweep.helix` and then never reached
    `need(CUT_SWEEP)` at all, so an operator who had switched swept cuts off would still
    have got one; and a plain solid sweep stopped counting towards `solids_so_far`, so a
    boss landing on a swept body no longer asked for `feature.boss.additive`.

    Neither was visible to the corpus, because the one helical case it carries is a
    solid sweep standing alone. Parametrising over both kinds of feature and all three
    kinds of path is what makes that impossible to reintroduce.
    """
    for path in (PLANAR_PATH, HELICAL_PATH, SPATIAL_PATH):
        solid = set(caps.requirements(_document([_sweep("solid.sweep", path)])))
        assert caps.SOLID_SWEEP in solid, path["id"]

        removed = set(caps.requirements(_document([
            _sweep("solid.sweep", PLANAR_PATH, "feature.blank"),
            _sweep("cut.sweep", path, "feature.groove", cut_from="body.main",
                   depends=["feature.blank"]),
        ])))
        assert caps.CUT_SWEEP in removed, path["id"]


def test_a_boss_landing_on_a_swept_body_is_still_a_boss():
    """The other half of the same break: a sweep is a solid, so what follows it is a boss."""
    features = [
        _sweep("solid.sweep", PLANAR_PATH),
        {"id": "feature.pad", "type": "solid.extrude", "enabled": True,
         "depends_on": ["feature.pipe"], "produces": [],
         "inputs": {
             "sketch": {"id": "sketch.pad", "plane": {"on": "base", "plane": "XY"},
                        "outer": {"type": "circle", "center": [0.0, 0.0], "radius": 3.0},
                        "inner": [], "construction": [], "constraints": [],
                        "dimensions": []},
             "direction": "+Z", "distance": 5.0}},
    ]
    assert caps.FEATURE_BOSS_ADDITIVE in set(caps.requirements(_document(features)))


def test_each_kind_of_path_asks_for_its_own_key():
    assert caps.FEATURE_SWEEP_SPATIAL_PATH in set(
        caps.requirements(_document([_sweep("solid.sweep", SPATIAL_PATH)]))
    )
    assert caps.FEATURE_SWEEP_SPATIAL_PATH not in set(
        caps.requirements(_document([_sweep("solid.sweep", PLANAR_PATH)]))
    )
    assert caps.FEATURE_SWEEP_HELIX_CONICAL not in set(
        caps.requirements(_document([_sweep("solid.sweep", HELICAL_PATH)]))
    )
    assert caps.FEATURE_SWEEP_HELIX_CONICAL in set(
        caps.requirements(_document([
            _sweep("solid.sweep", {**HELICAL_PATH, "cone_angle": 15.0})
        ]))
    )
