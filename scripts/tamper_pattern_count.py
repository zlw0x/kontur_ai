"""Drill the same six holes twice, and see whether anything notices.

ADR-027 uses this as its illustration of why a shape claim exists, and the
illustration has never been run. Take a document that patterns one hole six times
at 60 degrees and change the count to twelve. Instances 6 through 11 land exactly
on top of instances 0 through 5. The part that comes out is **identical** — same
volume, same bounding box, same face count, same genus, same bytes. Every
measurement in the validation report passes, because every measurement is taken
on a part that is correct.

The only thing that disagrees is the claim, which said six openings while the
document now says twelve. A count is the one kind of error that measuring the
result cannot find, because the result is not wrong.

    python scripts/tamper_pattern_count.py .local/sc4/output/cad-ir.json out.json

Nothing here is part of the service. It is a way to produce a specific wrong
document on purpose, so that the check meant to catch it can be observed catching
it rather than assumed to.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def double_the_count(document: dict) -> tuple[dict, str]:
    """Find the one pattern in the document and double its instance count.

    Returns the changed document and a line describing what changed, so the
    caller reports the actual edit rather than the intended one — a tamper script
    that silently did nothing would make the run look like a pass.
    """
    for feature in document.get("features", []):
        if not str(feature.get("type", "")).startswith("pattern."):
            continue
        inputs = feature.get("inputs", {})
        for key in ("count", "instances", "instance_count", "total_count"):
            if isinstance(inputs.get(key), int):
                before = inputs[key]
                inputs[key] = before * 2
                return document, (
                    f"{feature.get('id')} ({feature.get('type')}): "
                    f"{key} {before} -> {inputs[key]}"
                )
    raise SystemExit(
        "no pattern feature with an integer count in this document — "
        "nothing to double, and a silent success here would be a false pass"
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    document = json.loads(source.read_text(encoding="utf-8"))
    document, change = double_the_count(document)
    target.write_text(json.dumps(document, indent=1), encoding="utf-8")
    print(f"wrote {target}")
    print(f"  {change}")
    print("  the part this builds is identical to the correct one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
