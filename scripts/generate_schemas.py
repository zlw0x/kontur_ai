"""Regenerate the checked-in JSON Schemas from the contract models.

Hand-maintained copies of these documents drift from the DTOs that actually
gate the boundary, so they are generated instead.  `--check` fails when the
checked-in files no longer match the models, which is what CI runs.
"""

import json
import sys
from pathlib import Path


root = Path(__file__).parents[1]
sys.path.insert(0, str(root / "apps" / "api"))

from app.contracts import (  # noqa: E402
    JobCostSnapshot,
    PricingProfile,
    ResourceEventBatch,
    WorkerCapabilityManifest,
)


BASE_ID = "https://cad.example.com/schemas"
DOCUMENTS = {
    "resource-event-batch": (ResourceEventBatch, "1.0", "Resource ledger ingestion batch"),
    "pricing-profile": (PricingProfile, "1.0", "Versioned pricing profile"),
    "job-cost-snapshot": (JobCostSnapshot, "1.0", "Immutable job cost snapshot"),
    "worker-capability-manifest": (WorkerCapabilityManifest, "1.0", "Worker capability manifest"),
}


def render(model, version: str, title: str, name: str) -> str:
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/{name}/{version}",
        "title": title,
        **model.model_json_schema(),
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for name, (model, version, title) in DOCUMENTS.items():
        target = root / "schemas" / f"{name}.schema.json"
        content = render(model, version, title, name)
        if check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != content:
                stale.append(target.relative_to(root).as_posix())
            continue
        target.write_text(content, encoding="utf-8")
        print(f"generated: {target.relative_to(root).as_posix()}")
    if stale:
        print("stale generated schemas: " + ", ".join(stale), file=sys.stderr)
        print("run: python scripts/generate_schemas.py", file=sys.stderr)
        return 1
    if check:
        print("valid: generated JSON Schemas match the contract models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
