"""Fillet and chamfer: the operations that only name geometry.

Everything before this built a solid from a profile. A blend takes the solid that
exists and modifies the edges a selector named, so this module is mostly about the
naming and about what the kernel does when the naming is wrong.

Three things are checked here rather than left to OpenCascade.

*How many edges the selector matched.* The selector contract already decides that
(ADR-019) and CAD-IR 1.5 forbids a blend from declaring a cardinality that permits
zero. What this adds is the trace: a blend that matched nothing fails with the
narrowing that got it there, because "no match" alone does not say which clause was
wrong.

*That the edges are edges of the part.* A seam is dropped by the resolver, so a
blend never sees one. Named here because a chamfer of a seam is the failure that
looks most like a kernel bug and is really a contract question.

*That an asymmetric chamfer's reference face contains the edges it measures from.*
build123d refuses this too — "Some edges are not part of the face" — but as a
`ValueError` with nothing about the document in it. Ours names the selector.

The kernel's own refusals are wrapped rather than swallowed. An oversized fillet
radius comes back as `ValueError: Failed creating a fillet with radius of 5`, which
is a true statement about a document that asked for a 5 mm round on a 6 mm plate,
and a caller that received it as a crash would have to parse prose to find out.
"""

from __future__ import annotations

from build123d import chamfer as _chamfer
from build123d import fillet as _fillet
from cad_ir.canonical import ChamferFeature, FilletFeature

from .errors import CadEngineError
from .selectors import narrowing, require_one, resolve_edges, resolve_faces
from .topology import read_edges, read_faces


def blend(feature, part, params):
    """The part with `feature` applied, or a typed refusal.

    One entry point for both operations because everything except the call itself
    is shared, and two copies of the selector handling would be two places for the
    seam rule to drift.
    """
    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} blends edges, but nothing has been built for it to blend.",
        )

    edges = _edges(feature, part)
    if isinstance(feature, FilletFeature):
        radius = _positive(params, feature.inputs.radius, f"{feature.id} radius")
        return _apply(
            lambda: _fillet(edges, radius),
            feature,
            f"a fillet of radius {radius} mm on {len(edges)} edge(s)",
        )

    if isinstance(feature, ChamferFeature):
        return _chamfer_feature(feature, part, params, edges)

    raise CadEngineError(  # pragma: no cover - the dispatch above is exhaustive
        "UNSUPPORTED_FEATURE", "feature", f"{feature.type} is not a blend."
    )


def _chamfer_feature(feature: ChamferFeature, part, params, edges):
    inputs = feature.inputs
    distance = _positive(params, inputs.distance, f"{feature.id} distance")
    second = (
        None
        if inputs.second_distance is None
        else _positive(params, inputs.second_distance, f"{feature.id} second distance")
    )
    angle = (
        None
        if inputs.angle_deg is None
        else params.resolve(inputs.angle_deg, f"{feature.id} angle")
    )
    if angle is not None and not 0 < angle < 90:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            f"{feature.id} chamfers at {angle}°; the angle is more than 0 and less than 90.",
        )

    reference = None
    if inputs.measured_from is not None:
        reference = _reference_face(inputs.measured_from, part, edges, feature.id)

    described = f"a {distance} mm chamfer on {len(edges)} edge(s)"
    return _apply(
        lambda: _chamfer(edges, distance, length2=second, angle=angle, reference=reference),
        feature,
        described,
    )


def _edges(feature, part):
    """The kernel edges the feature's selector names.

    The resolver drops seams and applies the predicates; the cardinality was
    already narrowed by CAD-IR 1.5 to something that cannot match nothing. What is
    left is to turn a resolution into handles, or to fail with the trace.
    """
    selector = feature.inputs.edges
    resolution = resolve_edges(selector, read_edges(part))
    if not resolution.satisfied or not resolution.matched:
        raise CadEngineError(
            resolution.failure_code or "SELECTOR_NO_MATCH",
            "selector",
            f"Selector {selector.id} named {len(resolution.matched)} edge(s) for "
            f"{feature.id}, which its declared cardinality does not allow. "
            + narrowing(resolution),
        )
    return [descriptor.handle for descriptor in resolution.matched]


def _reference_face(selector, part, edges, feature_id: str):
    """The face an asymmetric chamfer's first distance is measured on.

    Checked to contain every edge being chamfered, because the kernel's version of
    this check raises a `ValueError` about faces and edges with no mention of the
    document. A document whose reference face does not touch the edges it measures
    from has said something about a part that does not exist, and it should read
    like that.
    """
    face = require_one(resolve_faces(selector, read_faces(part)), selector).handle
    on_face = {_edge_key(edge) for edge in face.edges()}
    stray = [edge for edge in edges if _edge_key(edge) not in on_face]
    if stray:
        raise CadEngineError(
            "SELECTOR_NO_MATCH",
            "selector",
            f"{feature_id} measures from the face {selector.id} names, but "
            f"{len(stray)} of the {len(edges)} edge(s) it chamfers are not on that face. "
            "A distance can only be measured along a face the edge belongs to.",
        )
    return face


def _edge_key(edge) -> tuple:
    """An edge's identity by where it is, matching `topology._edge_key`.

    Two `Edge` wrappers around the same curve are different Python objects, so
    membership has to be decided geometrically.
    """
    start = edge.position_at(0.0)
    end = edge.position_at(1.0)
    ends = sorted(
        [
            (round(start.X, 6), round(start.Y, 6), round(start.Z, 6)),
            (round(end.X, 6), round(end.Y, 6), round(end.Z, 6)),
        ]
    )
    return (round(float(edge.length), 6), ends[0], ends[1])


def _positive(params, value, what: str) -> float:
    """Resolve a size and insist it is positive.

    CAD-IR checks a literal; this is where a parameter reference is checked, and it
    is the only place it can be — the document says `{"parameter": "fillet_radius"}`
    and the number arrives here.
    """
    resolved = params.resolve(value, what)
    if resolved <= 0:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE", "feature", f"{what} is {resolved}; it must be positive."
        )
    return resolved


def _apply(call, feature, described: str):
    """Run the kernel call, and turn its refusal into something typed.

    A blend is the operation most likely to be refused for a reason that is really
    about the document — a radius larger than the material it is rounding — so the
    kernel's message is kept and framed rather than replaced.
    """
    try:
        result = call()
    except CadEngineError:
        raise
    except Exception as error:  # noqa: BLE001 - the kernel raises ValueError and worse
        raise CadEngineError(
            "BLEND_FAILED",
            "feature",
            f"{feature.id} asks for {described}, and the kernel refused it: {error}. "
            "A blend cannot remove more material than the edge has on either side.",
        ) from error
    if result is None:
        raise CadEngineError(
            "BLEND_FAILED", "feature", f"{feature.id} asks for {described} and produced nothing."
        )
    return result


__all__ = ["blend"]
