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
base-plane sketches, a fixed set of **named selections**, and no constraints or
driving dimensions.

Rule 4 has no notion of an optional property, and for a long time that was read
as "a selector cannot be offered at all": a selector's predicates are
individually optional, so forcing the model to emit every one of them produces a
document the canonical validator rejects — a planar face has no radius.

That reading was too strong, and ADR-032 corrects it. Rule 4 governs the
properties a schema *declares*. Nothing obliges the profile to declare the whole
predicate vocabulary: a selection that declares three predicates and requires all
three is dialect-legal and canonically valid at once, because the predicates it
leaves out are optional in the canonical model. What could not be offered was the
vocabulary; a *fixed* set of predicates was always expressible.

So the profile offers selections rather than selectors — "the upright corners of
the outline", "the rims where holes break out of the top", "the face the part is
open at" — each written here against the topology this engine builds, each
exercised by the golden corpus, and each with nothing for the model to choose but
a count. Composing a selector is still not on offer, and that is the point.

Constraints and driving dimensions stay out for the original reason, which does
still hold: a constraint's `to` and `axis` are optional in a way no fixed choice
resolves, and forcing them would make every constraint binary and axial.

Revolve (CAD-IR 1.4), sweep and loft (1.9) are left out for a different reason,
and not because of the dialect. The drawing agent reads an outline and holes; a
turned section with its centre line, or a path with bend radii on an elevation,
are not things it can extract yet, so offering the operations would only invite a
model to invent one. Widening what is read off a scan is a vision problem, and
they wait for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
TARGET = ROOT / "schemas" / "cad-ir-mvp-output.schema.json"

sys.path.insert(0, str(ROOT / "packages" / "cad-ir"))

from cad_ir.canonical import CAD_IR_VERSION  # noqa: E402

# Taken from the contract rather than written here. A profile pinned to a version
# the contract has moved past is a schema that constrains the model to emit a
# document the validator will refuse — and the version is the one field where
# that failure is total rather than partial.
SCHEMA_ID = f"https://cad.example.com/schemas/cad-ir-mvp-output/{CAD_IR_VERSION}"

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
        # A scalar is a number, a named parameter, or one derived from a
        # parameter by the two operations CAD-IR 1.11 allows. `anyOf`, never
        # `oneOf`.
        #
        # Two separate defs rather than one node with an operator field: negation
        # takes one operand and division takes two, and rule 4 forbids an optional
        # property — the same reason `cut_extrusion` and `blind_cut_extrusion` are
        # two branches instead of one optional depth (ADR-029).
        #
        # They recurse back into `scalar`, which the canonical model bounds at
        # three levels. Nothing in the dialect forbids recursion; nothing else in
        # the profile uses it either.
        "scalar_quotient": obj(divide=ref("scalar"), by=number()),
        "scalar_negation": obj(negate=ref("scalar")),
        "scalar": {"anyOf": [
            number(),
            obj(parameter=ref("identifier")),
            ref("scalar_quotient"),
            ref("scalar_negation"),
        ]},
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
    def sketch_on(plane: dict[str, Any]) -> dict[str, Any]:
        return obj(
            id=ref("identifier"),
            plane=plane,
            outer=ref("contour"),
            inner=array(ref("contour"), 0, 32),
            construction=array(ref("construction_entity"), 0, 32),
            # Present and always empty. Rule 4 makes every property mandatory, so
            # the alternative to an empty array is a schema the model cannot satisfy.
            constraints=array(obj(), 0, 0),
            dimensions=array(obj(), 0, 0),
        )

    defs["sketch"] = sketch_on(obj(on=const("base"), plane=const("XY")))
    # The same sketch, on a plane an earlier feature built. This is what a boss
    # standing on a plate needs, and it costs the dialect nothing: a datum plane's
    # inputs are all mandatory, unlike a selector's predicates.
    defs["datum_sketch"] = sketch_on(obj(on=const("datum"), plane=obj(result=ref("identifier"))))

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
    # A hole that stops. Its own variant rather than an optional depth, because the
    # canonical validator refuses a cut that states both `through_all` and a
    # distance — the dialect's lack of optional properties and the contract's
    # exclusivity meet here, and two branches satisfy both.
    defs["blind_cut_extrusion"] = obj(
        id=ref("identifier"),
        type=const("cut.extrude"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(id=ref("identifier"), kind=const("face")), 0, 0),
        inputs=obj(
            sketch=ref("sketch"),
            direction=const("+Z"),
            through_all={"type": "boolean", "const": False},
            distance=ref("scalar"),
            source_body=obj(result=ref("identifier")),
        ),
    )
    # A plane parallel to XY, so a boss has somewhere to stand. Offset from the base
    # plane only: a plane on top of another plane is a stack this profile has no use
    # for, and every extra way to say the same thing is another way to say it wrong.
    defs["datum_plane"] = obj(
        id=ref("identifier"),
        type=const("datum.plane.offset"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(id=ref("identifier"), kind=const("plane")), 1, 1),
        inputs=obj(base=const("XY"), offset_mm=ref("scalar"), flip={"type": "boolean"}),
    )
    # Material added on that plane. It names no body and starts none, so it fuses
    # into the one being built — which is what a boss on a plate is (ADR-028).
    defs["boss_extrusion"] = obj(
        id=ref("identifier"),
        type=const("solid.extrude"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(id=ref("identifier"), kind=const("solid_body")), 0, 0),
        inputs=obj(
            sketch=ref("datum_sketch"),
            direction=const("+Z"),
            distance=ref("scalar"),
        ),
    )

    # --- named selections ---------------------------------------------------
    #
    # The dialect wall, and how it turned out to be passable (ADR-032).
    #
    # Rule 4 says every object lists *its own* properties as required. It does not say
    # a schema has to declare every property the canonical model allows — and a
    # selector's predicates are optional in the canonical model, so a profile that
    # declares three of them and requires all three is both dialect-legal and
    # canonically valid. What could not be offered was the predicate *vocabulary*; a
    # fixed set of predicates was always expressible, and nobody tried.
    #
    # So a selection is a named shape with nothing to choose but a count. The model
    # cannot compose a selector, which is the point: every one of these was written
    # here, against the topology this engine builds, and is exercised by the corpus.

    def selection(kind: str, where: dict[str, Any], counted: bool) -> dict[str, Any]:
        return obj(
            id=ref("identifier"),
            kind=const(kind),
            # The base extrusion is the only body this profile builds, so naming it is
            # a constant rather than a choice — one fewer thing to get wrong.
            from_result=const("body.main"),
            cardinality=(
                obj(type=const("exactly_n"),
                    value={"type": "integer", "minimum": 1, "maximum": 64})
                if counted
                else const("exactly_one")
            ),
            where=where,
        )

    # The upright edges of the outline, and only those: `convex` excludes the inside
    # of a hole, which is where "round the corners" would otherwise land.
    defs["outer_corner_edges"] = selection(
        "edge",
        obj(curve_type=const("line"),
            direction_parallel_to=const("axis.z"),
            convexity=const("convex")),
        counted=True,
    )
    # The rims where holes break out of the top face. Circular, so the upright edges
    # of the outline are not among them, and topmost, so the far side is not either.
    defs["bore_rim_edges"] = selection(
        "edge",
        obj(curve_type=const("circle"),
            position=obj(extreme_along=const("axis.z"), extreme=const("maximum"))),
        counted=True,
    )
    # The face a hollow part is open at, on a part that has one upward face.
    defs["top_face"] = selection(
        "face",
        obj(surface_type=const("planar"),
            normal=obj(parallel_to=const("axis.z"), direction=const("positive"))),
        counted=False,
    )
    # The same face on a part that has more than one, and the reason there are two
    # selections rather than one narrower one.
    #
    # A run on a flanged bushing stopped at `SELECTOR_AMBIGUOUS`: "planar face facing
    # +Z" found the flange's shoulder *and* the sleeve's end, and `exactly_one` cannot
    # choose. Narrowing the offer above to the topmost would have made every document
    # resolve — including the ones where the drawing shows the shoulder open, which
    # would then be a silent wrong part instead of a refusal. So the topmost is a
    # second named shape and the reading stage says which one the drawing shows.
    #
    # "The largest" is the third thing a drawing might mean and is deliberately not
    # here: a selector states an area as a *measurement*, so offering it would ask the
    # model for a number off the part rather than a shape off the drawing.
    defs["topmost_face"] = selection(
        "face",
        obj(surface_type=const("planar"),
            normal=obj(parallel_to=const("axis.z"), direction=const("positive")),
            position=obj(extreme_along=const("axis.z"), extreme=const("maximum"))),
        counted=False,
    )

    def blend(name: str, type_name: str, selector: str, size: str) -> None:
        defs[name] = obj(
            id=ref("identifier"),
            type=const(type_name),
            enabled={"type": "boolean"},
            depends_on=array(ref("identifier"), 1, 8),
            produces=array(obj(), 0, 0),
            inputs=obj(**{"edges": ref(selector), size: ref("scalar")}),
        )

    # `exactly_n` is what makes these safe to offer: a blend may not declare a
    # cardinality that permits zero matches (ADR-026), and stating the count is also
    # what gives the shape claim something to disagree with.
    blend("corner_fillet", "feature.fillet", "outer_corner_edges", "radius")
    blend("corner_chamfer", "feature.chamfer", "outer_corner_edges", "distance")
    blend("bore_chamfer", "feature.chamfer", "bore_rim_edges", "distance")

    # Hollow, inward, open at the top. `direction` is a constant rather than a choice:
    # an outward wall changes the part's overall size, and a drawing that means one
    # says so in dimensions the reading stage has no word for yet (ADR-030).
    defs["hollow"] = obj(
        id=ref("identifier"),
        type=const("feature.shell"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(), 0, 0),
        inputs=obj(
            # Either named shape, and nothing else. `anyOf` rather than a widened
            # predicate set: the model picks between two selections written here, which
            # is the whole of what ADR-032 permits it to do.
            faces={"anyOf": [ref("top_face"), ref("topmost_face")]},
            thickness=ref("scalar"),
            direction=const("inward"),
        ),
    )

    # Patterns are the first operation the reading stage can genuinely ask for: six
    # holes on a bolt circle is something a drawing shows and a shape claim carries,
    # and every field of a pattern is mandatory, so the dialect can express it
    # (ADR-027). `skip` is present and empty for the same reason `constraints` is.
    defs["linear_pattern"] = obj(
        id=ref("identifier"),
        type=const("feature.pattern"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(), 0, 0),
        inputs=obj(
            of=ref("identifier"),
            pattern=obj(
                kind=const("linear"),
                direction=enum("+X", "-X", "+Y", "-Y"),
                spacing_mm=ref("scalar"),
                count={"type": "integer", "minimum": 2, "maximum": 200},
            ),
            skip=array({"type": "integer"}, 0, 0),
        ),
    )
    defs["circular_pattern"] = obj(
        id=ref("identifier"),
        type=const("feature.pattern"),
        enabled={"type": "boolean"},
        depends_on=array(ref("identifier"), 1, 8),
        produces=array(obj(), 0, 0),
        inputs=obj(
            of=ref("identifier"),
            pattern=obj(
                kind=const("circular"),
                axis=const("axis.z"),
                through=array(ref("scalar"), 3, 3),
                step_deg=ref("scalar"),
                count={"type": "integer", "minimum": 2, "maximum": 200},
            ),
            skip=array({"type": "integer"}, 0, 0),
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
        features=array(
            {
                "anyOf": [
                    ref("base_extrusion"),
                    ref("cut_extrusion"),
                    ref("blind_cut_extrusion"),
                    ref("datum_plane"),
                    ref("boss_extrusion"),
                    ref("linear_pattern"),
                    ref("circular_pattern"),
                    ref("corner_fillet"),
                    ref("corner_chamfer"),
                    ref("bore_chamfer"),
                    ref("hollow"),
                ]
            },
            1,
            20,
        ),
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
