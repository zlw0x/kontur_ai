"""The trusted gate in front of canonical CAD-IR.

The schema says the document is well-formed. This says it means something: the
feature graph is acyclic and ordered, every reference resolves, and nothing in
it describes how to drive KOMPAS rather than what the part is.

It runs before any COM object exists. Everything it rejects, it rejects while
the cost of being wrong is a typed error rather than a half-built model on the
owner's machine.
"""

from __future__ import annotations

import re
from typing import Any

from .canonical import (
    CAD_IR_VERSION,
    MIGRATABLE_VERSIONS,
    SUPPORTED_VERSIONS,
    CadIrDocument,
    CutExtrudeFeature,
    CutLoftFeature,
    CutRevolveFeature,
    CutSweepFeature,
    PatternFeature,
    ParameterRef,
    ParameterStatus,
    ResultKind,
    ResultRef,
    SolidExtrudeFeature,
    SolidLoftFeature,
    SolidRevolveFeature,
    SolidSweepFeature,
    declared_version,
)
from .errors import CadIrValidationError, ValidationIssue
from .selectors import EdgeSelector, FaceSelector

#: What a pattern may repeat: the features that make material, and a pattern, which
#: is how a grid is written (ADR-027).
_REPEATABLE = (
    SolidExtrudeFeature,
    CutExtrudeFeature,
    SolidRevolveFeature,
    CutRevolveFeature,
    SolidSweepFeature,
    CutSweepFeature,
    SolidLoftFeature,
    CutLoftFeature,
    PatternFeature,
)

#: Text that has no business in a document describing geometric intent.
#: The closed schema is the first defence — a COM handle has no field to live
#: in. This is the second: a path or a command smuggled through a free-text
#: name, label or note.
_EXECUTION_DETAIL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a Windows path", re.compile(r"(?:^|[\s\"'=])[A-Za-z]:[\\/]")),
    ("a UNC path", re.compile(r"\\\\[^\\\s]")),
    ("a parent-directory traversal", re.compile(r"\.\.[\\/]")),
    ("an executable or script file", re.compile(r"\.(?:exe|dll|ps1|bat|cmd|sh|py|vbs)\b", re.I)),
    ("an interpreter or shell", re.compile(r"\b(?:powershell|cmd\.exe|/bin/(?:ba)?sh|python\d?)\b", re.I)),
    ("a COM identifier", re.compile(r"\b(?:com_?handle|progid|iunknown|iface_ptr|0x[0-9a-f]{6,})\b", re.I)),
    ("a raw topology index", re.compile(r"\b(?:face|edge|vertex|body)[_\s]*(?:index|id|no)\s*[:=#]?\s*\d+", re.I)),
)


def validate_canonical(value: dict[str, Any]) -> CadIrDocument:
    """Parse and check a canonical document, or raise with every issue found."""
    _require_supported_version(value)
    try:
        document = CadIrDocument(**value)
    except Exception as error:  # pydantic ValidationError, reported as issues
        raise CadIrValidationError(_schema_issues(error)) from error

    issues = (
        _feature_graph_issues(document)
        + _body_issues(document)
        + _selector_issues(document)
        + _parameter_issues(document)
        + _expectation_issues(document)
        + _execution_detail_issues(value)
    )
    if issues:
        raise CadIrValidationError(issues)
    return document


def _require_supported_version(value: dict[str, Any]) -> None:
    """Check the version before reading anything else.

    A document from a future build may use a field this one would silently
    ignore, so the version is not something to discover halfway through.
    """
    version = declared_version(value)
    if version is None:
        raise CadIrValidationError(
            [ValidationIssue("CAD_IR_VERSION_MISSING", "$.schema_version", "the document declares no version")]
        )
    if version in SUPPORTED_VERSIONS:
        return
    if version in MIGRATABLE_VERSIONS:
        raise CadIrValidationError(
            [
                ValidationIssue(
                    "CAD_IR_VERSION_UNSUPPORTED",
                    "$.schema_version",
                    f"version {version} must be normalised to {CAD_IR_VERSION} before validation",
                )
            ]
        )
    if _is_newer(version, CAD_IR_VERSION):
        raise CadIrValidationError(
            [
                ValidationIssue(
                    "CAD_IR_VERSION_TOO_NEW",
                    "$.schema_version",
                    f"version {version} is newer than {CAD_IR_VERSION}; this build cannot read it",
                )
            ]
        )
    raise CadIrValidationError(
        [ValidationIssue("CAD_IR_VERSION_UNSUPPORTED", "$.schema_version", f"unsupported version {version}")]
    )


def _is_newer(candidate: str, baseline: str) -> bool:
    def parts(version: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in version.split("."))
        except ValueError:
            return ()

    left, right = parts(candidate), parts(baseline)
    if not left:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def _feature_graph_issues(document: CadIrDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    position: dict[str, int] = {}
    for index, feature in enumerate(document.features):
        path = f"$.features[{index}]"
        if feature.id in seen:
            issues.append(
                ValidationIssue("FEATURE_ID_DUPLICATE", path, f"duplicate feature id: {feature.id}")
            )
        seen.add(feature.id)
        position.setdefault(feature.id, index)

    for index, feature in enumerate(document.features):
        path = f"$.features[{index}].depends_on"
        for dependency in feature.depends_on:
            if dependency == feature.id:
                issues.append(
                    ValidationIssue("FEATURE_SELF_REFERENCE", path, f"{feature.id} depends on itself")
                )
            elif dependency not in seen:
                issues.append(
                    ValidationIssue(
                        "FEATURE_DEPENDENCY_MISSING", path, f"unknown dependency: {dependency}"
                    )
                )
            elif position[dependency] > index:
                # Features are built in array order, so a dependency further
                # down the list would be built after the feature needing it.
                issues.append(
                    ValidationIssue(
                        "FEATURE_ORDER_INVALID",
                        path,
                        f"{feature.id} depends on {dependency}, which is declared after it",
                    )
                )
    issues.extend(_cycle_issues(document))
    issues.extend(_result_issues(document, position))
    issues.extend(_pattern_issues(document, position))
    return issues


def _pattern_issues(document: CadIrDocument, position: dict[str, int]) -> list[ValidationIssue]:
    """A pattern repeats a feature that exists, runs first, and is switched on.

    The last of those is the one worth having. A pattern of six adds five instances
    to what the source feature already built, so a document that disables the source
    and leaves the pattern enabled asks for five holes around a hole that is not
    there — five instances at offsets from a position nothing occupies. It builds, and
    it is not the part anyone drew.
    """
    issues: list[ValidationIssue] = []
    by_id = {feature.id: feature for feature in document.features}
    for index, feature in enumerate(document.features):
        if not isinstance(feature, PatternFeature):
            continue
        path = f"$.features[{index}].inputs.of"
        source = by_id.get(feature.inputs.of)
        if source is None:
            issues.append(
                ValidationIssue(
                    "FEATURE_DEPENDENCY_MISSING",
                    path,
                    f"{feature.id} repeats {feature.inputs.of}, which no feature declares",
                )
            )
            continue
        if position.get(source.id, index) >= index:
            issues.append(
                ValidationIssue(
                    "FEATURE_ORDER_INVALID",
                    path,
                    f"{feature.id} repeats {source.id}, which is not built before it",
                )
            )
        if source.id not in feature.depends_on:
            # The graph is what the build order comes from, so a pattern that used a
            # feature without depending on it would be correct only by accident.
            issues.append(
                ValidationIssue(
                    "FEATURE_DEPENDENCY_MISSING",
                    path,
                    f"{feature.id} repeats {source.id} but does not depend on it",
                )
            )
        if feature.enabled and not source.enabled:
            issues.append(
                ValidationIssue(
                    "FEATURE_DISABLED_SOURCE",
                    path,
                    f"{feature.id} repeats {source.id}, which the document has disabled; "
                    "a pattern adds instances to the one the source built",
                )
            )
        if not isinstance(source, _REPEATABLE):
            # A pattern re-runs the operation that made material, at an offset. An
            # operation that made none has nothing to re-run: a plane is not somewhere
            # a second copy could go, and a blend or a shell modifies the body that is
            # already there, so repeating one would mean applying it again to the same
            # solid. Stated once, for every kind at once — naming the plane alone left
            # the others to fail later, in the engine, as an unsupported tool.
            issues.append(
                ValidationIssue(
                    "UNSUPPORTED_FEATURE_SET",
                    path,
                    f"{feature.id} repeats {source.id}, which modifies the body rather "
                    "than making material a pattern could place a copy of",
                )
            )
        if source.id == feature.id:  # pragma: no cover - the cycle check has it too
            issues.append(
                ValidationIssue("FEATURE_SELF_REFERENCE", path, f"{feature.id} repeats itself")
            )
    return issues


def _cycle_issues(document: CadIrDocument) -> list[ValidationIssue]:
    graph = {feature.id: list(feature.depends_on) for feature in document.features}
    visiting: set[str] = set()
    done: set[str] = set()
    cycles: list[str] = []

    def visit(node: str) -> None:
        if node in done or node not in graph:
            return
        if node in visiting:
            cycles.append(node)
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.discard(node)
        done.add(node)

    for node in graph:
        visit(node)
    return [
        ValidationIssue(
            "FEATURE_DEPENDENCY_CYCLE", "$.features", f"feature dependency cycle through {node}"
        )
        for node in sorted(set(cycles))
    ]


def _result_issues(document: CadIrDocument, position: dict[str, int]) -> list[ValidationIssue]:
    """A referenced result must exist and must already have been produced."""
    issues: list[ValidationIssue] = []
    produced_by: dict[str, str] = {}
    for index, feature in enumerate(document.features):
        for result in feature.produces:
            if result.id in produced_by:
                issues.append(
                    ValidationIssue(
                        "FEATURE_ID_DUPLICATE",
                        f"$.features[{index}].produces",
                        f"result {result.id} is produced by more than one feature",
                    )
                )
            produced_by.setdefault(result.id, feature.id)

    for index, feature in enumerate(document.features):
        for path, reference in _references(feature.inputs, f"$.features[{index}].inputs", ResultRef):
            producer = produced_by.get(reference.result)
            if producer is None:
                issues.append(
                    ValidationIssue(
                        "FEATURE_RESULT_UNAVAILABLE", path, f"no feature produces {reference.result}"
                    )
                )
            elif position.get(producer, index) >= index:
                issues.append(
                    ValidationIssue(
                        "FEATURE_RESULT_UNAVAILABLE",
                        path,
                        f"{reference.result} is produced by {producer}, which does not run first",
                    )
                )
            elif producer not in feature.depends_on:
                issues.append(
                    ValidationIssue(
                        "FEATURE_DEPENDENCY_MISSING",
                        path,
                        f"{feature.id} uses {reference.result} but does not depend on {producer}",
                    )
                )
    return issues


def _body_issues(document: CadIrDocument) -> list[ValidationIssue]:
    """A feature that starts a body must name it, and a boolean must have one to work on.

    A body nothing can name is a body no selector and no boolean can reach, so it could
    never be cut, blended or combined — it would arrive in the delivered STEP as a lump
    with no history. The name is the `produces` entry, which every other operation
    already uses to say what it made.
    """
    issues: list[ValidationIssue] = []
    for index, feature in enumerate(document.features):
        if not getattr(feature.inputs, "new_body", False):
            continue
        bodies = [
            result for result in feature.produces if result.kind is ResultKind.SOLID_BODY
        ]
        if len(bodies) != 1:
            issues.append(
                ValidationIssue(
                    "CAD_IR_INVALID",
                    f"$.features[{index}].produces",
                    f"{feature.id} starts a body of its own and must name exactly one "
                    f"solid_body result; it names {len(bodies)}",
                )
            )
    return issues


def _selector_issues(document: CadIrDocument) -> list[ValidationIssue]:
    """A selector's `from_result` must name a body an earlier feature built.

    `from_result` is a plain id rather than a `ResultRef`, so the reference walk
    above does not see it, and until CAD-IR 1.5 nothing checked it at all: a
    selector could name a body no feature produces and the engine would resolve
    against whatever it had. That was survivable while the only selector in the
    contract chose a sketch plane. A fillet is *entirely* a selector, and one
    naming a body that does not exist would blend the wrong thing rather than fail.

    Two ids are also required to be unique across the document, because a selector
    id is what a resolution trace and a repair prompt name.
    """
    issues: list[ValidationIssue] = []
    bodies: dict[str, int] = {}
    for index, feature in enumerate(document.features):
        for result in feature.produces:
            if result.kind is ResultKind.SOLID_BODY:
                bodies.setdefault(result.id, index)

    seen: dict[str, str] = {}
    for index, feature in enumerate(document.features):
        for path, selector in _selectors(feature.inputs, f"$.features[{index}].inputs"):
            if selector.id in seen:
                issues.append(
                    ValidationIssue(
                        "DUPLICATE_ID",
                        f"{path}.id",
                        f"selector {selector.id} is declared more than once",
                    )
                )
            seen.setdefault(selector.id, feature.id)

            produced_at = bodies.get(selector.from_result)
            if produced_at is None:
                issues.append(
                    ValidationIssue(
                        "FEATURE_RESULT_UNAVAILABLE",
                        f"{path}.from_result",
                        f"selector {selector.id} names the body {selector.from_result}, "
                        "which no feature produces",
                    )
                )
            elif produced_at >= index:
                issues.append(
                    ValidationIssue(
                        "FEATURE_RESULT_UNAVAILABLE",
                        f"{path}.from_result",
                        f"selector {selector.id} names {selector.from_result}, which is "
                        "not built before the feature that selects on it",
                    )
                )
    return issues


def _selectors(value: Any, path: str):
    """Every face or edge selector in a parsed inputs tree, with its path."""
    if isinstance(value, (FaceSelector, EdgeSelector)):
        yield path, value
        return
    if hasattr(value, "__pydantic_fields__"):
        for name in type(value).model_fields:
            yield from _selectors(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _selectors(child, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _selectors(child, f"{path}.{key}")


def _parameter_issues(document: CadIrDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known: dict[str, ParameterStatus] = {}
    for index, parameter in enumerate(document.parameters):
        if parameter.id in known:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_ID", f"$.parameters[{index}]", f"duplicate parameter id: {parameter.id}"
                )
            )
        known.setdefault(parameter.id, parameter.status)

    for index, feature in enumerate(document.features):
        if not feature.enabled:
            continue
        for path, reference in _references(feature.inputs, f"$.features[{index}].inputs", ParameterRef):
            status = known.get(reference.parameter)
            if status is None:
                issues.append(
                    ValidationIssue(
                        "PARAMETER_NOT_FOUND", path, f"unknown parameter: {reference.parameter}"
                    )
                )
            elif status is ParameterStatus.UNRESOLVED:
                # An unresolved value is a question that was never answered.
                # Building with it would silently invent a dimension.
                issues.append(
                    ValidationIssue(
                        "UNRESOLVED_PARAMETER_USED",
                        path,
                        f"an enabled feature uses unresolved parameter: {reference.parameter}",
                    )
                )
    return issues


def _expectation_issues(document: CadIrDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for index, expectation in enumerate(document.expectations):
        if expectation.id in seen:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_ID", f"$.expectations[{index}]", f"duplicate expectation id: {expectation.id}"
                )
            )
        seen.add(expectation.id)

    present = {expectation.type for expectation in document.expectations}
    for required in ("bounding_box", "body_count"):
        if required not in present:
            # Without these an independent verifier has nothing to check the
            # produced solid against, and a wrong model looks like a right one.
            issues.append(
                ValidationIssue(
                    "REQUIRED_EXPECTATION_MISSING",
                    "$.expectations",
                    f"required expectation is missing: {required}",
                )
            )
    return issues


def _execution_detail_issues(value: Any, path: str = "$") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if isinstance(value, dict):
        for key, child in value.items():
            issues.extend(_execution_detail_issues(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_execution_detail_issues(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        for description, pattern in _EXECUTION_DETAIL_PATTERNS:
            if pattern.search(value):
                issues.append(
                    ValidationIssue(
                        "EXECUTION_DETAIL_PRESENT",
                        path,
                        f"CAD-IR describes intent, not execution; this looks like {description}",
                    )
                )
                break
    return issues


def _references(value: Any, path: str, kind: type):
    """Walk a parsed inputs tree yielding typed references and their paths."""
    if isinstance(value, kind):
        yield path, value
        return
    if hasattr(value, "__pydantic_fields__"):
        for name in type(value).model_fields:
            yield from _references(getattr(value, name), f"{path}.{name}", kind)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _references(child, f"{path}[{index}]", kind)
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _references(child, f"{path}.{key}", kind)


def _schema_issues(error: Exception) -> list[ValidationIssue]:
    errors = getattr(error, "errors", None)
    if not callable(errors):
        return [ValidationIssue("SCHEMA_INVALID", "$", str(error))]
    issues = []
    for item in errors():
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"]
        )
        issues.append(ValidationIssue("SCHEMA_INVALID", location, item["msg"]))
    return issues
