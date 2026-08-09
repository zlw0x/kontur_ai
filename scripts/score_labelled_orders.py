"""Score a labelled corpus run from what was measured, under one rule.

    python scripts/score_labelled_orders.py .local/labelled

Separate from the runner on purpose. Every record carries the geometry that was
*measured* by reopening the delivered files, so the verdict can be recomputed
without asking the model anything again — and it had to be, because the first rule
this harness used was wrong.

It compared the label's `solids` — what a reader counts on a drawing — against
`topology.solid_count`, which is `body_count`, what the delivered file contains.
This repository keeps those as different questions on purpose (ADR-028: the bracket
fixture declares two bodies and satisfies a claim of three solids). Four pad cases
came back with the bounding box and the volume exact to the last digit and were
scored WRONG for having their boss fused into the plate, which is the same part.

Rescoring from the records rather than re-running is the whole reason the runner
writes `measured` instead of only a verdict.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_labelled_orders import disagreements  # noqa: E402


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".local/labelled")
    labels = {
        case["id"]: case
        for case in json.loads((root / "labels.json").read_text(encoding="utf-8"))["cases"]
    }
    rows = [
        json.loads(line)
        for line in (root / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    families: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    silent: list[str] = []
    fused: list[str] = []
    for row in rows:
        family = families[row["family"]]
        family["n"] += 1
        if row["outcome"] in ("NOT_DELIVERED", "UNANSWERABLE_QUESTION", "TIMED_OUT",
                              "ANSWERS_REFUSED", "REFUSED_AT_UPLOAD"):
            family["not delivered"] += 1
            if not row.get("announced"):
                silent.append(f"{row['id']} was not delivered and nothing said why")
            continue
        problems = disagreements(labels[row["id"]], row.get("measured", {}))
        family["delivered"] += 1
        if problems:
            family["wrong"] += 1
            if not row.get("announced"):
                silent.append(f"{row['id']}: {'; '.join(problems)}")
        else:
            family["correct"] += 1
        if row.get("measured", {}).get("solid_count") != labels[row["id"]]["solids"]:
            fused.append(row["id"])

    total = collections.Counter()
    print(f"{'family':10} {'n':>4} {'delivered':>10} {'correct':>8} {'wrong':>6}")
    for name in sorted(families):
        counts = families[name]
        total.update(counts)
        print(f"{name:10} {counts['n']:4} {counts['delivered']:10} "
              f"{counts['correct']:8} {counts['wrong']:6}")
    print(f"{'TOTAL':10} {total['n']:4} {total['delivered']:10} "
          f"{total['correct']:8} {total['wrong']:6}")

    asked = sum(row.get("questions_asked", 0) for row in rows)
    unanswerable = sum(row.get("questions_unanswerable", 0) for row in rows)
    print(f"\nquestions asked: {asked}, unanswerable from the sheet: {unanswerable}")
    print(f"bodies fused where the reader counts two: {len(fused)}")
    print(f"\nwrong or undelivered AND silent: {len(silent)}")
    for line in silent:
        print("  ", line)
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main(sys.argv))
