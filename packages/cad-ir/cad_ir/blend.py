"""CAD-IR 1.5: fillet and chamfer — the first operations that only name geometry.

Every operation before this one describes something to make: a profile and a
distance, a profile and an axis. A blend describes something that already exists
and says what to do to its edges. So it is the first feature whose entire input is
a selector, and the first where getting the *naming* wrong produces a part that is
plausible, buildable and not the one on the drawing.

That shapes three rules.

*An edge blend must name at least one edge.* `zero_or_one` and `all` are refused,
which is the opposite of the leniency they look like. Both let a selector that
matches nothing be a silently successful no-op — the model builds, every
expectation passes, and the drawing's rounded corners are square. "Round every
corner" is written `exactly_n: 4`, which states the count, so a part that grew a
fifth corner is a contradiction rather than a surprise.

*An asymmetric chamfer names the face its first distance is measured from.* Two
distances or a distance and an angle are meaningless until something says which
side of the edge the first one belongs to, and the kernel's own answer to "which
side?" is whichever face it happened to visit first. So an asymmetric chamfer
carries a face selector, and the engine checks that the face actually contains the
edges before the kernel is asked.

*A blend produces nothing.* It modifies a body; it does not make one. A `produces`
entry would put a result id in the document that no later feature could
meaningfully refer to, because the thing it would name is the body that was
already there.

What is deliberately absent is the **tangent chain** — "this edge and everything
smoothly continuous with it". It is in the roadmap (P2.4) and it is an implicit
widening of a selector: the document states one edge and the kernel decides how
many it meant. Every rule above exists to stop exactly that, so a chain has to
arrive as something the document counts, not as something the kernel discovers.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import (
    FeatureResult,
    FeatureType,
    Id,
    ParameterRef,
    Provenance,
    Scalar,
    StrictModel,
)
from .selectors import Cardinality, EdgeSelector, ExactlyN, FaceSelector

#: The cardinalities an edge blend may declare.
#:
#: `exactly_n` is allowed too and is handled separately, being a model rather than
#: a member of the enum.
BLEND_CARDINALITIES: tuple[Cardinality, ...] = (
    Cardinality.EXACTLY_ONE,
    Cardinality.ONE_OR_MORE,
)


def _require_countable_edges(selector: EdgeSelector) -> None:
    """A blend's selector must be unable to match nothing.

    `all` and `zero_or_one` both permit zero matches, and a blend of zero edges is
    a feature that silently does not happen: the document is valid, the build
    succeeds, every expectation still holds, and the part has square corners where
    the drawing shows round ones. Nothing downstream can catch it, because from the
    outside it is indistinguishable from a document that never asked.
    """
    cardinality = selector.cardinality
    if isinstance(cardinality, ExactlyN):
        if cardinality.value < 1:
            raise ValueError(
                f"selector {selector.id} blends exactly 0 edges, which is a feature "
                "that does nothing; leave it out of the document instead"
            )
        return
    if cardinality not in BLEND_CARDINALITIES:
        raise ValueError(
            f"selector {selector.id} declares {cardinality}, which allows matching no "
            "edges at all; an edge blend must declare exactly_one, one_or_more or "
            "exactly_n so that blending nothing is a failure rather than a no-op"
        )


def _require_positive(value: Scalar, what: str) -> None:
    """A literal size has to be positive; a named one is the engine's to resolve.

    Checked here only where it can be: a `ParameterRef` is a promise about a number
    this module never sees, and the engine resolves and re-checks it in front of the
    kernel.
    """
    if isinstance(value, ParameterRef):
        return
    if float(value) <= 0:
        raise ValueError(f"{what} must be positive")


class FilletInputs(StrictModel):
    """Constant-radius fillet on the edges a selector names.

    There is no `source_body`: the selector's `from_result` already says which
    body's edges these are, and a second way to say it is a second thing that can
    disagree.
    """

    edges: EdgeSelector
    radius: Scalar

    @model_validator(mode="after")
    def validate_inputs(self) -> "FilletInputs":
        _require_countable_edges(self.edges)
        _require_positive(self.radius, "a fillet radius")
        return self


class ChamferInputs(StrictModel):
    """A chamfer, symmetric unless the document says otherwise.

    `distance` alone is the equal-distance chamfer. `second_distance` makes it
    two-distance and `angle_deg` makes it distance-and-angle; either of those needs
    `measured_from`, because until a face is named, "the first distance" is not a
    statement about the part.
    """

    edges: EdgeSelector
    distance: Scalar
    second_distance: Scalar | None = None
    angle_deg: Scalar | None = None
    #: The face `distance` is measured on. Required for an asymmetric chamfer and
    #: refused for a symmetric one, where it would have nothing to disambiguate.
    measured_from: FaceSelector | None = None

    @model_validator(mode="after")
    def validate_inputs(self) -> "ChamferInputs":
        _require_countable_edges(self.edges)
        _require_positive(self.distance, "a chamfer distance")
        if self.second_distance is not None and self.angle_deg is not None:
            raise ValueError(
                "a chamfer is given two distances or a distance and an angle, not both"
            )
        if self.second_distance is not None:
            _require_positive(self.second_distance, "a chamfer's second distance")
        if self.angle_deg is not None:
            if isinstance(self.angle_deg, ParameterRef):
                pass
            elif not 0 < float(self.angle_deg) < 90:
                # 0 and 90 are the two degenerate cases: no material removed, and
                # a cut parallel to the face it is measured from.
                raise ValueError("a chamfer angle is more than 0 and less than 90 degrees")

        asymmetric = self.second_distance is not None or self.angle_deg is not None
        if asymmetric and self.measured_from is None:
            raise ValueError(
                "an asymmetric chamfer must name the face its first distance is measured "
                "from; without one, which side the distance belongs to is whichever face "
                "the kernel visits first"
            )
        if not asymmetric and self.measured_from is not None:
            raise ValueError(
                "a symmetric chamfer measures the same distance on both faces, so naming "
                "one of them says nothing"
            )
        if self.measured_from is not None and (
            self.measured_from.cardinality is not Cardinality.EXACTLY_ONE
        ):
            raise ValueError(
                "a chamfer is measured from one face, so its selector must declare "
                "exactly_one"
            )
        return self


class _BlendFeature(StrictModel):
    """What a fillet and a chamfer share, which is everything but the sizes."""

    id: Id
    enabled: bool = True
    depends_on: Annotated[list[Id], Field(max_length=64)] = Field(default_factory=list)
    #: Always empty. A blend modifies a body rather than making one, so there is
    #: nothing for a later feature to name that was not already there.
    produces: Annotated[list[FeatureResult], Field(max_length=0)] = Field(default_factory=list)
    provenance: Provenance | None = None


class FilletFeature(_BlendFeature):
    type: Literal[FeatureType.FILLET]
    inputs: FilletInputs


class ChamferFeature(_BlendFeature):
    type: Literal[FeatureType.CHAMFER]
    inputs: ChamferInputs


__all__ = [
    "BLEND_CARDINALITIES",
    "ChamferFeature",
    "ChamferInputs",
    "FilletFeature",
    "FilletInputs",
]
