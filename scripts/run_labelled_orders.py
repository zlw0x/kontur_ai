"""Put the labelled drawings through the real service and score what comes back.

    python scripts/run_labelled_orders.py .local/labelled .local/labelled/results.jsonl

Everything before this milestone was about the service not breaking. This is about
whether it *works*, and there is no other way to find out.

**Three numbers, counted separately**, because they answer different questions and
collapsing them would hide the interesting one:

1. *delivered* — the order produced a STEP and an STL at all.
2. *correct* — the part measures what the drawing says, checked against numbers this
   harness computed from the drawing before the model saw it.
3. *caught* — where the part was **not** correct, something in the service said so
   rather than delivering it quietly.

The third is the one worth the run. A service that is right 80% of the time and
silent about the other 20% is worse than one that is right 60% of the time and says
which 40% to look at, because only the second can be used.

**Resumable**, and that is not a convenience: a hundred orders is hours of real model
calls, and a run that has to start over after an interruption is a run nobody
finishes. Results are appended a line at a time and a case already in the file is
skipped.

It authenticates with `MANUAL_API_TOKEN`, which is the diagnostic operator key and is
exactly what this is. That also means the orders it creates have no owner and are not
subject to the customer quotas — measuring the reading stage is not the load those
protect against.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "http://localhost:8000"
TOKEN = "local-development-manual-api-token-change-me"

#: How long one order may take before the harness stops waiting for it.
#:
#: Generous: a reading, a compilation, up to three compile repairs and a container
#: start. What it is protecting against is a run that stops making progress, not a
#: slow drawing.
ORDER_TIMEOUT_SECONDS = 900
POLL_SECONDS = 10

#: A settled order, in the vocabulary `order_status` answers in.
#:
#: `MANUAL_REVIEW` is a settlement here because `automatic_acceptance` ships off: a
#: finished build waits for a person, and for this measurement "a person has not
#: looked at it yet" is not a different outcome from "delivered".
SETTLED = {"READY", "MANUAL_REVIEW", "FAILED", "CANCELLED", "EXPIRED"}

#: How much the measured geometry may differ from the closed form.
#:
#: A millionth of a millimetre on a size, and a thousandth of a cubic millimetre on a
#: volume. Both are far inside what the kernel produces and far outside floating-point
#: noise, so a failure here is a real disagreement rather than a rounding argument.
SIZE_TOLERANCE = 1e-6
VOLUME_TOLERANCE = 1e-3


def call(path: str, *, method: str = "GET", body: bytes | None = None,
         content_type: str | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(f"{API}{path}", data=body, method=method)
    request.add_header("x-manual-api-token", TOKEN)
    if content_type:
        request.add_header("content-type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as failure:
        raw = failure.read()
        try:
            return failure.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return failure.code, {"detail": raw.decode("utf-8", "replace")[:300]}


# --- answering what the reading asks ----------------------------------------------
#
# A question names a parameter the *model* chose, so the harness cannot look it up by
# id. It matches on meaning instead, and counts the ones it cannot match — that number
# is a measurement in its own right: a question this cannot answer from the drawing's
# own dimensions is a question a customer would have to guess at too.

#: Ordered, because the first match wins and the more specific patterns come first.
#: `pocket_depth` before `thickness` matters: "depth of the pocket" contains neither
#: word the other way round, but "plate depth" would otherwise take the pocket's.
ANSWER_PATTERNS: list[tuple[str, str]] = [
    (r"pocket.*depth|depth.*pocket|blind.*depth|глуб", "pocket_depth"),
    (r"pocket.*(diam|dia\b)|(diam|dia\b).*pocket", "pocket_diameter"),
    (r"pocket.*rad|rad.*pocket", "pocket_radius"),
    (r"(bore|central).*(diam|dia\b)|(diam|dia\b).*(bore|central)", "bore_diameter"),
    (r"(bore|central).*rad", "bore_radius"),
    (r"(pitch|bolt).*circle.*(diam|dia\b)|pcd", "pitch_circle_diameter"),
    (r"(pitch|bolt).*circle.*rad", "pitch_circle_radius"),
    (r"(pitch|spacing|between).*(hole|centre|center)|hole.*(pitch|spacing)", "hole_pitch"),
    (r"outer.*(diam|dia\b)|overall.*(diam|dia\b)|(diam|dia\b).*(flange|disc|plate)", "outer_diameter"),
    (r"outer.*rad", "outer_radius"),
    (r"(pad|boss).*(height|thick)|(height|thick).*(pad|boss)", "pad_height"),
    (r"(pad|boss).*(length|width|size)", "pad_length"),
    (r"total.*(height|thick)|overall.*(height|thick)", "total_height"),
    (r"hole.*(diam|dia\b)|(diam|dia\b).*hole", "hole_diameter"),
    (r"hole.*rad|rad.*hole", "hole_radius"),
    (r"(left|first).*(hole|centre|center)|(hole|centre|center).*(from|to).*left", "hole_from_left"),
    (r"(bottom|lower).*(hole|centre|center)|(hole|centre|center).*(from|to).*bottom",
     "hole_from_bottom"),
    (r"thick|плит|s\b", "thickness"),
    (r"\bheight\b|\bвысот", "width"),
    (r"\blength\b|\bдлин", "length"),
    (r"\bwidth\b|\bширин", "width"),
]


def answer_for(question: dict, stated: dict[str, float]) -> float | str | None:
    """The value this drawing states for what the question is asking about.

    Returns `None` when nothing matches, which is counted rather than guessed at.
    Guessing would make the run measure the harness rather than the service.
    """
    if question.get("answer_kind") == "choice":
        choices = question.get("choices") or []
        # The families here are drawn so the answer is on the sheet: a pocket says
        # "не сквозн." and a plate says "сквозн.". Prefer the choice matching the
        # family's truth, and otherwise take the first rather than inventing one.
        wanted = "no" if stated.get("pocket_depth") else "yes"
        for choice in choices:
            lowered = str(choice).lower()
            if wanted == "no" and ("не" in lowered or "no" in lowered or "false" in lowered):
                return choice
            if wanted == "yes" and ("да" in lowered or "yes" in lowered or "true" in lowered):
                return choice
        return choices[0] if choices else None

    haystack = f"{question.get('parameter_id', '')} {question.get('text', '')}".lower()
    for pattern, key in ANSWER_PATTERNS:
        if re.search(pattern, haystack) and key in stated:
            return float(stated[key])
    return None


# --- scoring ------------------------------------------------------------------------


VOLUME = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*mm3")


def measured(report: dict) -> dict[str, Any]:
    """What the delivered files actually are, out of the worker's own report.

    The bounding box, the genus and the solid count are machine-readable; the volume
    is only in a check's prose, so it is parsed. Everything here was measured by
    reopening the exported files, not taken from the document.
    """
    geometry = report.get("geometry", {})
    mesh = geometry.get("mesh", {})
    topology = geometry.get("topology", {})
    volume = None
    for check in geometry.get("checks", []):
        if check.get("name") == "positive_volume":
            found = VOLUME.search(check.get("detail", ""))
            volume = float(found.group(1)) if found else None
    return {
        "bounding_box": mesh.get("bounding_box"),
        "volume_mm3": volume,
        "genus": mesh.get("genus"),
        "solid_count": topology.get("solid_count"),
    }


def disagreements(label: dict, found: dict) -> list[str]:
    """Where the delivered part and the drawing differ, named one by one."""
    problems = []
    box = found.get("bounding_box")
    if box is None:
        problems.append("no bounding box was measured")
    else:
        # Sorted, because which axis is which is the document's choice and the drawing
        # does not care: a 60 x 30 plate lying the other way round is the same part.
        if any(abs(a - b) > SIZE_TOLERANCE
               for a, b in zip(sorted(box), sorted(label["bounding_box"]))):
            problems.append(f"bounding box {box} against {label['bounding_box']}")
    if found.get("volume_mm3") is None:
        problems.append("no volume was measured")
    elif abs(found["volume_mm3"] - label["volume_mm3"]) > VOLUME_TOLERANCE:
        problems.append(f"volume {found['volume_mm3']} against {label['volume_mm3']}")
    if found.get("genus") != label["through_holes"]:
        problems.append(f"genus {found.get('genus')} against {label['through_holes']} through holes")
    if found.get("solid_count") != label["solids"]:
        problems.append(f"{found.get('solid_count')} solids against {label['solids']}")
    return problems


# --- one order ------------------------------------------------------------------------


def run_case(case: dict, drawings: Path) -> dict[str, Any]:
    started = time.time()
    record: dict[str, Any] = {
        "id": case["id"], "family": case["family"], "rounds": 0,
        "questions_asked": 0, "questions_unanswerable": 0,
    }
    page = (drawings / f"{case['id']}.png").read_bytes()
    status, created = call("/api/v1/drawing-jobs", method="POST", body=page,
                           content_type="image/png")
    if status != 201:
        return {**record, "outcome": "REFUSED_AT_UPLOAD", "detail": str(created)[:200]}
    order_id = created["order_id"]
    record["order_id"] = order_id

    while time.time() - started < ORDER_TIMEOUT_SECONDS:
        _, state = call(f"/api/v1/drawing-jobs/{order_id}")
        status_name = state["status"]
        if status_name == "WAITING_FOR_USER_ANSWERS":
            questions = state.get("questions", [])
            record["questions_asked"] += len(questions)
            answers = []
            for question in questions:
                value = answer_for(question, case["stated"])
                if value is None:
                    record["questions_unanswerable"] += 1
                    record["unanswered"] = question.get("text", "")[:160]
                    break
                answers.append(
                    {"question_id": question["id"], "value": value}
                    if isinstance(value, str)
                    else {"question_id": question["id"], "value": value, "unit": "mm"}
                )
            if len(answers) != len(questions):
                return {**record, "outcome": "UNANSWERABLE_QUESTION",
                        "seconds": round(time.time() - started, 1)}
            code, replied = call(
                f"/api/v1/drawing-jobs/{order_id}/answers", method="POST",
                body=json.dumps({"answers": answers}).encode(),
                content_type="application/json",
            )
            if code != 201:
                return {**record, "outcome": "ANSWERS_REFUSED", "detail": str(replied)[:200],
                        "seconds": round(time.time() - started, 1)}
            record["rounds"] += 1
            time.sleep(POLL_SECONDS)
            continue
        if status_name in SETTLED:
            record["seconds"] = round(time.time() - started, 1)
            record["status"] = status_name
            record["failure_code"] = state.get("failure_code")
            record["failure_message"] = (state.get("failure_message") or "")[:200]
            kinds = {item["type"].upper() for item in state.get("artifacts", [])}
            if not {"STEP", "STL"}.issubset(kinds):
                # Nothing was delivered. Whether the service *said* so is the third
                # number: a typed failure code is the service catching itself.
                return {**record, "outcome": "NOT_DELIVERED",
                        "announced": bool(state.get("failure_code"))}
            job_id = state["job_id"]
            _, report = call(f"/api/v1/manual/cad-jobs/{job_id}/artifacts/VALIDATION_REPORT")
            found = measured(report or {})
            problems = disagreements(case, found)
            return {
                **record, "outcome": "CORRECT" if not problems else "WRONG",
                "measured": found, "problems": problems,
                # A part that is wrong *and* was reported valid is the case that
                # matters: the service delivered it without saying anything.
                "announced": bool(state.get("failure_code")) or not (report or {}).get("valid", True),
            }
        time.sleep(POLL_SECONDS)
    return {**record, "outcome": "TIMED_OUT", "seconds": round(time.time() - started, 1)}


def main(argv: list[str]) -> int:
    drawings = Path(argv[1] if len(argv) > 1 else ".local/labelled")
    results = Path(argv[2] if len(argv) > 2 else drawings / "results.jsonl")
    limit = int(argv[3]) if len(argv) > 3 else 10_000
    cases = json.loads((drawings / "labels.json").read_text(encoding="utf-8"))["cases"]

    done = set()
    if results.exists():
        for line in results.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    results.parent.mkdir(parents=True, exist_ok=True)

    ran = 0
    for case in cases:
        if case["id"] in done:
            continue
        if ran >= limit:
            break
        record = run_case(case, drawings)
        with results.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        ran += 1
        print(
            f"{record['id']:14} {record['outcome']:22} "
            f"{record.get('seconds', 0):7}s  rounds={record['rounds']}"
            + (f"  {record['problems'][0]}" if record.get("problems") else ""),
            flush=True,
        )
    print(f"\n{ran} run, {len(done)} already in {results}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main(sys.argv))
