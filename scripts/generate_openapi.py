"""Regenerate the checked-in OpenAPI v1 document from FastAPI routes.

`--check` fails when the checked-in file no longer matches the routes, which is
what CI runs — the same arrangement `generate_schemas.py` has had all along.

It was missing, and the file had been stale since migration 0007: `retry_after`
was added to `JobFailureRequest` and `JobFailureAck`, and nothing regenerated the
published document or noticed. `validate_schemas.py` only checks that the file is a
well-formed OpenAPI document, and `check_openapi_compatibility.py` only checks that
nothing v1 promised has *disappeared* from it — neither can see a field that never
arrived. A contract file that silently drifts from the service is worse than no
file, because it is the one an integrator reads.
"""

import json
import os
import sys
from pathlib import Path


root = Path(__file__).parents[1]
sys.path.insert(0, str(root / "apps" / "api"))
sys.path.insert(0, str(root / "packages" / "cad-ir"))
os.environ["WORKER_REPOSITORY_MODE"] = "memory"

from app.main import app  # noqa: E402


target = root / "schemas" / "openapi.v1.json"
rendered = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"

if "--check" in sys.argv:
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    if current != rendered:
        print(
            f"stale: {target.relative_to(root)} does not match the routes.\n"
            "Run `python scripts/generate_openapi.py` and commit the result.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"valid: {target.relative_to(root)} matches the routes")
    raise SystemExit(0)

target.write_text(rendered, encoding="utf-8", newline="")
print(f"generated: {target.relative_to(root)}")
