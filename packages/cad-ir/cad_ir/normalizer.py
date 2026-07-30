"""Lift an older document into the canonical form.

Normalisation is a translation, not a repair. It renames and restructures what
the older version already said; it never fills in a value, relaxes a constraint
or guesses at intent. Anything the canonical version cannot express is a typed
`CAD_IR_MIGRATION_FAILED` rather than a silent approximation — a migration that
quietly drops a recorded assumption is worse than one that refuses.

Three paths arriving at the canonical version. 0.1.0 and 1.1 share the sketch
translation, because both express exactly the same two shapes — a centred
rectangle and a circle — and each of those becomes a contour. 1.2 needs no
translation at all: 1.3 only adds names, constraints and dimensions, so a 1.2
document is already a 1.3 document that happens to use none of them.

The original document is kept as an artifact and its hash is recorded in the
lineage, so nothing an older version carried is lost even where the canonical
form has no slot for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .canonical import (
    CAD_IR_SCHEMA,
    CAD_IR_VERSION,
    CadIrDocument,
    DocumentMetadata,
    canonical_json,
    declared_version,
    sha256_of,
)
from .canonical_validator import validate_canonical
from .errors import CadIrValidationError, ValidationIssue

#: Bumped whenever this translation changes. Two documents normalised by
#: different versions may differ, and the lineage has to say which produced
#: the canonical form on file.
NORMALIZER_VERSION = "1.2"

LEGACY_VERSION = "0.1.0"
SKETCH_ENTITY_VERSION = "1.1"
PRE_CONSTRAINT_VERSION = "1.2"

_FEATURE_TYPES = {"extrude_add": "solid.extrude", "extrude_cut": "cut.extrude"}

_RESULT_KINDS = {"body": "solid_body", "face": "face", "edge": "edge", "sketch": "sketch"}

_EXPECTATION_TYPES = {
    "solid_body_count": "body_count",
    "hole_count": "through_hole_count",
    "bounding_box": "bounding_box",
}


@dataclass(frozen=True, slots=True)
class Lineage:
    """What the canonical document came from.

    Stored beside the artifact rather than inside it: a document that recorded
    its own hash could not have one.
    """

    original_schema_version: str
    canonical_schema_version: str
    original_sha256: str
    canonical_sha256: str
    normalizer_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "original_schema_version": self.original_schema_version,
            "canonical_schema_version": self.canonical_schema_version,
            "original_sha256": self.original_sha256,
            "canonical_sha256": self.canonical_sha256,
            "normalizer_version": self.normalizer_version,
        }


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    document: CadIrDocument
    canonical_json: str
    lineage: Lineage


def normalize(value: dict[str, Any], metadata: DocumentMetadata | None = None) -> NormalizationResult:
    """Return the canonical 1.1 form of `value`, whatever version it declares.

    Normalising an already-canonical document is a no-op beyond re-hashing, so
    running this twice is safe and yields byte-identical output.
    """
    if not isinstance(value, dict):
        raise _failed("$", "CAD-IR root must be an object")
    original_sha256 = sha256_of(canonical_json(value))
    version = declared_version(value)

    if version == CAD_IR_VERSION:
        document = validate_canonical(value)
    elif version == LEGACY_VERSION:
        document = validate_canonical(_translate(value, metadata))
    elif version == SKETCH_ENTITY_VERSION:
        document = validate_canonical(_relabel(_lift_sketches(value)))
    elif version == PRE_CONSTRAINT_VERSION:
        # Purely additive: 1.3 only adds names, constraints and dimensions, and
        # a 1.2 document has none of them. Nothing about the part changes, so
        # this is the one migration that is genuinely a relabelling.
        document = validate_canonical(_relabel(value))
    elif version is None:
        raise CadIrValidationError(
            [ValidationIssue("CAD_IR_VERSION_MISSING", "$.schema_version", "the document declares no version")]
        )
    else:
        # Deliberately not attempted. Guessing at the shape of an unknown
        # version is how a migration silently changes a part.
        raise CadIrValidationError(
            [
                ValidationIssue(
                    "CAD_IR_VERSION_UNSUPPORTED",
                    "$.schema_version",
                    f"no migration path from version {version} to {CAD_IR_VERSION}",
                )
            ]
        )

    canonical = document.canonical_json()
    return NormalizationResult(
        document=document,
        canonical_json=canonical,
        lineage=Lineage(
            original_schema_version=version,
            canonical_schema_version=CAD_IR_VERSION,
            original_sha256=original_sha256,
            canonical_sha256=sha256_of(canonical),
            normalizer_version=NORMALIZER_VERSION,
        ),
    )


def _translate(value: dict[str, Any], metadata: DocumentMetadata | None) -> dict[str, Any]:
    part = _require(value, "part", "$")
    _require_empty(value, "unresolved")
    _require_empty(value, "assumptions")
    header: dict[str, Any] = {
        "units": part.get("units", "mm"),
        "part_type": "single_part",
        "coordinate_system": "right_handed",
    }
    if part.get("name"):
        header["name"] = part["name"]
    return {
        "schema": CAD_IR_SCHEMA,
        "schema_version": CAD_IR_VERSION,
        "document": header,
        "parameters": [
            _parameter(item, index) for index, item in enumerate(_require(value, "parameters", "$"))
        ],
        "features": _features(_require(value, "features", "$")),
        "expectations": [
            _expectation(item, index)
            for index, item in enumerate(_require(value, "expected_invariants", "$"))
        ],
        "metadata": (metadata or _default_metadata()).model_dump(mode="json", exclude_none=True),
    }


def _default_metadata() -> DocumentMetadata:
    return DocumentMetadata(generator="cad-ir-normalizer", generator_version=NORMALIZER_VERSION)


def _parameter(item: dict[str, Any], index: int) -> dict[str, Any]:
    path = f"$.parameters[{index}]"
    unit = item.get("unit")
    if unit != "mm":
        # 0.1.0 only ever expressed millimetres. Anything else would need a
        # unit conversion, and converting a dimension during a schema
        # migration is exactly the silent change this refuses to make.
        raise _failed(path, f"cannot migrate a parameter in {unit!r}; 1.1 expects millimetres")
    result: dict[str, Any] = {
        "id": _require(item, "id", path),
        "type": "length",
        "value": float(_require(item, "value", path)),
        "unit": "mm",
        "status": item.get("status", "confirmed"),
    }
    if item.get("name"):
        result["name"] = item["name"]
    provenance = _provenance(item.get("confidence"), item.get("source"))
    if provenance:
        result["provenance"] = provenance
    return result


def _provenance(confidence: Any, source: Any) -> dict[str, Any]:
    provenance: dict[str, Any] = {}
    if isinstance(confidence, (int, float)):
        provenance["confidence"] = float(confidence)
    if isinstance(source, dict) and source:
        if isinstance(source.get("page"), int) and isinstance(source.get("region"), list):
            provenance["source"] = {
                "page": source["page"],
                "region": [float(number) for number in source["region"]],
                **({"label": source["label"]} if isinstance(source.get("label"), str) else {}),
            }
        else:
            # Untyped 0.1.0 provenance. Kept as a note rather than discarded,
            # and rather than being forced into a shape it does not have.
            provenance["note"] = json.dumps(source, sort_keys=True, ensure_ascii=False)[:300]
    return provenance


def _features(items: list[Any]) -> list[dict[str, Any]]:
    """Translate features, then link each cut to the body it applies to.

    0.1.0 said which body a cut affected through `depends_on`; 1.1 says it with
    `source_body`. Deriving one from the other is a translation of something
    the document already stated, not an assumption about intent — so it is only
    done when the dependency is unambiguous: exactly one dependency, producing
    exactly one solid body.
    """
    features = [_feature(item, index) for index, item in enumerate(items)]
    bodies: dict[str, list[str]] = {
        feature["id"]: [
            result["id"] for result in feature["produces"] if result["kind"] == "solid_body"
        ]
        for feature in features
    }
    for feature in features:
        if feature["type"] != "cut.extrude" or "source_body" in feature["inputs"]:
            continue
        produced = [bodies.get(dependency, []) for dependency in feature["depends_on"]]
        candidates = [body for group in produced for body in group]
        if len(feature["depends_on"]) == 1 and len(candidates) == 1:
            feature["inputs"]["source_body"] = {"result": candidates[0]}
    return features


def _feature(item: dict[str, Any], index: int) -> dict[str, Any]:
    path = f"$.features[{index}]"
    legacy_type = _require(item, "type", path)
    if legacy_type not in _FEATURE_TYPES:
        raise _failed(path, f"CAD-IR {CAD_IR_VERSION} cannot express feature type {legacy_type!r}")
    inputs = _require(item, "inputs", path)
    result: dict[str, Any] = {
        "id": _require(item, "id", path),
        "type": _FEATURE_TYPES[legacy_type],
        "enabled": bool(item.get("enabled", True)),
        "depends_on": list(item.get("depends_on", [])),
        "produces": [_result(name, path) for name in item.get("semantic_outputs", [])],
        "inputs": _inputs(legacy_type, inputs, f"{path}.inputs"),
    }
    return result


def _result(name: Any, path: str) -> dict[str, str]:
    if not isinstance(name, str) or "." not in name:
        raise _failed(path, f"cannot infer the kind of result {name!r}")
    kind = _RESULT_KINDS.get(name.split(".", 1)[0])
    if kind is None:
        raise _failed(path, f"unknown result kind in {name!r}")
    return {"id": name, "kind": kind}


def _inputs(legacy_type: str, inputs: dict[str, Any], path: str) -> dict[str, Any]:
    translated: dict[str, Any] = {
        "sketch": _sketch(_require(inputs, "sketch", path), f"{path}.sketch"),
        "direction": _require(inputs, "direction", path),
    }
    if legacy_type == "extrude_add":
        translated["distance"] = _scalar(_require(inputs, "distance", path), f"{path}.distance")
    elif inputs.get("through_all") is True:
        translated["through_all"] = True
    elif "distance" in inputs:
        translated["distance"] = _scalar(inputs["distance"], f"{path}.distance")
    else:
        raise _failed(path, "a cut must declare either through_all or a distance")
    return translated


def _relabel(value: dict[str, Any]) -> dict[str, Any]:
    """Declare the canonical version without touching anything else."""
    return {**value, "schema_version": CAD_IR_VERSION}


def _lift_sketches(value: dict[str, Any]) -> dict[str, Any]:
    """Restate a 1.1 document's sketches in the 1.2 form.

    Everything else about 1.1 is already canonical, so this rewrites only the
    sketch: a plane name becomes a plane specification, and the entity list
    becomes an outer contour.
    """
    lifted = dict(value)
    features = _require(value, "features", "$")
    lifted["features"] = [
        _lift_feature_sketch(feature, index) for index, feature in enumerate(features)
    ]
    return lifted


def _lift_feature_sketch(feature: Any, index: int) -> dict[str, Any]:
    path = f"$.features[{index}]"
    if not isinstance(feature, dict):
        raise _failed(path, "a feature must be an object")
    inputs = feature.get("inputs")
    if not isinstance(inputs, dict) or "sketch" not in inputs:
        return feature
    return {
        **feature,
        "inputs": {**inputs, "sketch": _sketch(inputs["sketch"], f"{path}.inputs.sketch")},
    }


def _sketch(sketch: Any, path: str) -> dict[str, Any]:
    """Turn a 1.1 or 0.1.0 sketch into a 1.2 one.

    Both older versions express exactly one shape per sketch, so the single
    entity becomes the outer contour. A sketch carrying several would need this
    to decide which one is the profile and which are islands, and inferring
    that from nothing but a list order is precisely the guess normalisation
    does not make.
    """
    entities = _require(sketch, "entities", path)
    if not isinstance(entities, list) or len(entities) != 1:
        raise _failed(
            f"{path}.entities",
            f"CAD-IR {CAD_IR_VERSION} sketches state one outer contour and its islands; a sketch "
            f"of {len(entities) if isinstance(entities, list) else '?'} entities does not say which "
            "is which",
        )
    declared_contours = int(sketch.get("expected_closed_contours", 1))
    if declared_contours != 1:
        raise _failed(
            f"{path}.expected_closed_contours",
            f"the sketch declares {declared_contours} closed contours but carries one entity",
        )
    return {
        "id": _require(sketch, "id", path),
        "plane": {"on": "base", "plane": _require(sketch, "plane", path)},
        "outer": _contour(entities[0], f"{path}.entities[0]"),
    }


def _contour(entity: dict[str, Any], path: str) -> dict[str, Any]:
    """One older sketch entity as a 1.2 contour.

    The entity's `id` has no slot in 1.2 and is dropped. A contour is not
    referenced by anything — 1.2 has no constraints — so the id was a label
    rather than a statement about the part.
    """
    entity_type = _require(entity, "type", path)
    center = [
        _scalar(value, f"{path}.center[{index}]")
        for index, value in enumerate(_require(entity, "center", path))
    ]
    if entity_type == "center_rectangle":
        return {
            "type": "rectangle",
            "center": center,
            "width": _scalar(_require(entity, "width", path), f"{path}.width"),
            "height": _scalar(_require(entity, "height", path), f"{path}.height"),
        }
    if entity_type == "circle":
        return {
            "type": "circle",
            "center": center,
            "radius": _scalar(_require(entity, "radius", path), f"{path}.radius"),
        }
    raise _failed(path, f"CAD-IR {CAD_IR_VERSION} cannot express sketch entity {entity_type!r}")


def _scalar(value: Any, path: str) -> Any:
    """Translate a 0.1.0 scalar into a number or a parameter reference.

    1.1 has no expression language, so an expression survives only when it is
    a bare parameter name — which is what every expression in practice was.
    Evaluating anything richer would fold a formula into a literal and lose
    the parametric intent the document existed to record.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict) and set(value) == {"param"} and isinstance(value["param"], str):
        return {"parameter": value["param"]}
    if isinstance(value, dict) and set(value) == {"expr"} and isinstance(value["expr"], str):
        expression = value["expr"].strip()
        if expression.replace("_", "").replace(".", "").replace("-", "").isalnum() and not (
            expression[:1].isdigit()
        ):
            return {"parameter": expression}
        raise _failed(
            path,
            f"CAD-IR {CAD_IR_VERSION} has no expression language; {expression!r} is not a bare "
            "parameter reference",
        )
    raise _failed(path, "a scalar must be a number, a parameter reference or a bare expression")


def _expectation(item: dict[str, Any], index: int) -> dict[str, Any]:
    path = f"$.expected_invariants[{index}]"
    legacy_type = _require(item, "type", path)
    if legacy_type not in _EXPECTATION_TYPES:
        raise _failed(path, f"CAD-IR {CAD_IR_VERSION} cannot express invariant {legacy_type!r}")
    severity = item.get("severity", "error")
    if severity != "error":
        # A 0.1.0 warning-severity invariant is advisory. 1.1 expectations are
        # all binding, so promoting one would change what a build is allowed
        # to produce.
        raise _failed(path, f"cannot migrate a {severity!r} invariant; 1.1 expectations are binding")

    expected = _require(item, "expected", path)
    identifier = _require(item, "id", path)
    if legacy_type == "bounding_box":
        if not isinstance(expected, list) or len(expected) != 3:
            raise _failed(path, "a bounding box invariant must carry three dimensions")
        return {
            "id": identifier,
            "type": "bounding_box",
            "size_mm": {
                "x": float(expected[0]),
                "y": float(expected[1]),
                "z": float(expected[2]),
            },
            "tolerance_mm": float(item.get("tolerance") or 0.0),
        }
    return {"id": identifier, "type": _EXPECTATION_TYPES[legacy_type], "value": int(expected)}


def _require(owner: Any, key: str, path: str) -> Any:
    if not isinstance(owner, dict) or key not in owner:
        raise _failed(path, f"{path}.{key} is required to migrate")
    return owner[key]


def _require_empty(value: dict[str, Any], key: str) -> None:
    if value.get(key):
        raise _failed(
            f"$.{key}",
            f"CAD-IR {CAD_IR_VERSION} has no slot for {key}; migrating would drop a recorded "
            "statement about the part",
        )


def _failed(path: str, message: str) -> CadIrValidationError:
    return CadIrValidationError([ValidationIssue("CAD_IR_MIGRATION_FAILED", path, message)])
