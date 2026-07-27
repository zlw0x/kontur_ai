import json
from pathlib import Path
from jsonschema import Draft202012Validator

root = Path(__file__).parents[1]
for path in sorted((root / "schemas").glob("*.schema.json")):
    document = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    print(f"valid: {path.relative_to(root)}")

openapi_path = root / "schemas" / "openapi.v1.json"
openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
assert openapi["openapi"].startswith("3.1."), "OpenAPI must use version 3.1"
assert openapi["info"]["version"].split(".")[0] == "1", "OpenAPI major must match /api/v1"
print(f"valid: {openapi_path.relative_to(root)}")
