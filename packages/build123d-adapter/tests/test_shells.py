"""Shell, on real geometry.

POSTMVP-017. The golden corpus already builds five shells and measures their
arithmetic; what is here is the rest — the two measurements that justify decisions
the contract makes, and the failures that produce a plausible part rather than an
error.

The measurement worth having in a test rather than in a comment is the one about
`offset` with nothing open. It is the reason CAD-IR refuses a cardinality that
permits zero matches, and a reason that lives only in prose is a reason that stops
being checked.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

pytest.importorskip("build123d", reason="the CAD engine is not installed")

from cad_ir.canonical import CAD_IR_VERSION  # noqa: E402
from cad_ir.canonical_validator import validate_canonical  # noqa: E402
from cad_ir.errors import CadIrValidationError  # noqa: E402

from cad_engine_build123d.adapter import build_part  # noqa: E402
from cad_engine_build123d.errors import CadEngineError  # noqa: E402
from cad_engine_build123d.shells import shell  # noqa: E402

WIDTH, HEIGHT, DEPTH = 100.0, 60.0, 40.0
WALL = 3.0


def sketch(name: str, outer: dict) -> dict[str, Any]:
    return {"id": f"sketch.{name}", "plane": {"on": "base", "plane": "XY"},
            "outer": outer, "inner": [], "construction": [], "constraints": [],
            "dimensions": []}


def rectangle(width: float, height: float, centre=(0.0, 0.0)) -> dict[str, Any]:
    return {"type": "rectangle", "center": list(centre), "width": width,
            "height": height, "rotation_deg": 0.0}


def block(fid: str, body: str, outer: dict, depends: list[str] | None = None,
          new_body: bool = False) -> dict[str, Any]:
    inputs: dict[str, Any] = {"sketch": sketch(fid.split(".")[-1], outer),
                              "direction": "+Z", "distance": DEPTH}
    if new_body:
        inputs["new_body"] = True
    return {"id": fid, "type": "solid.extrude", "enabled": True,
            "depends_on": depends or [], "produces": [{"id": body, "kind": "solid_body"}],
            "inputs": inputs}


def hollow(body: str = "body.main", thickness: Any = WALL, direction: str = "inward",
           cardinality: Any = "exactly_one", depends: str = "feature.block") -> dict[str, Any]:
    return {
        "id": "feature.hollow", "type": "feature.shell", "enabled": True,
        "depends_on": [depends], "produces": [],
        "inputs": {
            "faces": {"id": "selector.top", "kind": "face", "from_result": body,
                      "cardinality": cardinality,
                      "where": {"surface_type": "planar",
                                "normal": {"parallel_to": "axis.z",
                                           "direction": "positive"}}},
            "thickness": thickness, "direction": direction,
        },
    }


def document(features: list[dict], parameters: list[dict] | None = None,
             bodies: int = 1) -> dict[str, Any]:
    return {
        "schema": "cad-ai/cad-ir", "schema_version": CAD_IR_VERSION,
        "document": {"units": "mm", "part_type": "single_part",
                     "coordinate_system": "right_handed", "name": "enclosure"},
        "parameters": parameters or [],
        "features": features,
        "expectations": [
            {"id": "inv.box", "type": "bounding_box",
             "size_mm": {"x": WIDTH, "y": HEIGHT, "z": DEPTH}, "tolerance_mm": 0.05},
            {"id": "inv.bodies", "type": "body_count", "value": bodies},
        ],
        "metadata": {"generator": "test", "generator_version": "1"},
    }


def enclosure(**kwargs) -> dict[str, Any]:
    return document([block("feature.block", "body.main", rectangle(WIDTH, HEIGHT)),
                     hollow(**kwargs)])


def built(value: dict):
    return build_part(validate_canonical(value))


def size(part) -> tuple[float, float, float]:
    box = part.bounding_box().size
    return (round(box.X, 6), round(box.Y, 6), round(box.Z, 6))


def test_a_shelled_box_keeps_its_outside_and_loses_its_inside():
    """The whole operation, in the two numbers that describe it.

    The outer size is the drawing's, unchanged — which is exactly why nothing that
    measures the outside can tell a shelled part from a solid one — and the volume is
    the box minus a cavity one wall short on four sides and one on the floor.
    """
    part = built(enclosure())

    assert size(part) == (WIDTH, HEIGHT, DEPTH)
    cavity = (WIDTH - 2 * WALL) * (HEIGHT - 2 * WALL) * (DEPTH - WALL)
    assert float(part.volume) == pytest.approx(WIDTH * HEIGHT * DEPTH - cavity, abs=1e-6)

    # Five outer walls, five inner ones and the rim between them, where a solid box
    # has six faces. This is the one expectation in the contract that can see a shell.
    planar = [face for face in part.faces() if str(face.geom_type) == "GeomType.PLANE"]
    assert len(planar) == 11


def test_an_offset_that_opens_nothing_shrinks_the_solid_instead_of_hollowing_it():
    """Why a shell may not declare a cardinality that permits zero matches.

    `offset` is two operations wearing one name, and the list of open faces is what
    decides which. With nothing open it is not a hollow box that failed to open — it
    is a *smaller solid box*, 2t less in every direction, and the only check in a
    document that would notice is a bounding box somebody remembered to state.

    Measured against build123d directly, because the contract's rule is a claim about
    what this kernel does and a claim like that has to be checked against the kernel.
    """
    from build123d import Box, Kind, offset

    box = Box(WIDTH, HEIGHT, DEPTH)
    shrunk = offset(box, amount=-WALL, openings=None, kind=Kind.INTERSECTION)

    assert float(shrunk.volume) == pytest.approx(
        (WIDTH - 2 * WALL) * (HEIGHT - 2 * WALL) * (DEPTH - 2 * WALL), abs=1e-6
    )
    assert len(shrunk.faces()) == 6  # a solid, not a shell

    # And the contract refuses to let a document ask for it.
    for cardinality in ("all", "zero_or_one", {"type": "exactly_n", "value": 0}):
        with pytest.raises(CadIrValidationError):
            validate_canonical(enclosure(cardinality=cardinality))


def test_a_wall_thicker_than_the_material_is_refused_rather_than_returned_solid():
    """The kernel's answer here is the part it was given, with no error at all.

    A 30 mm wall in a part 60 mm across has the two walls meeting before they leave
    a cavity. OpenCascade returns the original solid — same volume, same bounding box,
    same body count, same hole count — so the document builds, verifies and is a
    billet. Nothing but a comparison of the volume before and after catches it.
    """
    with pytest.raises(CadEngineError) as raised:
        built(enclosure(thickness=30.0))

    assert raised.value.code == "SHELL_NO_CAVITY"
    assert "removes no material" in raised.value.safe_message


def test_the_direction_is_the_difference_between_two_different_parts():
    """Same faces, same thickness, and a part 6 mm bigger in x and y.

    Which is why the direction is stated rather than defaulted quietly at the kernel:
    the sign of a number is not something a drawing agent should be able to omit.
    """
    inward = built(enclosure())
    outward = built(enclosure(direction="outward"))

    assert size(inward) == (WIDTH, HEIGHT, DEPTH)
    # No wall on the open face, so it grows by t upwards and 2t across.
    assert size(outward) == (WIDTH + 2 * WALL, HEIGHT + 2 * WALL, DEPTH + WALL)
    assert float(outward.volume) == pytest.approx(
        (WIDTH + 2 * WALL) * (HEIGHT + 2 * WALL) * (DEPTH + WALL) - WIDTH * HEIGHT * DEPTH,
        abs=1e-6,
    )


def test_a_shell_hollows_the_body_its_selector_names_and_leaves_the_other_alone():
    """`from_result` decides, as it does for a blend (ADR-028).

    Two blocks, one hollowed. The finished compound is one solid billet and one shell,
    and the sum says which of them was which.
    """
    value = document(
        [
            block("feature.block", "body.main", rectangle(WIDTH, HEIGHT)),
            block("feature.spacer", "body.spacer",
                  rectangle(WIDTH, HEIGHT, (2 * WIDTH, 0.0)),
                  depends=["feature.block"], new_body=True),
            hollow(),
        ],
        bodies=2,
    )
    part = build_part(validate_canonical(value))

    solids = part.solids()
    assert len(solids) == 2
    cavity = (WIDTH - 2 * WALL) * (HEIGHT - 2 * WALL) * (DEPTH - WALL)
    assert float(part.volume) == pytest.approx(2 * WIDTH * HEIGHT * DEPTH - cavity, abs=1e-6)


def test_a_wall_stated_as_a_parameter_is_the_wall_that_gets_built():
    """The one path the corpus does not take: a thickness that is a name.

    A literal wall is checked by the contract before the engine ever sees it. A named
    one is a promise about a number that arrives here, and this is where the promise
    is kept — or, when the parameter says 0, refused.
    """
    def with_wall(value: float) -> dict[str, Any]:
        return document(
            [block("feature.block", "body.main", rectangle(WIDTH, HEIGHT)),
             hollow(thickness={"parameter": "p_wall"})],
            parameters=[{"id": "p_wall", "type": "length", "unit": "mm",
                         "value": value, "status": "confirmed"}],
        )

    part = built(with_wall(2.0))
    cavity = (WIDTH - 4.0) * (HEIGHT - 4.0) * (DEPTH - 2.0)
    assert float(part.volume) == pytest.approx(WIDTH * HEIGHT * DEPTH - cavity, abs=1e-6)

    with pytest.raises(CadEngineError) as raised:
        built(with_wall(0.0))
    assert raised.value.code == "DIMENSION_OUT_OF_RANGE"


def test_a_shell_with_nothing_built_says_so_rather_than_crashing():
    """The branch the contract makes unreachable, kept because it is cheap.

    A document whose selector names a body no feature builds is refused by
    `FEATURE_RESULT_UNAVAILABLE` before the engine runs, so this is reached only by
    calling the operation directly. An `AttributeError` on `None` would be the same
    fact reported as a bug in the engine.
    """
    feature = validate_canonical(enclosure()).features[1]

    with pytest.raises(CadEngineError) as raised:
        shell(feature, None, params=None)
    assert raised.value.code == "UNSUPPORTED_FEATURE_SET"


def test_a_cup_is_a_cylinder_with_its_middle_taken_out():
    """A curved wall, where the inner surface is a second cylinder rather than a plane.

    Worth its own case because a box shell is entirely planar, and the operation that
    matters on a turned part is the one that has to offset a curve.
    """
    radius, tall, wall = 20.0, 50.0, 2.0
    value = document([
        {"id": "feature.block", "type": "solid.extrude", "enabled": True,
         "depends_on": [], "produces": [{"id": "body.main", "kind": "solid_body"}],
         "inputs": {"sketch": sketch("disc", {"type": "circle", "center": [0.0, 0.0],
                                              "radius": radius}),
                    "direction": "+Z", "distance": tall}},
        hollow(thickness=wall),
    ])
    value["expectations"][0]["size_mm"] = {"x": 2 * radius, "y": 2 * radius, "z": tall}
    part = build_part(validate_canonical(value))

    assert float(part.volume) == pytest.approx(
        math.pi * radius**2 * tall - math.pi * (radius - wall) ** 2 * (tall - wall), abs=1e-6
    )
    cylinders = [f for f in part.faces() if str(f.geom_type) == "GeomType.CYLINDER"]
    assert len(cylinders) == 2  # the bore and the outside


def test_the_shell_is_applied_to_the_part_as_it_is_when_the_feature_runs():
    """Order matters, and the document's order is the one that is used.

    A hole cut before the shell is a hole through a wall; the same hole cut after is a
    hole through a wall too — but the *cavity* differs, because the second document
    hollows a plate that still has its material. Stated as a test because "resolved
    against the part at this point in the sequence" is otherwise a comment.
    """
    bore = {"id": "feature.bore", "type": "cut.extrude", "enabled": True,
            "depends_on": ["feature.block"], "produces": [],
            "inputs": {"sketch": sketch("bore", {"type": "circle", "center": [0.0, 0.0],
                                                 "radius": 10.0}),
                       "direction": "+Z", "through_all": True,
                       "source_body": {"result": "body.main"}}}

    before = copy.deepcopy(document(
        [block("feature.block", "body.main", rectangle(WIDTH, HEIGHT)), bore,
         {**hollow(), "depends_on": ["feature.block", "feature.bore"]}]))
    after = copy.deepcopy(document(
        [block("feature.block", "body.main", rectangle(WIDTH, HEIGHT)), hollow(),
         {**bore, "depends_on": ["feature.block", "feature.hollow"]}]))

    assert float(built(before).volume) != pytest.approx(float(built(after).volume), abs=1e-3)


# --- the fixture -----------------------------------------------------------


def enclosure_fixture() -> dict:
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "cad-ir"
    return json.loads((fixtures / "enclosure.v1_8.json").read_text("utf-8"))


def test_the_enclosure_fixture_is_the_arithmetic_of_its_drawing():
    """A hollow part with a rounded outline, a floor and two mounting holes.

    Every number closed-form from the drawing, and the one worth spelling out is the
    inner corner radius: offsetting a rounded outline inward by t leaves arcs of
    `R − t`, so the cavity's cross-section is the outer one shrunk by t on every side
    *and* rounded 3 mm tighter. A shell that used the outer radius inside would be
    138 mm³ out — which is the kind of difference nothing but arithmetic notices.

        outer area   120·80 − 4(1 − π/4)·10²        = 9 585.8407
        inner area   114·74 − 4(1 − π/4)·7²         = 8 393.8620
        volume       9 585.8407·40 − 8 393.8620·37 − 2·π·3²·3
    """
    part = build_part(validate_canonical(enclosure_fixture()))

    outer = 120.0 * 80.0 - 4 * (1 - math.pi / 4) * 10.0**2
    inner = 114.0 * 74.0 - 4 * (1 - math.pi / 4) * 7.0**2
    expected = outer * 40.0 - inner * 37.0 - 2 * math.pi * 3.0**2 * 3.0

    assert float(part.volume) == pytest.approx(expected, abs=1e-6)
    assert size(part) == (120.0, 80.0, 40.0)

    radii = sorted(round(face.radius, 3) for face in part.faces()
                   if str(face.geom_type) == "GeomType.CYLINDER")
    assert radii == [3.0, 3.0, 7.0, 7.0, 7.0, 7.0, 10.0, 10.0, 10.0, 10.0]


def test_the_enclosure_fixture_verifies_after_a_round_trip_through_step_and_stl():
    """Reopened and measured, not read back off the plan that built it (ADR-018).

    Both of its `surface_face_count` expectations are about the shell: four arcs at
    the stated radius outside and four at `R − wall` inside. A shell that did not
    happen has the first four and none of the second.
    """
    import tempfile
    from pathlib import Path

    from cad_engine_build123d.adapter import _export
    from cad_engine_build123d.verify import Expectations, verify

    document = validate_canonical(enclosure_fixture())
    directory = Path(tempfile.mkdtemp())
    _export(build_part(document), directory)
    report = verify(directory / "model.step", directory / "model.stl",
                    Expectations.of(document))

    assert report.valid, [item for item in report.checks if not item.passed]
    named = {item.name for item in report.checks}
    assert "surface_face_count[inv_inner_corners]" in named
