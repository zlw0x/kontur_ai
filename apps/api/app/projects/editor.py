"""Bounded edit commands. Documents are data; nothing here runs generated code."""

from __future__ import annotations

import re
from copy import deepcopy
from uuid import uuid4

from cad_ir.canonical import CAD_IR_VERSION
from cad_ir.canonical_validator import validate_canonical


class EditRefused(ValueError):
    pass


ALIASES = {
    "p_width": ("ширина", "ширину", "ширины"),
    "p_height": ("длина", "длину", "длины", "высота", "высоту", "высоты"),
    "p_depth": ("глубина", "глубину", "глубины"),
    "p_wall": ("стенка", "стенку", "стенки", "толщина стенки", "толщину стенки"),
}


def enclosure(width: float, height: float, depth: float, wall: float) -> dict:
    if wall * 2 >= min(width, height) or wall >= depth:
        raise EditRefused(
            "Стенка должна быть тоньше половины ширины и длины и меньше глубины."
        )
    sketch = {
        "id": "sketch.body",
        "plane": {"on": "base", "plane": "XY"},
        "outer": {
            "type": "rectangle",
            "center": [0, 0],
            "rotation_deg": 0,
            "width": {"parameter": "p_width"},
            "height": {"parameter": "p_height"},
        },
        "inner": [],
        "construction": [],
        "constraints": [],
        "dimensions": [],
    }
    value = {
        "schema": "cad-ai/cad-ir",
        "schema_version": CAD_IR_VERSION,
        "document": {
            "name": "enclosure",
            "units": "mm",
            "part_type": "single_part",
            "coordinate_system": "right_handed",
        },
        "parameters": [
            {
                "id": key,
                "name": name,
                "type": "length",
                "unit": "mm",
                "value": number,
                "status": "user_confirmed",
            }
            for key, name, number in (
                ("p_width", "Ширина", width),
                ("p_height", "Длина", height),
                ("p_depth", "Глубина", depth),
                ("p_wall", "Стенка", wall),
            )
        ],
        "reference_geometry": [],
        "features": [
            {
                "id": "feature.body",
                "type": "solid.extrude",
                "enabled": True,
                "depends_on": [],
                "produces": [{"id": "body.main", "kind": "solid_body"}],
                "inputs": {
                    "sketch": sketch,
                    "direction": "+Z",
                    "distance": {"parameter": "p_depth"},
                },
            },
            {
                "id": "feature.hollow",
                "type": "feature.shell",
                "enabled": True,
                "depends_on": ["feature.body"],
                "produces": [],
                "inputs": {
                    "direction": "inward",
                    "thickness": {"parameter": "p_wall"},
                    "faces": {
                        "id": "selector.open_top",
                        "kind": "face",
                        "from_result": "body.main",
                        "cardinality": "exactly_one",
                        "where": {
                            "surface_type": "planar",
                            "normal": {
                                "parallel_to": "axis.z",
                                "direction": "positive",
                            },
                        },
                    },
                },
            },
        ],
        "expectations": [
            {
                "id": "inv_bbox",
                "type": "bounding_box",
                "size_mm": {"x": width, "y": height, "z": depth},
                "tolerance_mm": 0.05,
            },
            {"id": "inv_bodies", "type": "body_count", "value": 1},
            {"id": "inv_holes", "type": "through_hole_count", "value": 0},
        ],
        "metadata": {"generator": "kontur-editor", "generator_version": "1.0"},
    }
    return validate_canonical(value).canonical_dict()


def _box_bindings(value: dict) -> dict[str, str]:
    """Only explicit dimensions of a base XY extrusion; never match by value.

    Subsequent cuts, shells and blends can shrink a box but cannot enlarge it.
    An expectation differing from the stated starting size is deliberately left
    alone: its independent measurement will refuse an unsafe edit.
    """
    first = value["features"][0]
    inputs = first["inputs"]
    sketch = inputs.get("sketch", {})
    if (
        first["type"] != "solid.extrude"
        or not first.get("enabled", True)
        or sketch.get("plane") != {"on": "base", "plane": "XY"}
        or inputs.get("direction") != "+Z"
        or inputs.get("both_directions", False)
        or inputs.get("taper_deg") not in (None, 0)
    ):
        return {}
    outer = sketch.get("outer", {})
    if outer.get("type") != "rectangle" or outer.get("rotation_deg", 0) != 0:
        return {}
    bindings = {}
    for axis, scalar in (
        ("x", outer.get("width")),
        ("y", outer.get("height")),
        ("z", inputs.get("distance")),
    ):
        if isinstance(scalar, dict) and set(scalar) == {"parameter"}:
            bindings[axis] = scalar["parameter"]
    return bindings


def edit_parameters(document: dict, changes: dict[str, float]) -> dict:
    value = deepcopy(document)
    parameters = {p["id"]: p for p in value["parameters"]}
    if not changes or any(key not in parameters for key in changes):
        raise EditRefused("Укажите существующий параметр модели.")
    bindings = _box_bindings(value)
    for expectation in value["expectations"]:
        if expectation["type"] == "bounding_box":
            for axis, key in bindings.items():
                if (
                    key in changes
                    and expectation["size_mm"][axis] == parameters[key]["value"]
                ):
                    expectation["size_mm"][axis] = changes[key]
    for key, number in changes.items():
        parameter = parameters[key]
        if parameter["type"] == "length" and not 0 < number <= 2000:
            raise EditRefused("Размер должен быть больше 0 и не больше 2000 мм.")
        parameter.update(value=number, status="user_confirmed")
    return validate_canonical(value).canonical_dict()


def add_hole(document: dict, diameter: float, x: float, y: float) -> dict:
    value = deepcopy(document)
    if not _box_bindings(value):
        raise EditRefused(
            "Пока отверстие можно добавить к корпусу или пластине в плоскости XY."
        )
    bodies = [
        r
        for f in value["features"]
        for r in f.get("produces", [])
        if r["kind"] == "solid_body"
    ]
    if len(bodies) != 1:
        raise EditRefused("Для отверстия нужна модель с одним исходным телом.")
    bounds = next(
        (e["size_mm"] for e in value["expectations"] if e["type"] == "bounding_box"),
        None,
    )
    center = value["features"][0]["inputs"]["sketch"]["outer"]["center"]
    if not all(isinstance(coordinate, (int, float)) for coordinate in center):
        raise EditRefused(
            "Для добавления отверстия нужны явные координаты центра исходного контура."
        )
    if bounds is not None and (
        abs(x - center[0]) + diameter / 2 >= bounds["x"] / 2
        or abs(y - center[1]) + diameter / 2 >= bounds["y"] / 2
    ):
        raise EditRefused("Отверстие должно целиком находиться внутри контура детали.")
    suffix = uuid4().hex[:12]
    parameter_id = f"hole_diameter_{suffix}"
    value["parameters"].append(
        {
            "id": parameter_id,
            "name": "Диаметр отверстия",
            "type": "length",
            "unit": "mm",
            "value": diameter,
            "status": "user_confirmed",
        }
    )
    value["features"].append(
        {
            "id": f"feature.hole_{suffix}",
            "type": "cut.extrude",
            "enabled": True,
            "depends_on": [
                f["id"] for f in value["features"] if f.get("enabled", True)
            ],
            "produces": [],
            "inputs": {
                "source_body": {"result": bodies[0]["id"]},
                "direction": "+Z",
                "through_all": True,
                "sketch": {
                    "id": f"sketch.hole_{suffix}",
                    "plane": {"on": "base", "plane": "XY"},
                    "outer": {
                        "type": "circle",
                        "center": [x, y],
                        "radius": {"divide": {"parameter": parameter_id}, "by": 2},
                    },
                    "inner": [],
                    "construction": [],
                    "constraints": [],
                    "dimensions": [],
                },
            },
        }
    )
    hole_counts = [
        e for e in value["expectations"] if e["type"] == "through_hole_count"
    ]
    if not hole_counts:
        raise EditRefused("В исходном проекте не задано контрольное число отверстий.")
    for expectation in hole_counts:
        expectation["value"] += 1
    return validate_canonical(value).canonical_dict()


NUMBER = r"([-+]?\d+(?:[.,]\d+)?)"


def edit_text(document: dict, text: str) -> dict:
    command = text.strip().lower().replace("ё", "е")
    hole = re.fullmatch(
        r"добавь отверстие (?:диаметром |диаметр )?"
        + NUMBER
        + r"(?:\s*мм)?\s+x\s*=?\s*"
        + NUMBER
        + r"\s+y\s*=?\s*"
        + NUMBER,
        command,
    )
    if hole:
        diameter, x, y = (float(s.replace(",", ".")) for s in hole.groups())
        if not 0 < diameter <= 2000 or max(abs(x), abs(y)) > 2000:
            raise EditRefused(
                "Диаметр и координаты должны быть в пределах 2000 мм; диаметр больше нуля."
            )
        return add_hole(document, diameter, x, y)
    match = re.fullmatch(
        r"(?:(установи|измени|увеличь|уменьши)\s+)?(.+?)(?:\s+(?:на|до)|\s*=)?\s+"
        + NUMBER
        + r"(?:\s*мм)?",
        command,
    )
    if not match:
        raise EditRefused(
            "Например: «ширина 140», «увеличь ширину на 10» или «добавь отверстие диаметром 6 x 0 y 0»."
        )
    verb, name, raw = match.groups()
    name = name.strip()
    candidates = [
        p
        for p in document["parameters"]
        if name
        in (p["id"].lower(), (p.get("name") or "").lower(), *ALIASES.get(p["id"], ()))
    ]
    if len(candidates) != 1:
        raise EditRefused(
            "Название размера неоднозначно или неизвестно. Используйте имя параметра из списка."
        )
    parameter = candidates[0]
    number = float(raw.replace(",", "."))
    if verb in ("увеличь", "уменьши"):
        if number <= 0 or " на " not in command:
            raise EditRefused(
                "Укажите положительное изменение: «увеличь ширину на 10»."
            )
        number = parameter["value"] + number * (1 if verb == "увеличь" else -1)
    return edit_parameters(document, {parameter["id"]: number})
