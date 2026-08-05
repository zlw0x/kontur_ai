"""Draft: draw the named walls in, measured from the plane of a named face.

`build123d.draft(faces, neutral_plane, angle)` — cited from the library's own
signature, probed before anything here was written (`scripts/probe_build123d_draft.py`).

Two of the three checks in this module exist because the kernel's answers were
measured rather than assumed, on a 40 × 40 × 20 block whose section closes at 45°:

| angle | what comes back |
|---|---|
| 10° | 26 689.1761 mm³, and `extrude(taper=10)` gives the same digits |
| 40° | 12 659.0858 mm³, a valid solid — smaller, and correct |
| **45°** | 10 666.6667 mm³ — the pyramid — reporting **`is_valid` false** |
| 60° and past | `Standard_ConstructionError` **with an empty message** |

The last row is why the kernel call is wrapped: a raw OCCT throw carrying no text at
all escapes the worker's typed-error contract as a crash, which is the shape
ENGINE-MIG-006 recorded for the revolve's `StdFail_NotDone`. The 45° row is why the
result is checked afterwards as well: a solid that says it is invalid is one this
engine must not export, and it is the only operation so far where the kernel says so
itself rather than returning something plausible.

The neutral plane is taken from a face the document names, so it is a plane the part
actually has rather than a coordinate somebody chose. It decides the part: the same
block drafted +10° about its base is 26 689.1761 mm³ and about its top is 37 974.1029,
both valid and both the right height.
"""

from __future__ import annotations

from build123d import Plane
from build123d import draft as _draft
from cad_ir.canonical import DraftFeature

from .errors import CadEngineError
from .selectors import narrowing, resolve_faces
from .topology import read_faces

#: How much of a difference in volume counts as "the draft did something", in mm³.
#: A draft at any angle a drawing states moves far more than this; the tolerance is
#: here so a kernel that recomputed the same solid is not mistaken for one.
_MOVED_TOLERANCE_MM3 = 1e-6


def draft(feature: DraftFeature, part, params):
    """The part with `feature`'s walls drawn in, or a typed refusal."""
    if part is None:
        raise CadEngineError(
            "UNSUPPORTED_FEATURE_SET",
            "feature",
            f"{feature.id} drafts the walls of a body, but nothing has been built yet.",
        )

    walls = _resolved(feature.inputs.faces, feature, part, "to draft")
    neutral = _neutral_plane(feature, part)
    angle = params.resolve(feature.inputs.angle_deg, f"{feature.id} draft angle")
    if angle == 0:
        raise CadEngineError(
            "DIMENSION_OUT_OF_RANGE",
            "feature",
            f"{feature.id} drafts by 0°, which leaves the walls where they are.",
        )

    before = float(part.volume)
    try:
        result = _draft(walls, neutral_plane=neutral, angle=angle)
    except CadEngineError:
        raise
    except Exception as error:  # noqa: BLE001 - OCCT throws bare, and sometimes empty
        raise CadEngineError(
            "DRAFT_TOO_STEEP",
            "feature",
            f"{feature.id} draws {len(walls)} wall(s) in by {angle}° and the kernel "
            f"refused it: {type(error).__name__} {error}. A draft steep enough to close "
            "the section it starts from has no solid to describe.",
        ) from error

    if result is None or not result.solids():
        raise CadEngineError(
            "DRAFT_TOO_STEEP",
            "feature",
            f"{feature.id} draws {len(walls)} wall(s) in by {angle}° and produced nothing.",
        )
    _require_a_solid_that_survived(feature, result, angle, before)
    return result


def _require_a_solid_that_survived(feature: DraftFeature, result, angle: float, before: float):
    """The two ways a draft comes back wrong while claiming to have worked.

    **The section closed.** At exactly the closing angle the kernel returns the
    degenerate solid — a pyramid where a frustum was asked for — and marks it invalid.
    Measured: 10 666.6667 mm³ on the 40 × 40 × 20 block at 45°, `is_valid` false. This
    is the first operation in this engine where the kernel volunteers that its answer
    is wrong, and exporting a shape it disowns would put a STEP nobody can open in
    front of a customer.

    **Nothing moved.** A draft whose faces the kernel declined to move returns the
    original solid, which is the shell's failure exactly (`SHELL_NO_CAVITY`) and the
    fourth time this kernel's failure mode has been a plausible answer.
    """
    if not _is_valid(result):
        raise CadEngineError(
            "DRAFT_TOO_STEEP",
            "feature",
            f"{feature.id} draws its walls in by {angle}° and the kernel returned a "
            f"solid it reports as invalid ({float(result.volume):.4f} mm³). At the angle "
            "that closes the section, the frustum the document asked for degenerates.",
        )
    if abs(float(result.volume) - before) <= _MOVED_TOLERANCE_MM3:
        raise CadEngineError(
            "DRAFT_MOVED_NOTHING",
            "feature",
            f"{feature.id} draws its walls in by {angle}° and the body is "
            f"{before:.4f} mm³ before and after. A feature that changed nothing is a "
            "draft the delivered part does not have.",
        )


def _is_valid(shape) -> bool:
    """`is_valid` is a property in build123d 0.11.1 and was a method before it.

    Read through `getattr` for that reason: calling a property raises
    `TypeError: 'bool' object is not callable`, which looks like a geometry failure
    and is not.
    """
    check = getattr(shape, "is_valid", None)
    if check is None:  # pragma: no cover - every Shape has one
        return True
    return bool(check() if callable(check) else check)


def _neutral_plane(feature: DraftFeature, part) -> Plane:
    """The plane of the face the document measures its draft from.

    Planar only, and refused rather than approximated: a cylinder has no single plane,
    and "the plane through the middle of it" is a position no drawing gave.
    """
    matched = _resolved(feature.inputs.neutral_face, feature, part, "as the neutral face")
    face = matched[0]
    try:
        # `Plane(face)` is the library's own planarity test — it raises
        # "Planes can only be created from planar faces". Asked first, because
        # `normal_at` answers happily for a cylinder: it returns the surface normal at
        # that point, so a check built on it would sail past a curved neutral face and
        # fail later as something else.
        Plane(face)
        centre = face.center()
        normal = face.normal_at(centre)
        # Turned to point **into** the material, and that is the whole of the sign
        # convention. `Plane(face)` takes the face's outward normal, and a base face
        # looks down and out of the part — so a positive angle read straight off it
        # narrows the part downwards and widens it going up, which is the opposite of
        # what a drawing that dimensions the base means. Measured both ways on a
        # 40 × 40 × 20 block: as-is gives 37 974.1029 mm³ from either the base or the
        # top, flipped gives 26 689.1761 from either. Flipped is the one where the
        # named face holds its size and the part narrows away from it, and it is the
        # same answer whichever end the document names — which is why the rule can be
        # stated at all.
        return Plane(origin=centre, z_dir=-normal)
    except CadEngineError:
        raise
    except Exception as error:  # noqa: BLE001 - a non-planar face has no single normal
        raise CadEngineError(
            "DRAFT_NEUTRAL_FACE_NOT_PLANAR",
            "selector",
            f"Selector {feature.inputs.neutral_face.id} names a face that is not planar, "
            f"so {feature.id} has no plane to measure its draft from.",
        ) from error


def _resolved(selector, feature: DraftFeature, part, what: str) -> list:
    """The kernel faces a selector names, or a refusal that says which clause emptied it."""
    resolution = resolve_faces(selector, read_faces(part))
    if not resolution.satisfied or not resolution.matched:
        raise CadEngineError(
            resolution.failure_code or "SELECTOR_NO_MATCH",
            "selector",
            f"Selector {selector.id} named {len(resolution.matched)} face(s) {what} for "
            f"{feature.id}, which its declared cardinality does not allow. "
            + narrowing(resolution),
        )
    return [descriptor.handle for descriptor in resolution.matched]


__all__ = ["draft"]
