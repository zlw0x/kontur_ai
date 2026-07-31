"""Build the schema Codex is constrained by, in the dialect it accepts.

Generated rather than hand-maintained because the dialect has one rule with
teeth — every object must list *all* of its properties as required — and
keeping that true by hand across a nested schema is how a full AI run gets
spent discovering it was not.

    python scripts/generate_output_profile.py [--check]

The rules, derived on 2026-07-28 from the 0.1.0 schema the API had been
accepting for months and from three real rejections that each cost an AI run:

  1. no `oneOf` (use `anyOf`)
  2. every schema node declares a `type`
  3. every array declares `items`
  4. every object lists all its properties as required
  5. every object sets `additionalProperties: false`

This profile is deliberately narrower than the canonical schema. It offers
base-plane sketches only, and no constraints or driving dimensions.

The reason is the same in every case: rule 4 has no notion of an optional
property. A selector's predicates are individually optional, so the model would
be forced to emit every one of them — and the canonical validator then rejects
the result, because a planar face has no radius. A constraint's `to` and `axis`
are optional in exactly the same way, and forcing them would make every
constraint binary and axial. A schema that cannot express optionality must not
be handed a model that needs it.

Auxiliary planes, face selectors, constraints and driving dimensions all reach
the adapter through the manual API instead.

Revolve (CAD-IR 1.4) is left out for a different reason, and not because of the
dialect. The drawing agent reads a rectangle and round holes; a turned profile and
the centre line it goes round are not something it can extract yet, so offering
the operation would only invite a model to invent one. Widening what is read off a
scan is a vision problem, and the operation waits for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
TARGET = ROOT / "schemas" / "cad-ir-mvp-output.schema.json"

SCHEMA_ID = "https://cad.example.com/schemas/cad-ir-mvp-output/1.4"
CAD_IR_VERSION = "1.4"

MAX_COORDINATE = 1_000_000


def obj(**properties: Any) -> dict[str, Any]:
    """An object node with rules 4 and 5 applied by construction."""
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }


def const(value: str) -> dict[str, Any]:
    return {"type": "string", "const": value}


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def number(minimum: float = -MAX_COORDINATE, maximum: float = MAX_COORDINATE) -> dict[str, Any]:
    return {"type": "number", "minimum": minimum, "maximum": maximum}


def array(items: dict[str, Any], minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def build() -> dict[str, Any]:
    defs: dict[str, Any] = {
        "identifier": {"type": "string", "pattern": r"^[a-z][a-z0-9_.-]{1,63}$"},
        # A scalar is a number or a named parameter. `anyOf`, never `oneOf`.
        "scalar": {"anyOf": [number(), obj(parameter=ref("identifier"))]},
        "point": array(ref("scalar"), 2, 2),
    }

    defs["line_segment"] = obj(
        type=const("line"), start=ref("point"), end=ref("point")
    )
    defs["arc_segment"] = obj(
        type=const("arc"),
        start=ref("point"),
        end=ref("point"),
        center=ref("point"),
        sweep=enum("ccw", "cw"),
    )
    defs["path_segment"] = {"anyOf": [ref("line_segment"), ref("arc_segment")]}

    defs["path_contour"] = obj(
        type=const("path"), segments=array(ref("path_segment"), 2, 200)
    )
    defs["circle_contour"] = obj(
        type=const("circle"), center=ref("point"), radius=ref("scalar")
    )
    defs["rectangle_contour"] = obj(
        type=const("rectangle"),
        center=ref("point"),
        width=ref("scalar"),
        height=ref("scalar"),
        rotation_deg=ref("scalar"),
    )
    defs["slot_contour"] = obj(
        type=const("slot"), start=ref("point"), end=ref("point"), radius=ref("scalar")
    )
    defs["regular_polygon_contour"] = obj(
        type=const("regular_polygon"),
        center=ref("point"),
        sides={"type": "integer", "minimum": 3, "maximum": 64},
        circumradius=ref("scalar"),
        rotation_deg=ref("scalar"),
    )
    defs["contour"] = {
        "anyOf": [
            ref("path_contour"),
            ref("circle_contour"),
            ref("rectangle_contour"),
            ref("slot_contour"),
            ref("regular_polygon_contour"),
        ]
    }

    # Construction geometry is offered because a drawing's centre lines and
    # bolt-circle centres are worth recording even before anything constrains
    # against them.
    defs["construction_point"] = obj(
        type=const("point"), id=ref("identifier"), at=ref("point")
    )
    defs["construction_line"] = obj(
        type=const("line"), id=ref("identifier"), start=ref("point"), end=ref("point")
    )
    defs["construction_circle"] = obj(
        type=const("circle"), id=ref("identifier"), center=ref("point"), radius=ref("scalar")
    )
    defs["construction_entity"] = {
        "anyOf": [
            ref("construction_point"),
            ref("construction_line"),
            ref("construction_circle"),
        ]
    }

    # The XY base plane only: this adapter extrudes along +Z from XY, so
    # offering XZ or YZ would invite geometry it refuses.
    defs["sketch"] = obj(
        id=ref("identifier"),
        plane=obj(on=const("base"), plane=const("XY")),
        outer=ref("contour"),
        inner=array(ref("contour"), 0, 32),
        construction=array(ref("construction_entity"), 0, 32),
        # Present and always empty. Rule 4 makes every property mandatory, so
        # the alternative to an empty array is a schema the model cannot satisfy.
        constraints=array(obj(), 0, 0),
        dimensions=array(obj(), 0, 0),
    )

    defs["base_extrusion"] = obj(
        id=ref("identifier"),
        type=const("solid.extrude"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 0, 0),
        produces=array(obj(id=ref("identifier"), kind=const("solid_body")), 1, 1),
        inputs=obj(
            sketch=ref("sketch"),
            direction=const("+Z"),
            distance=ref("scalar"),
        ),
    )
    defs["cut_extrusion"] = obj(
        id=ref("identifier"),
        type=const("cut.extrude"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(id=ref("identifier"), kind=const("face")), 0, 0),
        inputs=obj(
            sketch=ref("sketch"),
            direction=const("+Z"),
            through_all={"type": "boolean", "const": True},
            source_body=obj(result=ref("identifier")),
        ),
    )

    defs["bounding_box_expectation"] = obj(
        id=ref("identifier"),
        type=const("bounding_box"),
        size_mm=obj(
            x={"type": "number", "exclusiveMinimum": 0},
            y={"type": "number", "exclusiveMinimum": 0},
            z={"type": "number", "exclusiveMinimum": 0},
        ),
        tolerance_mm={"type": "number", "minimum": 0, "maximum": 100},
    )
    defs["count_expectation"] = obj(
        id=ref("identifier"),
        type=enum("body_count", "through_hole_count"),
        value={"type": "integer", "minimum": 0, "maximum": 1000},
    )

    document = obj(
        schema=const("cad-ai/cad-ir"),
        schema_version=const(CAD_IR_VERSION),
        document=obj(
            units=const("mm"),
            part_type=const("single_part"),
            coordinate_system=const("right_handed"),
            name={"type": "string", "maxLength": 100},
        ),
        parameters=array(
            obj(
                id=ref("identifier"),
                type=const("length"),
                value=number(),
                unit=const("mm"),
                name={"type": "string", "maxLength": 100},
                status=enum("confirmed", "user_confirmed", "inferred", "assumed"),
                provenance=obj(confidence={"type": "number", "minimum": 0, "maximum": 1}),
            ),
            1,
            64,
        ),
        features=array({"anyOf": [ref("base_extrusion"), ref("cut_extrusion")]}, 1, 20),
        expectations=array(
            {"anyOf": [ref("bounding_box_expectation"), ref("count_expectation")]}, 2, 8
        ),
        reference_geometry=array(obj(), 0, 0),
        metadata=obj(
            generator={"type": "string", "maxLength": 100},
            generator_version={"type": "string", "maxLength": 50},
            prompt_version={"type": "string", "maxLength": 50},
        ),
    )

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": f"CAD-IR {CAD_IR_VERSION}, narrowed to the geometry this build can construct",
        "description": (
            "A subset of the canonical CAD-IR schema, expressed in the dialect the Codex "
            "structured-output API accepts: anyOf rather than oneOf, every node typed, every "
            "array with items, and every object listing all of its properties as required. The "
            "canonical schema says what version 1.2 can express; this says what may be generated, "
            "so the model is constrained at generation time instead of being corrected by a repair "
            "loop. Auxiliary planes and face selectors are part of 1.2 but not offered here: a "
            "selector's predicates are individually optional, and a dialect without optional "
            "properties would force the model to emit predicates the trusted validator rejects. "
            "Semantics the dialect cannot state — that a contour closes, for instance — are "
            "enforced by the adapter before anything reaches KOMPAS."
        ),
        **document,
        "$defs": defs,
    }


def main() -> int:
    content = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print(f"stale: {TARGET.relative_to(ROOT).as_posix()}", file=sys.stderr)
            return 1
        print("up to date: cad-ir-mvp-output.schema.json")
        return 0
    TARGET.write_text(content, encoding="utf-8", newline="")
    print(f"generated: {TARGET.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
