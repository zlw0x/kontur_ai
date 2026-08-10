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
    BooleanFeature,
    BooleanOp,
    ChamferFeature,
    CircularPattern,
    CutExtrudeFeature,
    CutLoftFeature,
    CutRevolveFeature,
    CutSweepFeature,
    DatumPlaneOffsetFeature,
    DraftFeature,
    FilletFeature,
    LinearPattern,
    MirrorPattern,
    PatternFeature,
    ShellDirection,
    ShellFeature,
    SolidExtrudeFeature,
    SolidLoftFeature,
    SolidRevolveFeature,
    SolidSweepFeature,
)
from cad_ir.selectors import EdgeSelector, FaceSelector
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
SOLID_SWEEP = "solid.sweep"
CUT_SWEEP = "cut.sweep"
SOLID_LOFT = "solid.loft"
CUT_LOFT = "cut.loft"
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
# Two modes of the operation the cycle uses most, each its own key. A part built
# twice as thick and a part built with the wrong draft are different mistakes, and
# an operator who has seen one wants to stop that one.
FEATURE_EXTRUDE_SYMMETRIC = "feature.extrude.symmetric"
FEATURE_EXTRUDE_DRAFT = "feature.extrude.draft"
#: An extrusion whose length is a face rather than a number (CAD-IR 1.13).
#:
#: `experimental` rather than `beta`, and the reason is the corpus rule: a
#: capability is promoted by cases, and this one has the cases it was given here and
#: no run behind it. The cycle cannot ask for it either — a face selector is a named
#: selection written in this repository (ADR-032), and "the face this rib lands on"
#: is not a constant — so it arrives the way the shell did.
FEATURE_EXTRUDE_UNTIL_FACE = "feature.extrude.until_face"
FEATURE_BODY_NEW = "feature.body.new"
BOOLEAN_UNION = "boolean.union"
BOOLEAN_SUBTRACT = "boolean.subtract"
BOOLEAN_INTERSECT = "boolean.intersect"
FEATURE_PATTERN_LINEAR = "feature.pattern.linear"
FEATURE_PATTERN_CIRCULAR = "feature.pattern.circular"
FEATURE_MIRROR = "feature.mirror"
FEATURE_FILLET_CONSTANT = "feature.fillet.constant_radius"
FEATURE_CHAMFER_EQUAL = "feature.chamfer.equal_distance"
FEATURE_CHAMFER_ASYMMETRIC = "feature.chamfer.asymmetric"
# Two keys, because the two directions are two different parts. An inward wall keeps
# the drawing's outside size; an outward one grows past it, and an operator who has
# seen a part come out 6 mm too big in every direction wants to stop that one alone.
FEATURE_SHELL_INWARD = "feature.shell.inward"
FEATURE_SHELL_OUTWARD = "feature.shell.outward"
#: Drafting the walls of a body that already exists (CAD-IR 1.12, ADR-035). Separate
#: from `taper_deg`, which is part of an extrusion and has no key of its own, because
#: this is the operation an operator would roll back on its own: it names faces, and a
#: selector that lands on the wrong ones is a part of the right size with the wrong
#: walls leaning.
FEATURE_DRAFT = "feature.draft"
SELECTOR_EDGE_CONVEXITY = "selector.edge.convexity"
EXPORT_STEP = "export.step"
EXPORT_STL = "export.stl"
VALIDATE_MANIFOLD = "validate.manifold"
VALIDATE_BOUNDING_BOX = "validate.bounding_box"
VALIDATE_HOLE_COUNT = "validate.hole_count"
VALIDATE_SURFACE_FACE_COUNT = "validate.surface_face_count"
# The topology oracle: the genus of the delivered solid, computed off the STEP and
# off the STL and required to agree. Its own key because it is the one check that
# needs nothing from the document, so an operator stopping it is stopping a
# different kind of thing from a stated expectation.
VALIDATE_TOPOLOGY = "validate.topology"


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
#: **Nothing here is stable, and everything the golden corpus covers is beta as of
#: POSTMVP-013/014.** Revolve, the
#: blends, the patterns, named bodies and the booleans each arrived `experimental` — on
#: one fixture and one day — and the promotion was always meant to be a one-line change
#: with a corpus behind it. That corpus now exists: every one of these is built at several
#: sizes against closed-form arithmetic, refuses a named list of malformed documents with
#: named codes, and produces byte-identical results twice in a row
#: (`tests/golden_corpus.py`, `tests/test_corpus.py`).
#:
#: Not stable, and the bar for that is the roadmap's own: Gate P2 asks for 100 golden
#: models across 30 part types and 99% deterministic build success on a synthetic corpus.
#: Forty-two cases across fifteen part shapes is a body of evidence; it is not that gate.
#:
#: **`feature.chamfer.asymmetric` stays experimental**, alone among the operations. It is
#: the one whose distinguishing question — which face the first distance is measured from —
#: has no corpus case: the blended-bracket fixture exercises it and nothing varies it. An
#: operation has not earned a promotion just because its neighbours did.
#:
#: Convexity is listed among the operations because it is a *predicate* rather than one,
#: and it keeps its own switch: it is a measurement this engine makes with a dot product it
#: wrote itself, and if that is wrong on some geometry what has to stop is every selector
#: that trusts it — not every fillet.
DECLARED: Mapping[str, Declaration] = {
    SOLID_RECTANGULAR_PRISM: Declaration("beta"),
    SOLID_CONTOUR_PROFILE: Declaration("beta"),
    SOLID_REVOLVE: Declaration("beta"),
    CUT_REVOLVE: Declaration("beta"),
    SOLID_SWEEP: Declaration("beta"),
    CUT_SWEEP: Declaration("beta"),
    SOLID_LOFT: Declaration("beta"),
    CUT_LOFT: Declaration("beta"),
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
    FEATURE_EXTRUDE_SYMMETRIC: Declaration("beta"),
    FEATURE_EXTRUDE_DRAFT: Declaration("beta"),
    FEATURE_EXTRUDE_UNTIL_FACE: Declaration("experimental"),
    FEATURE_BODY_NEW: Declaration("beta"),
    BOOLEAN_UNION: Declaration("beta"),
    BOOLEAN_SUBTRACT: Declaration("beta"),
    BOOLEAN_INTERSECT: Declaration("beta"),
    FEATURE_PATTERN_LINEAR: Declaration("beta"),
    FEATURE_PATTERN_CIRCULAR: Declaration("beta"),
    FEATURE_MIRROR: Declaration("beta"),
    FEATURE_FILLET_CONSTANT: Declaration("beta"),
    FEATURE_CHAMFER_EQUAL: Declaration("beta"),
    FEATURE_CHAMFER_ASYMMETRIC: Declaration("experimental"),
    FEATURE_SHELL_INWARD: Declaration("beta"),
    FEATURE_SHELL_OUTWARD: Declaration("beta"),
    # Experimental until the corpus has more than the two shapes that
    # earned it: some walls of a block, and the outer wall of a turned part.
    FEATURE_DRAFT: Declaration("experimental"),
    SELECTOR_EDGE_CONVEXITY: Declaration("beta"),
    EXPORT_STEP: Declaration("beta"),
    EXPORT_STL: Declaration("beta"),
    VALIDATE_MANIFOLD: Declaration("beta"),
    VALIDATE_BOUNDING_BOX: Declaration("beta"),
    VALIDATE_HOLE_COUNT: Declaration("beta"),
    VALIDATE_SURFACE_FACE_COUNT: Declaration("beta"),
    VALIDATE_TOPOLOGY: Declaration("beta"),
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
    need(VALIDATE_TOPOLOGY, "every build")
    if any(str(getattr(item, "type", "")) == "through_hole_count" for item in document.expectations):
        need(VALIDATE_HOLE_COUNT, "the through-hole expectation")
    if any(
        str(getattr(item, "type", "")) == "surface_face_count" for item in document.expectations
    ):
        need(VALIDATE_SURFACE_FACE_COUNT, "the surface-face-count expectation")

    solids_so_far = 0
    for feature in document.features:
        if not feature.enabled:
            continue
        where = f"feature {feature.id}"

        if isinstance(feature, DatumPlaneOffsetFeature):
            need(SKETCH_PLANE_DATUM, where)
            continue

        if isinstance(feature, BooleanFeature):
            need(
                {
                    BooleanOp.UNION: BOOLEAN_UNION,
                    BooleanOp.SUBTRACT: BOOLEAN_SUBTRACT,
                    BooleanOp.INTERSECT: BOOLEAN_INTERSECT,
                }[feature.inputs.op],
                f"the boolean {feature.id}",
            )
            continue

        if getattr(feature.inputs, "both_directions", False) and not isinstance(
            feature, (SolidRevolveFeature, CutRevolveFeature)
        ):
            need(FEATURE_EXTRUDE_SYMMETRIC, f"the symmetric extrusion {feature.id}")
        taper = getattr(feature.inputs, "taper_deg", 0.0)
        if taper is not None and not isinstance(taper, (int, float)) or taper:
            need(FEATURE_EXTRUDE_DRAFT, f"the draft on {feature.id}")
        if getattr(feature.inputs, "until_face", None) is not None:
            need(
                FEATURE_EXTRUDE_UNTIL_FACE,
                f"the extrusion {feature.id}, which stops at a face",
            )

        if getattr(feature.inputs, "new_body", False):
            # A separate lump of material is its own capability: a part delivered as
            # two bodies where one was meant is a different kind of wrong from a
            # misplaced boss, and an operator may want to stop only that.
            need(FEATURE_BODY_NEW, f"the separate body {feature.id} builds")

        if isinstance(feature, SolidExtrudeFeature):
            need(SOLID_RECTANGULAR_PRISM, f"the solid extrusion {feature.id}")
            if solids_so_far and not feature.inputs.new_body:
                # A second additive feature lands on a body that already exists,
                # which is a different operation from making the first one and
                # was the source of the multi-body defect POSTMVP-006 found. A
                # feature starting a *new* body is not that: it fuses with nothing.
                need(FEATURE_BOSS_ADDITIVE, f"the boss {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutExtrudeFeature):
            need(FEATURE_HOLE_SIMPLE_THROUGH, f"the cut {feature.id}")
        elif isinstance(feature, SolidRevolveFeature):
            need(SOLID_REVOLVE, f"the revolve {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutRevolveFeature):
            need(CUT_REVOLVE, f"the revolved cut {feature.id}")
        elif isinstance(feature, SolidSweepFeature):
            need(SOLID_SWEEP, f"the sweep {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutSweepFeature):
            need(CUT_SWEEP, f"the swept cut {feature.id}")
        elif isinstance(feature, SolidLoftFeature):
            need(SOLID_LOFT, f"the loft {feature.id}")
            solids_so_far += 1
        elif isinstance(feature, CutLoftFeature):
            need(CUT_LOFT, f"the lofted cut {feature.id}")
        elif isinstance(feature, PatternFeature):
            spec = feature.inputs.pattern
            key = {
                LinearPattern: FEATURE_PATTERN_LINEAR,
                CircularPattern: FEATURE_PATTERN_CIRCULAR,
                MirrorPattern: FEATURE_MIRROR,
            }[type(spec)]
            need(key, f"the pattern {feature.id}")
        elif isinstance(feature, ShellFeature):
            need(
                FEATURE_SHELL_INWARD
                if feature.inputs.direction is ShellDirection.INWARD
                else FEATURE_SHELL_OUTWARD,
                f"the shell {feature.id}",
            )
        elif isinstance(feature, DraftFeature):
            need(FEATURE_DRAFT, f"the draft {feature.id}")
        elif isinstance(feature, FilletFeature):
            need(FEATURE_FILLET_CONSTANT, f"the fillet {feature.id}")
        elif isinstance(feature, ChamferFeature):
            # Two keys, because the asymmetric form is a different question about
            # the document: which face the first distance belongs to. An operator
            # who has seen a chamfer come out the wrong way round wants to stop
            # that one without stopping every chamfer.
            asymmetric = (
                feature.inputs.second_distance is not None or feature.inputs.angle_deg is not None
            )
            if asymmetric:
                need(FEATURE_CHAMFER_ASYMMETRIC, f"the asymmetric chamfer {feature.id}")
            else:
                need(FEATURE_CHAMFER_EQUAL, f"the chamfer {feature.id}")

        for selector in _selectors_of(feature.inputs):
            if getattr(selector.where, "convexity", None) is not None:
                need(SELECTOR_EDGE_CONVEXITY, f"the convexity predicate in {selector.id}")

        sketch = getattr(feature.inputs, "sketch", None)
        if sketch is not None:
            _sketch_requirements(sketch, need)
        # A loft has sections rather than a sketch, and each of them draws contours on
        # a plane exactly as a sketch does. Asking only for `sketch` would leave a loft
        # of two spelled-out profiles needing neither `solid.contour_profile` nor a
        # plane key — a flag that silently did not apply.
        for section in getattr(feature.inputs, "sections", []) or []:
            _sketch_requirements(section, need)

    return needed


def _selectors_of(inputs):
    """Every selector in a feature's inputs, however deeply it sits.

    Walked rather than listed field by field: a selector reached by a path nobody
    remembered to enumerate is a predicate whose flag silently does not apply.
    """
    if isinstance(inputs, (FaceSelector, EdgeSelector)):
        yield inputs
        return
    if hasattr(inputs, "__pydantic_fields__"):
        for name in type(inputs).model_fields:
            yield from _selectors_of(getattr(inputs, name))
    elif isinstance(inputs, (list, tuple)):
        for item in inputs:
            yield from _selectors_of(item)


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
