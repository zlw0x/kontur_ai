"""Shell: hollow the body, and open the faces the document names.

The kernel call is one line. Everything else in this module is there because
OpenCascade's `offset` is *two* operations wearing one name, and which one it
performs depends on whether the list of open faces is empty.

    offset(solid, -3, openings=[top])   a 3 mm wall, open at the top
    offset(solid, -3, openings=[])      the same solid, 6 mm smaller in every direction

Measured on a 100 × 60 × 40 box: the first gives 52 188 mm³ and keeps the bounding
box; the second gives 172 584 mm³ — which is 94 × 54 × 34, a solid block. So a
selector that matched no faces does not leave the part alone, and CAD-IR 1.8 refuses
the cardinalities that permit it before the document reaches here.

The second measured surprise is why this module checks the result rather than
trusting the call. A wall thicker than the material has room for **does not fail**:
30 mm inward on that same box comes back as 240 000 mm³ — the original solid, whole,
with no cavity at all and no error raised. Every check in the document passes it. The
bounding box is right, the body count is right, the hole count is right, and the part
is a billet. So the volume is compared before and after, and a shell that removed
nothing is refused with a code rather than exported.

`Kind.INTERSECTION` is fixed rather than offered. It is what a shell means in every
CAD system — the walls are extended until they meet — and the alternative,
`Kind.ARC`, puts a radius on every inner corner that no drawing stated. An unstated
radius is exactly what ADR-026 refuses to let a blend invent, and a shell inventing
one wholesale would be the same mistake at a larger scale.
"""

from __future__ import annotations

from build123d import Kind
from build123d import offset as _offset
from cad_ir.canonical import ShellDirection, ShellFeature

from .errors import CadEngineError
from .selectors import narrowing, resolve_faces
from .topology import read_faces

#: How much of a difference in volume counts as "something was removed", in mm³.
#: Well below any wall a drawing would state and well above the noise of a kernel
#: that recomputed the same solid.
_CAVITY_TOLERANCE_MM3 = 1e-6


def shell(feature: ShellFeature, part, params):
    """The part hollowed as `feature` says, or a typed refusal."""
    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} hollows a body, but nothing has been built for it to hollow.",
        )

    faces = _open_faces(feature, part)
    thickness = params.resolve(feature.inputs.thickness, f"{feature.id} wall thickness")
    if thickness <= 0:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            f"{feature.id} shells by {thickness} mm; a wall thickness must be positive.",
        )

    inward = feature.inputs.direction is ShellDirection.INWARD
    before = float(part.volume)
    try:
        result = _offset(
            part,
            amount=-thickness if inward else thickness,
            openings=faces,
            kind=Kind.INTERSECTION,
        )
    except CadEngineError:
        raise
    except Exception as error:  # noqa: BLE001 - the kernel raises ValueError and worse
        raise CadEngineError(
            "SHELL_FAILED",
            "feature",
            f"{feature.id} asks for a {thickness} mm {feature.inputs.direction} wall with "
            f"{len(faces)} face(s) open, and the kernel refused it: {error}.",
        ) from error

    if result is None or not result.solids():
        raise CadEngineError(
            "SHELL_FAILED",
            "feature",
            f"{feature.id} asks for a {thickness} mm wall and produced nothing.",
        )

    if inward and float(result.volume) >= before - _CAVITY_TOLERANCE_MM3:
        # Not an internal error: it is a document asking for a wall the part has no
        # room for, and the kernel answering with the part it started from.
        raise CadEngineError(
            "SHELL_NO_CAVITY",
            "feature",
            f"{feature.id} shells inward by {thickness} mm and removes no material: "
            f"the body is {before:.3f} mm³ before and {float(result.volume):.3f} mm³ "
            "after. Two walls of that thickness meet before they leave a cavity, so "
            "the part is solid where the document says it is hollow.",
        )
    return result


def _open_faces(feature: ShellFeature, part):
    """The kernel faces the document opens.

    CAD-IR 1.8 has already refused a cardinality that permits zero, so what is left
    here is turning a resolution into handles — and, when it fails, saying which
    clause of the selector got it there. "No match" alone sends a repair agent
    guessing at six predicates.
    """
    selector = feature.inputs.faces
    resolution = resolve_faces(selector, read_faces(part))
    if not resolution.satisfied or not resolution.matched:
        raise CadEngineError(
            resolution.failure_code or "SELECTOR_NO_MATCH",
            "selector",
            f"Selector {selector.id} named {len(resolution.matched)} face(s) to open for "
            f"{feature.id}, which its declared cardinality does not allow. "
            + narrowing(resolution),
        )
    return [descriptor.handle for descriptor in resolution.matched]


__all__ = ["shell"]
