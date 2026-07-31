"""What this engine builds, one key at a time, and how to turn a key off.

ADR-021 requires a per-operation feature flag for every operation, so that an
operation found to be producing bad parts can be stopped without a release. The
KOMPAS worker has had that since POSTMVP-006; build123d shipped ENGINE-MIG-006
without it, and ENGINE-MIG-007 is where that debt is paid.

Three properties are carried over deliberately, because each of them is what
makes a rollback real rather than nominal.

*The key vocabulary is shared with the other engine.* The API schedules on these
names, and two engines with different words for the same operation would mean a
job routed by capability could not be routed at all. Where an operation is the
same operation, the key is the same string as `CadCapabilities` on the .NET side.
Where it is not — `export.m3d` here, `solid.revolve` there — the difference is the
point.

*A document is refused whole.* Requirements are collected in one pass over the
document and checked before any geometry is made, so a plan needing a disabled
operation costs a typed error rather than a half-built part.

*An unknown key is loud.* A typo in a rollback switch is the worst possible time
to fail silently: the operator believes an operation is off and it is still
running.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from cad_ir.canonical import (
    CutExtrudeFeature,
    CutRevolveFeature,
    DatumPlaneOffsetFeature,
    SolidExtrudeFeature,
    SolidRevolveFeature,
)
from cad_ir.sketch import (
    ArcSegment,
    PathContour,
    RegularPolygonContour,
    SketchOnBasePlane,
    SketchOnDatumPlane,
    SketchOnFace,
    SlotContour,
)

from .errors import CadEngineError

# --- the vocabulary -------------------------------------------------------
#
# Granularity follows the failure, not the code. An arc and a slot share every
# line of the drawing path, but a slot is expanded arithmetic that could be wrong
# on its own, so it gets its own key.

SOLID_RECTANGULAR_PRISM = "solid.rectangular_prism"
SOLID_CONTOUR_PROFILE = "solid.contour_profile"
SOLID_REVOLVE = "solid.revolve"
CUT_REVOLVE = "cut.revolve"
SKETCH_ARC = "sketch.arc"
SKETCH_SLOT = "sketch.slot"
SKETCH_REGULAR_POLYGON = "sketch.regular_polygon"
SKETCH_ISLANDS = "sketch.islands"
SKETCH_CONSTRUCTION = "sketch.construction_geometry"
SKETCH_PLANE_BASE = "sketch.plane.base"
SKETCH_PLANE_DATUM = "sketch.plane.datum_offset"
SKETCH_PLANE_FACE_SELECTOR = "sketch.plane.face_selector"
SKETCH_CONSTRAINTS = "sketch.constraints"
SKETCH_DIMENSIONS = "sketch.driving_dimensions"
FEATURE_HOLE_SIMPLE_THROUGH = "feature.hole.simple_through"
FEATURE_BOSS_ADDITIVE = "feature.boss.additive"
EXPORT_STEP = "export.step"
EXPORT_STL = "export.stl"
VALIDATE_MANIFOLD = "validate.manifold"
VALIDATE_BOUNDING_BOX = "validate.bounding_box"
VALIDATE_HOLE_COUNT = "validate.hole_count"


@dataclass(frozen=True)
class Declaration:
    """A capability's maturity, and the version of its behaviour.

    The behaviour version is independent of the engine build: it is bumped when
    an operation's observable behaviour changes, so the API can demand the newer
    behaviour without demanding a whole new worker.
    """

    status: str
    version: str = "1.0"


#: Everything this build declares, and how far anyone should trust it.
#:
#: **Beta, not stable, across the board.** Each of these has a real acceptance run
#: and a fixture that builds real geometry in CI, and none of them has the ten
#: positive and ten negative fixtures the roadmap asks for before an operation is
#: stable. The KOMPAS worker declared its newest operations beta on exactly that
#: argument; an engine two milestones old does not get to declare more.
#:
#: **Revolve is experimental**, which the API treats as not leasable at all. One
#: fixture, one day, and nothing in the service can currently produce a document
#: that uses it — the drawing agent cannot read a turned profile and the output
#: profile does not offer the operation. Declaring it beta would advertise a
#: readiness that has not been earned; declaring it here at all is what makes the
#: promotion a one-line change with a fixture corpus behind it.
DECLARED: Mapping[str, Declaration] = {
    SOLID_RECTANGULAR_PRISM: Declaration("beta"),
    SOLID_CONTOUR_PROFILE: Declaration("beta"),
    SOLID_REVOLVE: Declaration("experimental"),
    CUT_REVOLVE: Declaration("experimental"),
    SKETCH_ARC: Declaration("beta"),
    SKETCH_SLOT: Declaration("beta"),
    SKETCH_REGULAR_POLYGON: Declaration("beta"),
    SKETCH_ISLANDS: Declaration("beta"),
    SKETCH_CONSTRUCTION: Declaration("beta"),
    SKETCH_PLANE_BASE: Declaration("beta"),
    SKETCH_PLANE_DATUM: Declaration("beta"),
    SKETCH_PLANE_FACE_SELECTOR: Declaration("beta"),
    SKETCH_CONSTRAINTS: Declaration("beta"),
    SKETCH_DIMENSIONS: Declaration("beta"),
    FEATURE_HOLE_SIMPLE_THROUGH: Declaration("beta"),
    FEATURE_BOSS_ADDITIVE: Declaration("beta"),
    EXPORT_STEP: Declaration("beta"),
    EXPORT_STL: Declaration("beta"),
    VALIDATE_MANIFOLD: Declaration("beta"),
    VALIDATE_BOUNDING_BOX: Declaration("beta"),
    VALIDATE_HOLE_COUNT: Declaration("beta"),
}

#: Every key this build knows about, so a flag naming something else is refused
#: rather than silently doing nothing.
ALL: frozenset[str] = frozenset(DECLARED)

#: What the API is told when a capability is switched off. Not a low rung on the
#: maturity ladder — the API reads it as "no" outright, so a disabled operation
#: stops being scheduled rather than being scheduled reluctantly.
DISABLED = "disabled"


class CapabilityGate:
    """Which operations may be built on this run."""

    def __init__(self, disabled: frozenset[str]) -> None:
        self._disabled = disabled

    @classmethod
    def all_enabled(cls) -> "CapabilityGate":
        """The default. A missing flag file must never silently stop a service."""
        return cls(frozenset())

    @classmethod
    def disabling(cls, capabilities: Iterable[str]) -> "CapabilityGate":
        keys = frozenset(capabilities)
        unknown = sorted(keys - ALL)
        if unknown:
            raise CadEngineError(
                "CAPABILITY_UNKNOWN",
                "prepare",
                f"No such capability to disable: {', '.join(unknown)}.",
            )
        return cls(keys)

    @property
    def disabled(self) -> frozenset[str]:
        return self._disabled

    def is_enabled(self, capability: str) -> bool:
        return capability not in self._disabled

    def effective_status(self, capability: str) -> str:
        if not self.is_enabled(capability):
            return DISABLED
        return DECLARED[capability].status

    def require_all(self, needed: Mapping[str, str]) -> None:
        """Refuse the document if it needs anything that is turned off.

        Every blocked capability is named, not just the first: an operator who
        has turned off three operations should learn that in one run rather than
        in three.
        """
        blocked = sorted(key for key in needed if not self.is_enabled(key))
        if not blocked:
            return
        raise CadEngineError(
            "CAPABILITY_DISABLED",
            "cad-ir",
            "; ".join(
                f"{needed[key]} needs {key}, which is turned off on this worker"
                for key in blocked
            )
            + ".",
        )

    def declarations(self) -> dict[str, dict[str, str]]:
        """This engine's capabilities as the manifest states them."""
        return {
            key: {"status": self.effective_status(key), "version": declared.version}
            for key, declared in sorted(DECLARED.items())
        }


def requirements(document) -> dict[str, str]:
    """Every capability the document needs, and what in it needs each one.

    One pass, up front, so a document is refused whole rather than failing
    partway through a part. The mapping doubles as the explanation: an operator
    reading `CAPABILITY_DISABLED` gets told which feature asked for what.

    Disabled features are skipped. A document deliberately saying "not this one"
    is not asking for the operation it describes.
    """
    needed: dict[str, str] = {}

    def need(capability: str, what: str) -> None:
        needed.setdefault(capability, what)

    # Every build writes both files and checks the result, so these are not
    # conditional. Turning one off stops the engine, which is a legitimate thing
    # for an operator to want and a strange thing to have to phrase per document.
    need(EXPORT_STEP, "every build")
    need(EXPORT_STL, "every build")
    need(VALIDATE_MANIFOLD, "every build")
    need(VALIDATE_BOUNDING_BOX, "every build")
    if any(str(getattr(item, "type", "")) == "through_hole_count" for item in document.expectations):
        need(VALIDATE_HOLE_COUNT, "the through-hole expectation")

    solids_so_far = 0
    for feature in document.features:
        if not feature.enabled:
            continue
        where = f"feature {feature.id}"

        if isinstance(feature, DatumPlaneOffsetFeature):
            need(SKETCH_PLANE_DATUM, where)
            continue

        if isinstance(feature, SolidExtrudeFeature):
            need(SOLID_RECTANGULAR_PRISM, f"the solid extrusion {feature.id}")
            if solids_so_far:
                # A second additive feature lands on a body that already exists,
                # which is a different operation from making the first one and
                # was the source of the multi-body defect POSTMVP-006 found.
                need(FEATURE_BOSS_ADDITIVE, f"the boss {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutExtrudeFeature):
            need(FEATURE_HOLE_SIMPLE_THROUGH, f"the cut {feature.id}")
        elif isinstance(feature, SolidRevolveFeature):
            need(SOLID_REVOLVE, f"the revolve {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutRevolveFeature):
            need(CUT_REVOLVE, f"the revolved cut {feature.id}")

        sketch = getattr(feature.inputs, "sketch", None)
        if sketch is not None:
            _sketch_requirements(sketch, need)

    return needed


def _sketch_requirements(sketch, need) -> None:
    plane = sketch.plane
    if isinstance(plane, SketchOnBasePlane):
        need(SKETCH_PLANE_BASE, f"the sketch {sketch.id}")
    elif isinstance(plane, SketchOnDatumPlane):
        need(SKETCH_PLANE_DATUM, f"the sketch {sketch.id}")
    elif isinstance(plane, SketchOnFace):
        need(SKETCH_PLANE_FACE_SELECTOR, f"the sketch {sketch.id}")

    if sketch.inner:
        need(SKETCH_ISLANDS, f"the islands in {sketch.id}")
    if sketch.construction:
        need(SKETCH_CONSTRUCTION, f"the construction geometry in {sketch.id}")
    if sketch.constraints:
        need(SKETCH_CONSTRAINTS, f"the constraints in {sketch.id}")
    if sketch.dimensions:
        need(SKETCH_DIMENSIONS, f"the driving dimensions in {sketch.id}")

    for contour in [sketch.outer, *sketch.inner]:
        if isinstance(contour, PathContour):
            need(SOLID_CONTOUR_PROFILE, f"the spelled-out contour in {sketch.id}")
            if any(isinstance(segment, ArcSegment) for segment in contour.segments):
                need(SKETCH_ARC, f"the arc in {sketch.id}")
        elif isinstance(contour, SlotContour):
            need(SKETCH_SLOT, f"the slot in {sketch.id}")
        elif isinstance(contour, RegularPolygonContour):
            need(SKETCH_REGULAR_POLYGON, f"the polygon in {sketch.id}")


__all__ = [
    "ALL",
    "DECLARED",
    "DISABLED",
    "CapabilityGate",
    "Declaration",
    "requirements",
]
