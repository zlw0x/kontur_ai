"""Build a CAD-IR document with build123d, and export STEP and STL.

The trust boundary is unchanged from the KOMPAS era and is the whole reason the
engine could be replaced at all: the AI writes a document, a versioned schema and
a trusted validator check it, and only then does hand-written code drive the
kernel. Nothing in this module interprets a document as code.

Feature order is the document's own. CAD-IR states dependencies and the canonical
validator has already checked they are acyclic and declared before use, so array
order is a valid build order by the time a document arrives here. Re-deriving the
topology would be a second implementation of something already proved correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from build123d import Plane, export_step, export_stl, extrude
from cad_ir.canonical import (
    CadIrDocument,
    CutExtrudeFeature,
    DatumPlaneOffsetFeature,
    Direction,
    SolidExtrudeFeature,
)
from cad_ir.sketch import SketchOnBasePlane, SketchOnDatumPlane, SketchOnFace

from .constraints import DegreesOfFreedom, validate
from .entities import named_entities
from .errors import CadEngineError, unsupported
from .parameters import Parameters
from .selectors import require_one, resolve_faces
from .topology import read_faces
from .identity import ARTIFACTS, EngineDescription, describe
from .sketches import sketch_face

#: The base planes a sketch may name, and what they are in build123d.
BASE_PLANES = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}


@dataclass(frozen=True)
class BuiltArtifact:
    kind: str
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BuildOutcome:
    """What was built, and by what."""

    part: object
    artifacts: tuple[BuiltArtifact, ...]
    engine: EngineDescription


def build(document: CadIrDocument, output_directory: Path) -> BuildOutcome:
    """Build the document and write the two user-facing results."""
    output = _safe_output(output_directory)
    part = build_part(document)
    artifacts = _export(part, output)
    return BuildOutcome(part=part, artifacts=artifacts, engine=describe())


def build_part(document: CadIrDocument):
    """The solid, with nothing written to disk.

    Separate from `build` so geometry can be measured in a test without an
    export, and so an export failure is distinguishable from a modelling one.
    """
    part = None
    #: Datum planes, by the id of the result they produce, so a later sketch can
    #: name one. Named, never indexed — the rule ADR-019 sets for faces holds
    #: one level down for planes.
    planes: dict[str, Plane] = {}
    # Resolved once, up front. A parameter that does not exist should fail before
    # a single face is made rather than halfway through a part.
    params = Parameters.of(document)

    for feature in document.features:
        if not feature.enabled:
            # A disabled feature is a document deliberately saying "not this
            # one". Skipping it silently is correct; building it would be
            # ignoring the document.
            continue

        if isinstance(feature, DatumPlaneOffsetFeature):
            planes[_plane_result_id(feature)] = _offset_plane(feature, planes, params)
            continue

        if isinstance(feature, (SolidExtrudeFeature, CutExtrudeFeature)):
            part = _extrude_feature(feature, part, planes, params)
            continue

        raise unsupported(
            f"This engine cannot build a {feature.type} feature yet.", "feature"
        )

    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET", "prepare", "The document builds no solid."
        )
    return part


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def _extrude_feature(feature, part, planes: dict[str, Plane], params):
    sketch = feature.inputs.sketch
    _check_assertions(sketch, params)

    plane = _sketch_plane(sketch.plane, planes, part)
    face = sketch_face(sketch.outer, list(sketch.inner), params)

    is_cut = isinstance(feature, CutExtrudeFeature)
    if part is None and is_cut:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} cuts, but nothing has been built for it to cut.",
        )

    # The sketch is drawn in its own plane's coordinates and then placed, which
    # is what makes a profile mean the same thing on the XY plane and on a datum
    # plane 8 mm above it.
    placed = plane.location * face

    if is_cut and feature.inputs.through_all:
        # "Through all" is a statement about the body, so it is measured from the
        # body rather than given a large constant. A constant would be wrong in
        # both directions at once: too small for a big part, and for a small one
        # a tool reaching far past it that a later operation could still meet.
        solid = _through_all_tool(placed, part, plane)
    else:
        distance = params.resolve(feature.inputs.distance, f"{feature.id} distance")
        if distance <= 0:
            raise CadEngineError(
                "DIMENSION_OUT_OF_RANGE",
                "feature",
                "An extrusion distance must be positive.",
            )
        # Along the *plane's* normal, stated outright. Left to itself `extrude`
        # travels along the face's own normal, and which way that points depends
        # on how the contour happened to be wound — so the same document built a
        # stadium plate downwards and a hexagon hub upwards, leaving two solids
        # 8 mm apart that should have been one. The document says which way; the
        # winding of a wire is not the document.
        solid = extrude(
            placed, amount=distance * _sense(feature, plane), dir=plane.z_dir
        )

    if part is None:
        return solid
    combined = part - solid if is_cut else part + solid
    # `clean()` removes the faces a boolean leaves behind where two solids met.
    #
    # Without it a hub sitting exactly on a plate stays two solids with an
    # internal face between them: the shape is right, the body count is not, and
    # the document's `body_count` expectation would fail for a reason that has
    # nothing to do with what the drawing said. Found by comparing this fixture
    # with the KOMPAS run of the same document, which reported one body of
    # seventeen faces where this engine first reported two of eighteen.
    return combined.clean()


#: The world axis each `direction` names, as a unit vector.
_AXES = {
    Direction.PLUS_X: (1.0, 0.0, 0.0),
    Direction.MINUS_X: (-1.0, 0.0, 0.0),
    Direction.PLUS_Y: (0.0, 1.0, 0.0),
    Direction.MINUS_Y: (0.0, -1.0, 0.0),
    Direction.PLUS_Z: (0.0, 0.0, 1.0),
    Direction.MINUS_Z: (0.0, 0.0, -1.0),
}


def _sense(feature, plane: Plane) -> float:
    """Which way along the sketch plane's normal the document means, as +1 or -1.

    An extrusion travels along its sketch's normal — that is what an extrusion
    is. `direction` in CAD-IR names a *world* axis, so the two have to be
    reconciled rather than assumed equal: the same "+Z" means one thing for a
    sketch on XY and the opposite for a sketch on a plane that faces the other
    way.

    Reconciled by sign rather than by name, because a name comparison would be
    right only for the base planes and silently wrong on every datum plane that
    was flipped.
    """
    axis = _AXES.get(feature.inputs.direction)
    if axis is None:  # pragma: no cover - the enum is closed
        raise unsupported(f"Unknown direction {feature.inputs.direction}.", "feature")
    normal = plane.z_dir
    along = axis[0] * normal.X + axis[1] * normal.Y + axis[2] * normal.Z
    if abs(along) < 1e-9:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} extrudes along {feature.inputs.direction}, which lies in "
            "its own sketch plane. An extrusion has to leave its sketch.",
        )
    return 1.0 if along > 0 else -1.0


def _through_all_tool(placed_face, part, plane: Plane):
    """A cutting tool long enough to leave the body on both sides.

    Cut in both directions rather than one: a sketch on the base plane of a part
    that straddles it would otherwise cut only half the hole, and which half
    would depend on the sign of a direction the document meant as "through".
    """
    box = part.bounding_box()
    reach = max(box.size.X, box.size.Y, box.size.Z) + 1.0
    return extrude(placed_face, amount=reach, dir=plane.z_dir, both=True)


def _check_assertions(sketch, params) -> DegreesOfFreedom | None:
    """Refuse a sketch whose constraints its own coordinates contradict.

    This is the check, not an application. build123d has no constraint solver and
    a STEP file cannot carry constraints, so unlike the KOMPAS engine this one
    cannot put them into the delivered model — ADR-023 records that as a real
    cost. What survives is the half that catches a misread drawing, and it runs
    before any geometry is made: a document that says two different things about
    the same part should fail without starting a build.
    """
    if not sketch.constraints and not sketch.dimensions:
        return None
    entities = named_entities(sketch, params)
    return validate(entities, list(sketch.constraints), list(sketch.dimensions), params)


def _sketch_plane(spec, planes: dict[str, Plane], part) -> Plane:
    if isinstance(spec, SketchOnBasePlane):
        plane = BASE_PLANES.get(str(spec.plane))
        if plane is None:
            raise unsupported(f"{spec.plane} is not a base plane.", "sketch")
        return plane
    if isinstance(spec, SketchOnDatumPlane):
        # Both spellings carry their target in `plane`; on a datum sketch it is a
        # reference to a result an earlier feature produced, not a base name.
        name = str(spec.plane.result)
        plane = planes.get(name)
        if plane is None:
            raise CadEngineError(
                "FEATURE_RESULT_UNAVAILABLE",
                "sketch",
                f"No plane named {name} has been built.",
            )
        return plane
    if isinstance(spec, SketchOnFace):
        if part is None:
            raise CadEngineError(
                "FEATURE_RESULT_UNAVAILABLE",
                "selector",
                f"Selector {spec.face.id} names a face of a body nothing has built yet.",
            )
        # Resolved against the model as it is *now*, not once at the start. Every
        # operation that changes the topology changes what a selector means, and
        # a resolution cached across one would be an index by another name.
        face = require_one(resolve_faces(spec.face, read_faces(part)), spec.face)
        return Plane(face.handle)
    raise unsupported(f"Unknown sketch plane {type(spec).__name__}.", "sketch")


def _offset_plane(
    feature: DatumPlaneOffsetFeature,
    planes: dict[str, Plane],
    params,
) -> Plane:
    """A plane parallel to another, a stated distance away.

    `base` is either a base plane's name or a reference to a plane an earlier
    feature produced, so a document can stack them. Both are resolved by name;
    neither is an index.
    """
    inputs = feature.inputs
    name = str(inputs.base.result) if hasattr(inputs.base, "result") else str(inputs.base)
    base = BASE_PLANES.get(name) or planes.get(name)
    if base is None:
        raise CadEngineError(
            "FEATURE_RESULT_UNAVAILABLE",
            "feature",
            f"{feature.id} is offset from {name}, which is neither a base plane nor "
            "a plane an earlier feature built.",
        )
    offset = params.resolve(inputs.offset_mm, f"{feature.id} offset")
    # `flip` reverses the direction, so a document can say "8 mm the other way"
    # without writing a negative number that reads as a mistake.
    return base.offset(-offset if inputs.flip else offset)


def _plane_result_id(feature: DatumPlaneOffsetFeature) -> str:
    if not feature.produces:
        raise CadEngineError(
            "CAD_IR_INVALID",
            "feature",
            f"{feature.id} builds a plane and names no result for it, so nothing "
            "can sketch on it.",
        )
    return str(feature.produces[0].id)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _safe_output(path: Path) -> Path:
    if path is None or not str(path).strip():
        raise CadEngineError(
            "OUTPUT_PATH_INVALID", "prepare", "An output directory is required."
        )
    resolved = Path(path).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _export(part, output: Path) -> tuple[BuiltArtifact, ...]:
    """Write STEP and STL, then describe what is actually on disk.

    The checksum and the size are read back from the file rather than computed
    from what was meant to be written: an engine that reported a digest of its
    intent would agree with itself about a truncated file.
    """
    import hashlib

    written: list[BuiltArtifact] = []
    for artifact in ARTIFACTS:
        target = output / artifact.file_name
        try:
            if artifact.kind == "STEP":
                export_step(part, str(target))
            elif artifact.kind == "STL":
                # The tolerances are the export's contract with the checker that
                # runs afterwards: a mesh coarser than this would fail the
                # bounding-box comparison for reasons that are about tessellation
                # rather than about the model.
                export_stl(part, str(target), tolerance=0.01, angular_tolerance=0.1)
            else:  # pragma: no cover - ARTIFACTS is closed
                raise unsupported(f"Unknown artifact {artifact.kind}.", "export")
        except CadEngineError:
            raise
        except Exception as error:  # noqa: BLE001 - the kernel's failures are opaque
            raise CadEngineError(
                "EXPORT_FAILED", "export", f"Writing {artifact.file_name} failed: {error}"
            ) from error

        if not target.exists() or target.stat().st_size == 0:
            raise CadEngineError(
                "EXPORT_FAILED",
                "export",
                f"{artifact.file_name} was not written, and {describe().engine_id} "
                "declares it.",
            )
        written.append(
            BuiltArtifact(
                kind=artifact.kind,
                path=target,
                size_bytes=target.stat().st_size,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest().upper(),
            )
        )
    return tuple(written)


__all__ = ["build", "build_part", "BuildOutcome", "BuiltArtifact"]
