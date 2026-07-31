"""Union, subtract, intersect — between bodies the document has named.

Fusing has always happened implicitly: an additive feature joined what was already
there. That is right for a boss on a plate and wrong for anything a drawing calls a
boolean, because "subtract this from that and keep this" is a statement about two named
things and cannot be spelled as an ordering.

The operation modifies its target and consumes its tools, which is why a boolean
produces no result: the answer *is* the target body, under the name it already had.
A document that wants the tools kept says so.
"""

from __future__ import annotations

from cad_ir.canonical import BooleanFeature, BooleanOp

from .bodies import Bodies
from .errors import CadEngineError


def combine(feature: BooleanFeature, bodies: Bodies) -> None:
    """Apply one boolean to the table of bodies."""
    inputs = feature.inputs
    target = bodies.locate(str(inputs.target.result), str(feature.id))
    if target is None:
        raise CadEngineError(
            "FEATURE_RESULT_UNAVAILABLE",
            "feature",
            f"{feature.id} operates on {inputs.target.result}, which nothing has built.",
        )

    tools = [bodies.locate(str(item.result), str(feature.id)) for item in inputs.tools]
    result = bodies.solid_at(target)
    for index in tools:
        result = _apply(inputs.op, result, bodies.solid_at(index), feature)
    bodies.replace(target, result)

    if not inputs.keep_tools:
        # Highest index first, so removing one does not move the others.
        for index in sorted(tools, reverse=True):
            bodies.drop(index)
        # `replace` set the active body by index, and dropping may have moved the
        # target, so point at it again by name.
        bodies.replace(bodies.locate(str(inputs.target.result), str(feature.id)), result)


def _apply(op: BooleanOp, target, tool, feature):
    """One kernel boolean, with its refusal turned into something typed.

    An intersection of two bodies that do not touch is the case worth naming: the
    kernel returns an empty shape rather than failing, and a document that meant
    something else would otherwise get a part with a body of no volume in it.
    """
    try:
        if op is BooleanOp.UNION:
            result = target + tool
        elif op is BooleanOp.SUBTRACT:
            result = target - tool
        elif op is BooleanOp.INTERSECT:
            result = target & tool
        else:  # pragma: no cover - the enum is closed
            raise CadEngineError("UNSUPPORTED_FEATURE", "feature", f"Unknown boolean {op}.")
    except CadEngineError:
        raise
    except Exception as error:  # noqa: BLE001 - the kernel's failures are opaque
        raise CadEngineError(
            "BOOLEAN_FAILED",
            "feature",
            f"{feature.id} asks for a {op} and the kernel refused it: {error}",
        ) from error

    if result is None or not _has_volume(result):
        raise CadEngineError(
            "BOOLEAN_EMPTY",
            "feature",
            f"{feature.id} asks for a {op} whose result encloses no volume. "
            "Two bodies that do not overlap have nothing to intersect, and a body "
            "subtracted from itself leaves nothing.",
        )
    # `clean()` for the same reason every other combine does it: a boolean leaves the
    # faces where two solids met, and a body count is what notices.
    return result.clean()


def _has_volume(shape) -> bool:
    try:
        return float(shape.volume) > 1e-9
    except Exception:  # noqa: BLE001 - an empty compound has no volume to read
        return False


__all__ = ["combine"]
