import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .errors import CadIrValidationError, ValidationIssue
from .expression import ExpressionError, evaluate_expression, referenced_parameters
from .models import CadIrDocument, ParameterStatus


class CadIrValidator:
    def __init__(self, schema_path: Path | None = None):
        schema_path = schema_path or _default_schema_path()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._schema = Draft202012Validator(schema)

    def validate(self, value: dict[str, Any]) -> CadIrDocument:
        issues = [
            ValidationIssue(
                "SCHEMA_INVALID",
                _json_path(error.absolute_path),
                error.message,
            )
            for error in sorted(self._schema.iter_errors(value), key=lambda item: list(item.absolute_path))
        ]
        if issues:
            raise CadIrValidationError(issues)
        try:
            document = CadIrDocument.model_validate(value)
        except ValidationError as error:
            raise CadIrValidationError(
                [
                    ValidationIssue("TYPED_MODEL_INVALID", _location_path(item["loc"]), item["msg"])
                    for item in error.errors()
                ]
            ) from error
        semantic_issues = self._semantic_issues(document)
        if semantic_issues:
            raise CadIrValidationError(semantic_issues)
        return document

    def validate_json(self, payload: str | bytes) -> CadIrDocument:
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CadIrValidationError(
                [ValidationIssue("JSON_INVALID", "$", f"invalid JSON at offset {error.pos}")]
            ) from error
        if not isinstance(value, dict):
            raise CadIrValidationError(
                [ValidationIssue("SCHEMA_INVALID", "$", "CAD-IR root must be an object")]
            )
        return self.validate(value)

    def _semantic_issues(self, document: CadIrDocument) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        parameter_ids = [parameter.id for parameter in document.parameters]
        feature_ids = [feature.id for feature in document.features]
        invariant_ids = [invariant.id for invariant in document.expected_invariants]
        issues.extend(_duplicates(parameter_ids, "$.parameters"))
        issues.extend(_duplicates(feature_ids, "$.features"))
        issues.extend(_duplicates(invariant_ids, "$.expected_invariants"))

        known_features = set(feature_ids)
        for index, feature in enumerate(document.features):
            for dependency in feature.depends_on:
                if dependency not in known_features:
                    issues.append(
                        ValidationIssue(
                            "REFERENCE_NOT_FOUND",
                            f"$.features[{index}].depends_on",
                            f"unknown feature dependency: {dependency}",
                        )
                    )
                if dependency == feature.id:
                    issues.append(
                        ValidationIssue(
                            "FEATURE_GRAPH_CYCLE",
                            f"$.features[{index}].depends_on",
                            "feature cannot depend on itself",
                        )
                    )
        issues.extend(_cycle_issues(document))

        parameters = {parameter.id: parameter for parameter in document.parameters}
        numeric_values = {parameter.id: parameter.value for parameter in document.parameters}
        for feature_index, feature in enumerate(document.features):
            if not feature.enabled:
                continue
            for path, reference_type, content in _walk_values(
                feature.inputs, f"$.features[{feature_index}].inputs"
            ):
                if reference_type == "param":
                    parameter = parameters.get(content)
                    if parameter is None:
                        issues.append(
                            ValidationIssue("PARAMETER_NOT_FOUND", path, f"unknown parameter: {content}")
                        )
                    elif parameter.status == ParameterStatus.UNRESOLVED:
                        issues.append(
                            ValidationIssue(
                                "UNRESOLVED_PARAMETER_USED",
                                path,
                                f"buildable feature uses unresolved parameter: {content}",
                            )
                        )
                else:
                    try:
                        for parameter_id in referenced_parameters(content):
                            parameter = parameters.get(parameter_id)
                            if parameter is not None and parameter.status == ParameterStatus.UNRESOLVED:
                                issues.append(
                                    ValidationIssue(
                                        "UNRESOLVED_PARAMETER_USED",
                                        path,
                                        f"buildable feature expression uses unresolved parameter: {parameter_id}",
                                    )
                                )
                        evaluate_expression(content, numeric_values)
                    except ExpressionError as error:
                        issues.append(ValidationIssue("EXPRESSION_INVALID", path, str(error)))

        invariant_types = {invariant.type for invariant in document.expected_invariants}
        for required in ("bounding_box", "solid_body_count"):
            if required not in invariant_types:
                issues.append(
                    ValidationIssue(
                        "REQUIRED_INVARIANT_MISSING",
                        "$.expected_invariants",
                        f"required invariant is missing: {required}",
                    )
                )
        return issues


def _default_schema_path() -> Path:
    configured = os.environ.get("CAD_IR_SCHEMA_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(__file__).resolve().parent / "cad-ir.schema.json",
        Path("/schemas/cad-ir.schema.json"),
    ]
    module_path = Path(__file__).resolve()
    if len(module_path.parents) > 3:
        candidates.insert(1, module_path.parents[3] / "schemas" / "cad-ir.schema.json")
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("cad-ir.schema.json was not found; set CAD_IR_SCHEMA_PATH")


def _walk_values(value: Any, path: str) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        if set(value) == {"param"} and isinstance(value["param"], str):
            yield path, "param", value["param"]
            return
        if set(value) == {"expr"} and isinstance(value["expr"], str):
            yield path, "expr", value["expr"]
            return
        for key, child in value.items():
            yield from _walk_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_values(child, f"{path}[{index}]")


def _duplicates(values: list[str], path: str) -> list[ValidationIssue]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return [
        ValidationIssue("DUPLICATE_ID", path, f"duplicate id: {value}")
        for value in sorted(duplicates)
    ]


def _cycle_issues(document: CadIrDocument) -> list[ValidationIssue]:
    graph = {feature.id: feature.depends_on for feature in document.features}
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        cyclic = any(dependency in graph and visit(dependency) for dependency in graph[node])
        state[node] = 2
        return cyclic

    if any(visit(node) for node in graph):
        return [
            ValidationIssue("FEATURE_GRAPH_CYCLE", "$.features", "feature dependency graph is cyclic")
        ]
    return []


def _json_path(parts: Any) -> str:
    path = "$"
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _location_path(parts: tuple[Any, ...]) -> str:
    return _json_path(parts)
