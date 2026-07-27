"""Reject accidental breaking changes to the published v1 contract."""

import json
from pathlib import Path


root = Path(__file__).parents[1]
document = json.loads((root / "schemas" / "openapi.v1.json").read_text(encoding="utf-8"))
baseline = json.loads((root / "schemas" / "openapi.v1.compatibility.json").read_text(encoding="utf-8"))

assert document["info"]["version"].split(".")[0] == baseline["supported_api_major"]
for path, methods in baseline["required_paths"].items():
    assert path in document["paths"], f"removed v1 path: {path}"
    for method in methods:
        assert method in document["paths"][path], f"removed v1 operation: {method.upper()} {path}"

schemas = document["components"]["schemas"]
for name, required_properties in baseline["required_schema_properties"].items():
    assert name in schemas, f"removed v1 schema: {name}"
    properties = schemas[name]["properties"]
    required = set(schemas[name]["required"])
    for property_name in required_properties:
        assert property_name in properties and property_name in required, f"removed required v1 field: {name}.{property_name}"

print("valid: OpenAPI v1 compatibility")
