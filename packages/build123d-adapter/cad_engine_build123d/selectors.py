"""Resolve a semantic selector against measured geometry.

Geometry is named by what it means, never by an index (ADR-019). A selector
carries predicates and a declared cardinality; this module filters the
descriptors by the predicates and then checks how many survived against what the
document said to expect.

**Predicates filter; they never score.** There is no closest match and no
confidence threshold, because a selector that quietly picks one of two equally
good faces is a selector that builds a different part on a different day. When
the count does not match the declared cardinality the resolution fails and
carries a trace saying which predicate removed what — the trace is the difference
between "the selector found nothing" and knowing which clause was wrong.

Pure: it takes descriptors, not kernel handles, so the whole matching layer is
testable on a machine with no CAD library. Reading the topology is the other half
and lives in `topology.py`.

Ported from the C# resolver this engine replaces, predicate for predicate and
tolerance for tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from .errors import CadEngineError

#: How close two positions must be to count as the same extreme.
#:
#: An extreme is a ranking, so two faces at the same height have to come out as a
#: tie rather than as an arbitrary winner. Without this the answer would depend
#: on floating-point noise, which is exactly the non-determinism selectors exist
#: to remove.
EXTREME_TOLERANCE_MM = 1e-6


@dataclass(frozen=True)
class ResolutionStep:
    predicate: str
    before: int
    after: int


@dataclass(frozen=True)
class Resolution:
    """What a selector matched, and how it got there."""

    selector_id: str
    matched: tuple
    trace: tuple[ResolutionStep, ...] = field(default_factory=tuple)
    failure_code: str | None = None

    @property
    def satisfied(self) -> bool:
        return self.failure_code is None


def resolve_faces(selector, faces: Sequence) -> Resolution:
    where = selector.where
    steps: list[ResolutionStep] = []
    candidates = list(faces)

    candidates = _filter(
        candidates, steps, "surface_type", where.surface_type,
        lambda face, value: face.surface_type == str(value),
    )
    candidates = _filter(
        candidates, steps, "normal", where.normal,
        lambda face, value: _matches_normal(face.normal, value),
    )
    candidates = _filter(
        candidates, steps, "area_mm2", where.area_mm2,
        lambda face, value: _within(face.area_mm2, value),
    )
    candidates = _filter(
        candidates, steps, "radius_mm", where.radius_mm,
        lambda face, value: _within(face.radius_mm, value),
    )
    candidates = _filter(
        candidates, steps, "adjacent", where.adjacent,
        lambda face, value: _matches_adjacency(
            face.adjacent_surface_types, face.adjacent_face_count, value
        ),
    )
    # Position last, and the extreme after the centre: an extreme is a ranking
    # over whatever survived, not a test on a single face, so applying it before
    # the other predicates would rank the wrong population.
    candidates = _apply_position(candidates, steps, where.position)
    return _conclude(selector, candidates, steps)


def resolve_edges(selector, edges: Sequence) -> Resolution:
    where = selector.where
    steps: list[ResolutionStep] = []
    candidates = list(edges)

    candidates = _filter(
        candidates, steps, "curve_type", where.curve_type,
        lambda edge, value: edge.curve_type == str(value),
    )
    candidates = _filter(
        candidates, steps, "length_mm", where.length_mm,
        lambda edge, value: _within(edge.length_mm, value),
    )
    candidates = _filter(
        candidates, steps, "radius_mm", where.radius_mm,
        lambda edge, value: _within(edge.radius_mm, value),
    )
    candidates = _filter(
        candidates, steps, "direction_parallel_to", where.direction_parallel_to,
        lambda edge, value: _is_parallel(edge.direction, value),
    )
    candidates = _filter(
        candidates, steps, "adjacent", where.adjacent,
        lambda edge, value: _matches_adjacency(
            edge.adjacent_surface_types, edge.adjacent_face_count, value
        ),
    )
    candidates = _apply_position(candidates, steps, where.position)
    return _conclude(selector, candidates, steps)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _filter(candidates: list, steps: list, name: str, value, predicate: Callable) -> list:
    """Apply one predicate, and record what it removed.

    A predicate the document did not state is not applied and not traced: a step
    saying "surface_type removed nothing" when the document never mentioned
    surface types would pad every trace with clauses nobody wrote.
    """
    if value is None:
        return candidates
    before = len(candidates)
    kept = [item for item in candidates if predicate(item, value)]
    steps.append(ResolutionStep(name, before, len(kept)))
    return kept


def _apply_position(candidates: list, steps: list, position) -> list:
    if position is None:
        return candidates

    if position.center_along is not None and position.center_value_mm is not None:
        axis = _axis_index(position.center_along)
        before = len(candidates)
        candidates = [
            item
            for item in candidates
            if _within(item.centroid[axis], position.center_value_mm)
        ]
        steps.append(ResolutionStep(f"centre on {'xyz'[axis]}", before, len(candidates)))

    if position.extreme_along is not None and position.extreme is not None:
        axis = "xyz"[_axis_index(position.extreme_along)]
        extreme = str(position.extreme)
        before = len(candidates)
        if not candidates:
            steps.append(ResolutionStep(f"{extreme} position on {axis}", 0, 0))
            return candidates
        if extreme == "maximum":
            measure = lambda item: item.bounds.max_along(axis)  # noqa: E731
            best = max(measure(item) for item in candidates)
        else:
            measure = lambda item: item.bounds.min_along(axis)  # noqa: E731
            best = min(measure(item) for item in candidates)
        candidates = [
            item for item in candidates if abs(measure(item) - best) <= EXTREME_TOLERANCE_MM
        ]
        steps.append(ResolutionStep(f"{extreme} position on {axis}", before, len(candidates)))

    return candidates


def _conclude(selector, matched: list, steps: list) -> Resolution:
    code = _cardinality_failure(selector.cardinality, len(matched))
    return Resolution(
        selector_id=str(selector.id),
        matched=tuple(matched),
        trace=tuple(steps),
        failure_code=code,
    )


def _cardinality_failure(cardinality, count: int) -> str | None:
    """Which way the count missed, or nothing.

    Too few and too many are different mistakes in a document and get different
    codes: one means the predicates described nothing in the part, the other
    means they described a family and the document expected an individual.
    """
    kind = getattr(cardinality, "type", None) or str(cardinality)
    expected = getattr(cardinality, "value", None)

    if kind == "exactly_one":
        if count == 1:
            return None
        return "SELECTOR_NO_MATCH" if count == 0 else "SELECTOR_AMBIGUOUS"
    if kind == "zero_or_one":
        return None if count <= 1 else "SELECTOR_AMBIGUOUS"
    if kind == "one_or_more":
        return None if count >= 1 else "SELECTOR_NO_MATCH"
    if kind == "all":
        return None
    if kind == "exactly_n":
        if count == expected:
            return None
        return "SELECTOR_NO_MATCH" if count < expected else "SELECTOR_AMBIGUOUS"
    return "SELECTOR_NO_MATCH"


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _within(measured: float | None, measurement) -> bool:
    """Is the measurement within the tolerance the document stated?

    A missing measurement never matches. A face whose radius could not be taken
    is not a face of radius 5, and treating "unknown" as "close enough" is how a
    selector picks something for a reason that is not true of it.
    """
    if measured is None:
        return False
    return abs(measured - float(measurement.value)) <= float(measurement.tolerance)


def _axis_index(axis) -> int:
    """Which coordinate an axis names.

    The contract spells an axis `axis.z`, so the name has to be taken apart
    rather than indexed directly. Done in one place because getting it wrong is
    silent: `"xyz".index("axis.z")` raises, but a wrong *offset* would quietly
    measure the wrong coordinate and pick the wrong face.
    """
    name = str(axis).rsplit(".", 1)[-1].lower()
    if name not in "xyz" or len(name) != 1:
        raise CadEngineError(
            "SELECTOR_INVALID", "selector", f"{axis} is not one of the three axes."
        )
    return "xyz".index(name)


def _is_parallel(vector: tuple[float, float, float] | None, axis) -> bool:
    if vector is None:
        return False
    index = _axis_index(axis)
    others = [value for position, value in enumerate(vector) if position != index]
    return abs(vector[index]) > 1e-9 and all(abs(value) <= 1e-9 for value in others)


def _matches_normal(normal: tuple[float, float, float] | None, predicate) -> bool:
    if normal is None:
        return False
    if predicate.parallel_to is not None and not _is_parallel(normal, predicate.parallel_to):
        return False
    if predicate.perpendicular_to is not None:
        index = _axis_index(predicate.perpendicular_to)
        if abs(normal[index]) > 1e-9:
            return False
    if predicate.direction is not None:
        axis = predicate.parallel_to or predicate.perpendicular_to
        if axis is None:
            # A direction with no axis to be a direction along says nothing. The
            # contract lets the two be written apart; here they have to meet.
            return False
        value = normal[_axis_index(axis)]
        return value > 0 if str(predicate.direction) == "positive" else value < 0
    return True


def _matches_adjacency(surfaces: tuple[str, ...], face_count: int, predicate) -> bool:
    wanted = {str(item) for item in predicate.contains_surface_types}
    if not wanted.issubset(set(surfaces)):
        return False
    if predicate.face_count is not None and face_count != predicate.face_count:
        return False
    return True


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def require_one(resolution: Resolution, selector):
    """The single thing a selector named, or a typed failure with its trace."""
    if resolution.satisfied and len(resolution.matched) == 1:
        return resolution.matched[0]
    if resolution.satisfied and resolution.matched:
        raise CadEngineError(
            "SELECTOR_AMBIGUOUS",
            "selector",
            f"Selector {selector.id} matched {len(resolution.matched)} things where one "
            f"was needed. {_trace(resolution)}",
        )
    raise CadEngineError(
        resolution.failure_code or "SELECTOR_NO_MATCH",
        "selector",
        f"Selector {selector.id} matched {len(resolution.matched)} things, which its "
        f"declared cardinality does not allow. {_trace(resolution)}",
    )


def _trace(resolution: Resolution) -> str:
    if not resolution.trace:
        return "No predicate was stated, so nothing narrowed the candidates."
    return "Narrowing: " + "; ".join(
        f"{step.predicate} {step.before} -> {step.after}" for step in resolution.trace
    )


__all__ = [
    "EXTREME_TOLERANCE_MM",
    "Resolution",
    "ResolutionStep",
    "require_one",
    "resolve_edges",
    "resolve_faces",
]
