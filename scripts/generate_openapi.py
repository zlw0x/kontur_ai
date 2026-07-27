"""Regenerate the checked-in OpenAPI v1 document from FastAPI routes."""

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
target.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
    newline="",
)
print(f"generated: {target.relative_to(root)}")
