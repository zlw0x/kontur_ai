"""Repeat a feature: linear, circular, mirror.

A pattern is the first operation whose input is another *feature*, so this module
is mostly about re-deriving what that feature built and placing copies of it. The
tool it re-derives comes from the same function the original feature used
(`_extrude_tool`, `_revolve_tool`), because a pattern that rebuilt the geometry its
own way would be a second implementation of every operation it can repeat.

Two things are worth stating outright.

**Instance zero is already in the part.** The source feature ran before this one and
contributed its own position, so a pattern of six adds five. The instance list starts
at zero anyway — it is what a nested pattern needs, since a pattern of a pattern
places copies of *all* of the inner pattern's instances, the original included.

**A cut stays a cut.** The tool is a solid either way; whether it is added or
subtracted comes back from the source feature and each instance is combined the same
way it was. A pattern of a hole is five more holes, not a five-lump boss.
"""

from __future__ import annotations

import math
from typing import Callable

from build123d import Axis, Plane, Vector
from cad_ir.canonical import (
    CircularPattern,
    CutExtrudeFeature,
    CutRevolveFeature,
    DatumPlaneOffsetFeature,
    LinearPattern,
    MirrorPattern,
    PatternFeature,
    SolidExtrudeFeature,
    SolidRevolveFeature,
)

from .errors import CadEngineError, unsupported

#: The world direction each linear spelling names.
_DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}

#: The world axis each `axis.x` spelling names, as a direction.
_AXES = {"axis.x": (1.0, 0.0, 0.0), "axis.y": (0.0, 1.0, 0.0), "axis.z": (0.0, 0.0, 1.0)}

#: The base planes a mirror may name.
_PLANES = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}


def apply(feature: PatternFeature, part, planes: dict[str, Plane], params, sources, tool_of):
    """The part with every instance but the original added.

    `tool_of` is the adapter's tool-maker, passed in rather than imported: this
    module has to be able to ask for the solid of *any* feature a pattern can
    repeat, and the adapter is the thing that knows how to make each of them.
    """
    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} repeats {feature.inputs.of}, but nothing has been built.",
        )

    base, is_cut = _repeated(feature, part, planes, params, sources, tool_of)
    # The first placement is the original, which the source feature already put
    # there. A pattern of six adds five.
    for place in placements(feature, params)[1:]:
        part = _combined(part, place(base), is_cut)
    return part


def tool(feature: PatternFeature, part, planes: dict[str, Plane], params, sources, tool_of):
    """Everything this pattern contributes, as one solid, and how to combine it.

    Used when a *later* pattern repeats this one: a grid is a linear pattern of a
    linear pattern, so the outer one has to place copies of the inner one's whole
    output — the original instance included. That is the only reason this exists
    separately from `apply`, and it is why the instance list starts at zero.
    """
    base, is_cut = _repeated(feature, part, planes, params, sources, tool_of)
    whole = None
    for place in placements(feature, params):
        piece = place(base)
        whole = piece if whole is None else whole + piece
    return whole, is_cut


def _repeated(feature: PatternFeature, part, planes: dict[str, Plane], params, sources, tool_of):
    """The solid this pattern makes copies of, and whether it is removed.

    For a plain source that is the solid the source feature itself contributed. For a
    pattern it is everything *that* pattern contributed, which is what makes a grid a
    pattern of a pattern rather than a third operation.
    """
    source = sources.get(str(feature.inputs.of))
    if source is None:  # pragma: no cover - the canonical validator checks this
        raise CadEngineError(
            "FEATURE_RESULT_UNAVAILABLE",
            "feature",
            f"{feature.id} repeats {feature.inputs.of}, which the document does not declare.",
        )
    if isinstance(source, DatumPlaneOffsetFeature):
        raise unsupported(
            f"{feature.id} repeats {source.id}, which builds a plane rather than "
            "material. A pattern repeats an operation that adds or removes metal.",
            "feature",
        )
    if not source.enabled:  # pragma: no cover - the canonical validator checks this
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} repeats {source.id}, which the document has disabled.",
        )

    if isinstance(source, PatternFeature):
        return tool(source, part, planes, params, sources, tool_of)
    # Re-derived through the adapter's own tool-maker, so a pattern of an operation
    # is that operation and not a second implementation of it. A source whose sketch
    # sits on a selected face has its selector resolved again here, against the part
    # as it is now — which is the rule ADR-019 sets for every selector, and means a
    # pattern whose face has since become ambiguous fails rather than guesses.
    return tool_of(source, part, planes, params)


def placements(feature: PatternFeature, params) -> list[Callable]:
    """Where the instances go, the original first.

    A list of transforms rather than of solids, so the caller decides how many
    copies it actually needs — `apply` skips the first and a nested pattern does not.
    Skipped ordinals are dropped here, which is the one place that has to know they
    are ordinals of *this* pattern rather than of the finished part.
    """
    spec = feature.inputs.pattern
    skip = set(feature.inputs.skip)

    if isinstance(spec, LinearPattern):
        step = params.resolve(spec.spacing_mm, f"{feature.id} spacing")
        if step <= 0:
            raise CadEngineError(
                "DIMENSION_OUT_OF_RANGE",
                "feature",
                f"{feature.id} steps {step} mm; every instance would land on the original.",
            )
        direction = _DIRECTIONS.get(str(spec.direction))
        if direction is None:  # pragma: no cover - the enum is closed
            raise unsupported(f"Unknown pattern direction {spec.direction}.", "feature")
        offsets = [
            (direction[0] * step * index, direction[1] * step * index, direction[2] * step * index)
            for index in range(spec.count)
        ]
        return [
            _translation(offset)
            for index, offset in enumerate(offsets)
            if index not in skip
        ]

    if isinstance(spec, CircularPattern):
        step = params.resolve(spec.step_deg, f"{feature.id} step")
        if step == 0 or abs(step) >= 360:
            raise CadEngineError(
                "DIMENSION_OUT_OF_RANGE",
                "feature",
                f"{feature.id} turns {step}° between instances; that is not a step "
                "round a circle.",
            )
        axis = _circular_axis(spec, feature.id, params)
        return [
            _rotation(axis, step * index)
            for index in range(spec.count)
            if index not in skip
        ]

    if isinstance(spec, MirrorPattern):
        return [_identity, _reflection(_mirror_plane(spec, feature.id))]

    raise unsupported(  # pragma: no cover - the union is closed
        f"Unknown pattern {type(spec).__name__}.", "feature"
    )


def _circular_axis(spec: CircularPattern, feature_id: str, params) -> Axis:
    direction = _AXES.get(str(spec.axis))
    if direction is None:  # pragma: no cover - the enum is closed
        raise unsupported(f"Unknown pattern axis {spec.axis}.", "feature")
    through = [
        params.resolve(value, f"{feature_id} axis point") for value in spec.through
    ]
    return Axis(Vector(*through), Vector(*direction))


def _mirror_plane(spec: MirrorPattern, feature_id: str) -> Plane:
    """A base plane by name. A datum plane would need the build's plane table.

    Refused rather than half-supported: a mirror about a plane the engine could not
    find would otherwise fall back to a base plane and reflect about the wrong one,
    which is a part nobody can tell apart from the right one by reading the document.
    """
    name = str(spec.plane.result) if hasattr(spec.plane, "result") else str(spec.plane)
    plane = _PLANES.get(name)
    if plane is None:
        raise unsupported(
            f"{feature_id} mirrors about {name}. This engine mirrors about a base "
            "plane; a mirror about a datum plane is not built yet.",
            "feature",
        )
    return plane


def _identity(solid):
    return solid


def _translation(offset) -> Callable:
    if max(abs(value) for value in offset) == 0:
        return _identity
    return lambda solid: solid.translate(offset)


def _rotation(axis: Axis, angle: float) -> Callable:
    if math.fmod(angle, 360.0) == 0:
        return _identity
    return lambda solid: solid.rotate(axis, angle)


def _reflection(plane: Plane) -> Callable:
    return lambda solid: solid.mirror(plane)


def _combined(part, solid, is_cut: bool):
    """One instance, joined or removed, then cleaned like any other boolean.

    The same `clean()` the ordinary combine does, and for the same reason: two solids
    meeting exactly leave an internal face behind, and a body count is what notices.
    """
    combined = part - solid if is_cut else part + solid
    return combined.clean()


def repeats(feature: PatternFeature, sources) -> str:
    """What kind of thing this pattern repeats, for a message or a requirement."""
    source = sources.get(str(feature.inputs.of))
    if isinstance(source, (CutExtrudeFeature, CutRevolveFeature)):
        return "cut"
    if isinstance(source, (SolidExtrudeFeature, SolidRevolveFeature)):
        return "solid"
    if isinstance(source, PatternFeature):
        return repeats(source, sources)
    return "unknown"


__all__ = ["apply", "placements", "repeats", "tool"]
