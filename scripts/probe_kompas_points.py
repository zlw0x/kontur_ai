"""Identify which endpoint `Index` and `PartnerIndex` select on a KOMPAS constraint.

POSTMVP-007 left six constraint kinds verified but not applied — coincident,
midpoint, point-on-curve, aligned horizontally, aligned vertically and collinear
— for one reason: `IParametriticConstraint` carries `Index` and `PartnerIndex`,
and nothing on this machine says what their values mean. Applying one with the
defaults would pin whichever pair of points KOMPAS chose, and for the corner of
a contour that is very likely the wrong pair. A constraint the document did not
state, sitting in a file a customer opens, is worse than a missing one.

The type libraries export no enumerations, so as with the constraint types
themselves the only way to learn this is to set a value and look at what moved.

    python scripts/probe_kompas_points.py                  # every scenario
    python scripts/probe_kompas_points.py --scenario line-line
    python scripts/probe_kompas_points.py --members        # what the interface has

Scenarios, and the trap each one exists to avoid:

* `line-line` — coincident between two segments whose four endpoints are all
  distinct and far apart. If any two of them were close, "start moved onto the
  partner's start" and "end moved onto the partner's start" would be separated by
  less than the tolerance and the table would be a coin toss.
* `line-circle` — a circle as the partner, because a circle has a centre and no
  endpoints. Whichever index moves the segment onto the circle's centre is the
  one that means *centre*, and that cannot be learnt from two segments.
* `midpoint` — the midpoint constraint over the same index pairs. Midpoint is
  not symmetric: one operand contributes a point and the other a whole segment,
  so it is the scenario that says whether `Index` refers to the subject or to
  whatever the constraint considers its first operand.
* `line-arc` — an arc as the partner. An arc is the one entity with *both*
  endpoints and a centre, so the index that means "centre" on a circle need not
  be the same one here. This matters directly: `concentric` in the contract is a
  coincidence of two centres, and on an arc a wrong index would silently pin an
  endpoint instead.

Nothing here is saved. Each attempt builds a throwaway part, reads coordinates
**inside** the sketch edit — after `EndEdit` the entity proxies answer zero for
everything, which looks exactly like a constraint that collapsed the sketch —
and closes the document without saving.

Findings are written up in docs/TASK-POSTMVP-007-sketch-constraints.md.
"""

from __future__ import annotations

import argparse
import sys

K7 = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI7.tlb"

#: Measured in POSTMVP-007. Restated rather than imported, because this probe has
#: to be runnable on a machine that has nothing but KOMPAS and this file.
COINCIDENT = 11
MIDPOINT = 20

TOLERANCE = 1e-6

#: The two segments. Every endpoint, and both midpoints, are separated by more
#: than a millimetre from every other, so no two candidate answers can be
#: confused for one another.
A_LINE = (0.0, 0.0, 40.0, 12.0)
B_LINE = (60.0, 30.0, 95.0, 47.0)
#: The circle's centre sits where nothing else does, for the same reason.
A_CIRCLE = (-25.0, 18.0, 7.0)
#: Centre, radius, start and end angle. A quarter arc in the first quadrant of
#: its own centre, so its centre, its two ends and its midpoint are four clearly
#: separated points — an arc spanning 180 degrees would put its centre on the
#: chord and make "centre" and "midpoint of the chord" the same answer.
A_ARC = (-25.0, -30.0, 12.0, 0.0, 90.0)

#: Swept, not guessed. 0-based and 1-based are both plausible and a negative
#: value is how several other KOMPAS calls spell "not specified" — `GetPart(-1)`
#: being the one this project already relies on.
INDICES = (-1, 0, 1, 2, 3, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("line-line", "line-circle", "midpoint", "line-arc", "all"),
        default="all",
    )
    parser.add_argument(
        "--members",
        action="store_true",
        help="print the members of IParametriticConstraint and exit",
    )
    parser.add_argument(
        "--type",
        type=int,
        default=None,
        help="override the scenario's constraint type, to sweep indices for another kind",
    )
    parser.add_argument("--tlb", default=K7)
    arguments = parser.parse_args()

    try:
        import comtypes.client
    except ImportError:
        print("comtypes is required: pip install comtypes", file=sys.stderr)
        return 2

    k7 = comtypes.client.GetModule(arguments.tlb)
    application = comtypes.client.CreateObject("KOMPAS.Application.7", interface=k7.IApplication)
    application.Visible = False

    try:
        if arguments.members:
            return _print_members(k7, application)
        scenarios = (
            SCENARIOS if arguments.scenario == "all"
            else {arguments.scenario: SCENARIOS[arguments.scenario]}
        )
        for name, scenario in scenarios.items():
            if arguments.type is not None:
                scenario = {**scenario, "type": arguments.type,
                            "what": f"{scenario['what']} — type {arguments.type}"}
            print(f"\n== {name}: {scenario['what']}")
            print("index partner  created  effect")
            for index in INDICES:
                for partner_index in INDICES:
                    _attempt(k7, application, scenario, index, partner_index)
    finally:
        try:
            application.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


def _print_members(k7, application) -> int:
    """What the constraint interface actually exposes.

    Worth printing rather than assuming: the whole reason this probe exists is
    that two of its properties are undocumented here, and a third one nobody has
    noticed would be exactly the same kind of gap.
    """
    document, sketch, view = _fresh_sketch(k7, application)
    try:
        line = _line(k7, view, B_LINE)
        handle = line["object"].QueryInterface(k7.IDrawingObject1).NewConstraint()
        item = handle.QueryInterface(k7.IParametriticConstraint)
        for name in sorted(name for name in dir(item) if not name.startswith("_")):
            print(name)
        sketch.EndEdit()
    finally:
        document.Close(0)
    return 0


# --------------------------------------------------------------------------
# One attempt
# --------------------------------------------------------------------------


def _attempt(k7, application, scenario, index: int, partner_index: int) -> None:
    document, sketch, view = _fresh_sketch(k7, application)
    try:
        entities = scenario["build"](k7, view)
        try:
            handle = entities["subject"]["object"].QueryInterface(k7.IDrawingObject1).NewConstraint()
            item = handle.QueryInterface(k7.IParametriticConstraint)
            item.ConstraintType = scenario["type"]
            item.Partner = entities["partner"]["object"]
            item.Index = index
            item.PartnerIndex = partner_index
            created = item.Create()
        except Exception as error:  # noqa: BLE001
            print(f"{index:>5} {partner_index:>7}  raised {type(error).__name__}: {error}")
            return
        effect = scenario["describe"](entities)
        sketch.EndEdit()
        print(f"{index:>5} {partner_index:>7}  {created!s:<7}  {', '.join(effect)}")
    finally:
        document.Close(0)


def _fresh_sketch(k7, application):
    document = application.Documents.Add(4, False)
    top = document.QueryInterface(k7.IKompasDocument3D).TopPart
    part = top.QueryInterface(k7.IPart7)
    container = top.QueryInterface(k7.IModelContainer)
    handle = container.Sketchs.QueryInterface(k7.ISketchs).Add()
    sketch = handle.QueryInterface(k7.ISketch)
    sketch.Plane = part.DefaultObject(1)
    fragment = sketch.BeginEdit()
    view = (
        fragment.QueryInterface(k7.IFragmentDocument)
        .ViewsAndLayersManager.QueryInterface(k7.IViewsAndLayersManager)
        .Views.QueryInterface(k7.IViews)
        .ActiveView.QueryInterface(k7.IDrawingContainer)
    )
    return document, sketch, view


def _line(k7, view, coordinates):
    obj = view.LineSegments.QueryInterface(k7.ILineSegments).Add()
    segment = obj.QueryInterface(k7.ILineSegment)
    segment.X1, segment.Y1, segment.X2, segment.Y2 = coordinates
    segment.Update()
    return {"object": obj, "entity": segment, "was": coordinates, "kind": "line"}


def _arc(k7, view, coordinates):
    """Centre, radius and two angles — the form POSTMVP-006 measured as the only
    one that works. Setting the endpoints directly leaves Update() false with the
    radius still at zero."""
    import math

    obj = view.Arcs.QueryInterface(k7.IArcs).Add()
    arc = obj.QueryInterface(k7.IArc)
    arc.Xc, arc.Yc, arc.Radius, arc.Angle1, arc.Angle2 = coordinates
    arc.Direction = 0
    arc.Update()
    centre_x, centre_y, radius, start, end = coordinates
    return {
        "object": obj,
        "entity": arc,
        "was": (centre_x, centre_y, radius),
        "kind": "arc",
        "expected": {
            "centre": (centre_x, centre_y),
            "start": (centre_x + radius * math.cos(math.radians(start)),
                      centre_y + radius * math.sin(math.radians(start))),
            "end": (centre_x + radius * math.cos(math.radians(end)),
                    centre_y + radius * math.sin(math.radians(end))),
            "arc mid": (centre_x + radius * math.cos(math.radians((start + end) / 2)),
                        centre_y + radius * math.sin(math.radians((start + end) / 2))),
        },
    }


def _circle(k7, view, coordinates):
    obj = view.Circles.QueryInterface(k7.ICircles).Add()
    circle = obj.QueryInterface(k7.ICircle)
    circle.Xc, circle.Yc, circle.Radius = coordinates
    circle.Update()
    return {"object": obj, "entity": circle, "was": coordinates, "kind": "circle"}


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


def _build_line_line(k7, view):
    return {"partner": _line(k7, view, A_LINE), "subject": _line(k7, view, B_LINE)}


def _build_line_circle(k7, view):
    return {"partner": _circle(k7, view, A_CIRCLE), "subject": _line(k7, view, B_LINE)}


def _build_line_arc(k7, view):
    return {"partner": _arc(k7, view, A_ARC), "subject": _line(k7, view, B_LINE)}


def _points_of(entity, kind) -> list[tuple[str, float, float]]:
    """The named points a KOMPAS entity could plausibly offer a constraint."""
    if kind == "circle":
        return [("centre", entity.Xc, entity.Yc)]
    if kind == "arc":
        import math

        return [
            ("centre", entity.Xc, entity.Yc),
            ("start", entity.Xc + entity.Radius * math.cos(math.radians(entity.Angle1)),
             entity.Yc + entity.Radius * math.sin(math.radians(entity.Angle1))),
            ("end", entity.Xc + entity.Radius * math.cos(math.radians(entity.Angle2)),
             entity.Yc + entity.Radius * math.sin(math.radians(entity.Angle2))),
            ("arc mid",
             entity.Xc + entity.Radius * math.cos(math.radians((entity.Angle1 + entity.Angle2) / 2)),
             entity.Yc + entity.Radius * math.sin(math.radians((entity.Angle1 + entity.Angle2) / 2))),
        ]
    return [
        ("start", entity.X1, entity.Y1),
        ("end", entity.X2, entity.Y2),
        ("mid", (entity.X1 + entity.X2) / 2, (entity.Y1 + entity.Y2) / 2),
    ]


def _describe_pairing(entities) -> list[str]:
    """Which point of the subject landed on which point of the partner.

    Both sides are reported. The solver is free to move either operand, and a
    table that only watched the subject would read "unchanged" for exactly the
    cases where the partner was the one that moved.
    """
    subject = entities["subject"]
    partner = entities["partner"]
    facts = []
    subject_moved = not _same(_flat(subject), subject["was"])
    partner_moved = not _same(_flat(partner), partner["was"])
    if not subject_moved and not partner_moved:
        return ["nothing moved"]

    for name, x, y in _points_of(subject["entity"], subject["kind"]):
        for other, px, py in _points_of(partner["entity"], partner["kind"]):
            if abs(x - px) < 1e-5 and abs(y - py) < 1e-5:
                facts.append(f"subject {name} == partner {other}")
    if not facts:
        facts.append("moved, no pair of named points met")
    facts.append(f"[{'subject' if subject_moved else ''}"
                 f"{'+partner' if partner_moved else ''} moved]")
    facts.append(f"[B {_show(subject)} A {_show(partner)}]")
    return facts


def _flat(item):
    entity = item["entity"]
    if item["kind"] in ("circle", "arc"):
        return (entity.Xc, entity.Yc, entity.Radius)
    return (entity.X1, entity.Y1, entity.X2, entity.Y2)


def _show(item) -> str:
    values = _flat(item)
    if item["kind"] in ("circle", "arc"):
        return f"({values[0]:.2f},{values[1]:.2f}) r{values[2]:.2f}"
    return f"({values[0]:.2f},{values[1]:.2f})->({values[2]:.2f},{values[3]:.2f})"


def _same(left, right) -> bool:
    return all(abs(a - b) < TOLERANCE for a, b in zip(left, right))


SCENARIOS = {
    "line-line": {
        "what": "coincident between two segments, all four endpoints distinct",
        "type": COINCIDENT,
        "build": _build_line_line,
        "describe": _describe_pairing,
    },
    "line-circle": {
        "what": "coincident between a segment and a circle, to find the centre index",
        "type": COINCIDENT,
        "build": _build_line_circle,
        "describe": _describe_pairing,
    },
    "midpoint": {
        "what": "midpoint between two segments, which is not symmetric",
        "type": MIDPOINT,
        "build": _build_line_line,
        "describe": _describe_pairing,
    },
    "line-arc": {
        "what": "coincident between a segment and an arc, which has ends and a centre",
        "type": COINCIDENT,
        "build": _build_line_arc,
        "describe": _describe_pairing,
    },
}


if __name__ == "__main__":
    raise SystemExit(main())
