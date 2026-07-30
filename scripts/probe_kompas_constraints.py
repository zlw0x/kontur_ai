"""Identify KOMPAS sketch ConstraintType values by what they do to geometry.

Unlike the topology and sketch probes, this one cannot read anything: the type
libraries export **no enumerations at all**, so the constraint constants do not
exist in any file on this machine. They can only be observed.

So each candidate type is applied to deliberately wrong geometry and the
resulting coordinates say which constraint it was.

    python scripts/probe_kompas_constraints.py                  # every scenario
    python scripts/probe_kompas_constraints.py --scenario lines

Scenarios exist because one reference pair cannot separate everything:

* `lines` — two straight segments, the reference oblique. A *horizontal*
  reference would make "make B horizontal" and "make B parallel to A" produce
  the same answer, and the two types would be indistinguishable. That trap
  produced one wrong table before the tilt was added.
* `circles` — two circles, which is the only way concentricity and
  circle-to-circle tangency can show up at all.
* `line-circle` — tangency between a straight line and a circle.
* `symmetry` — two segments and a third acting as the axis, set through the
  constraint's `Axis` property.
* `unary` — no partner at all, which is the shape a `fixed` constraint has.
* `dimension` / `dimension-pair` — the same enumeration also carries the
  *driving* dimensions, and those do nothing at all until `Value` is set. A type
  that looks inert without a value is not necessarily inert.

This probe **does** start KOMPAS and build sketches, unlike the others. It
creates and closes its own throwaway documents and saves nothing.

Findings are written up in docs/TASK-POSTMVP-007-sketch-constraints.md.
"""

from __future__ import annotations

import argparse
import sys

K7 = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI7.tlb"

#: Swept rather than curated. A subset that creates for two straight segments is
#: not the subset that creates for two circles, and guessing which is which is
#: how a constraint gets mistaken for "unsupported".
CANDIDATES = tuple(range(0, 41))

TOLERANCE = 1e-6

#: Deliberately wrong in every respect the constraints could fix: not parallel,
#: not perpendicular, different lengths, not concentric, not tangent.
A_OBLIQUE = (0.0, 0.0, 20.0, 10.0)
#: No coordinate is shared with the reference. An earlier version started B at
#: x = 0, the same as A, and a constraint that aligned the two x coordinates
#: read as "unchanged" — the same class of trap as a horizontal reference
#: hiding the difference between horizontal and parallel.
B_LINE = (3.0, 14.0, 18.0, 21.0)
AXIS_LINE = (10.0, -10.0, 10.0, 30.0)
#: Distinct from every length, span and radius in the reference geometry, so a
#: measurement landing on it is the dimension having driven it there.
DIMENSION_VALUE = 50.0

A_CIRCLE = (0.0, 0.0, 10.0)
B_CIRCLE = (14.0, 3.0, 6.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("lines", "circles", "line-circle", "symmetry", "unary", "dimension",
                 "dimension-pair", "driving-dimension", "all"),
        default="all",
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
    scenarios = SCENARIOS if arguments.scenario == "all" else {arguments.scenario: SCENARIOS[arguments.scenario]}

    try:
        for name, scenario in scenarios.items():
            print(f"\n== {name}: {scenario['what']}")
            print("type  create valid  effect")
            for constraint_type in CANDIDATES:
                _attempt(k7, application, scenario, constraint_type)
    finally:
        try:
            application.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


# --------------------------------------------------------------------------
# One attempt
# --------------------------------------------------------------------------


def _attempt(k7, application, scenario, constraint_type: int) -> None:
    document, sketch, view = _fresh_sketch(k7, application)
    try:
        entities = scenario["build"](k7, view)
        subject = entities["subject"]
        try:
            constraint = subject["object"].QueryInterface(k7.IDrawingObject1).NewConstraint()
            item = constraint.QueryInterface(k7.IParametriticConstraint)
            item.ConstraintType = constraint_type
            if "partner" in entities:
                item.Partner = entities["partner"]["object"]
            if "axis" in entities:
                item.Axis = entities["axis"]["object"]
            if scenario.get("value") is not None:
                item.Value = scenario["value"]
                item.Variable = scenario.get("variable", "probe_size")
            created, valid = item.Create(), item.Valid
        except Exception as error:  # noqa: BLE001
            print(f"{constraint_type:>4}  raised {type(error).__name__}")
            return
        # Read inside the edit. Once EndEdit runs the entity proxies stop
        # answering with coordinates and everything reads back as zero — which
        # looks exactly like a constraint that collapsed the sketch to the
        # origin, and cost one wrong table before this was understood.
        effect = scenario["describe"](entities)
        sketch.EndEdit()
        print(f"{constraint_type:>4}  {created!s:<6} {valid!s:<6} {', '.join(effect) or 'moved'}")
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


def _circle(k7, view, coordinates):
    obj = view.Circles.QueryInterface(k7.ICircles).Add()
    circle = obj.QueryInterface(k7.ICircle)
    circle.Xc, circle.Yc, circle.Radius = coordinates
    circle.Update()
    return {"object": obj, "entity": circle, "was": coordinates, "kind": "circle"}


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


def _build_lines(k7, view):
    return {"partner": _line(k7, view, A_OBLIQUE), "subject": _line(k7, view, B_LINE)}


def _build_symmetry(k7, view):
    return {
        "partner": _line(k7, view, A_OBLIQUE),
        "subject": _line(k7, view, B_LINE),
        "axis": _line(k7, view, AXIS_LINE),
    }


def _build_circles(k7, view):
    return {"partner": _circle(k7, view, A_CIRCLE), "subject": _circle(k7, view, B_CIRCLE)}


def _build_line_circle(k7, view):
    return {"partner": _line(k7, view, A_OBLIQUE), "subject": _circle(k7, view, B_CIRCLE)}


def _build_unary(k7, view):
    return {"subject": _line(k7, view, B_LINE)}


def _build_driving_dimension(k7, view):
    """A segment, plus a linear dimension drawn over it.

    Dimensions live on ISymbols2DContainer, not on the geometry container, and
    the question this scenario answers is whether attaching a constraint to the
    *dimension* is what makes it drive the geometry.
    """
    subject = _line(k7, view, B_LINE)
    symbols = view.QueryInterface(k7.ISymbols2DContainer)
    obj = symbols.LineDimensions.QueryInterface(k7.ILineDimensions).Add()
    dimension = obj.QueryInterface(k7.ILineDimension)
    dimension.X1, dimension.Y1 = B_LINE[0], B_LINE[1]
    dimension.X2, dimension.Y2 = B_LINE[2], B_LINE[3]
    dimension.X3, dimension.Y3 = B_LINE[0], B_LINE[1] + 8
    obj.QueryInterface(k7.IDrawingObject).Update()
    # A dimension has to be associated with the geometry it measures before it
    # can drive it. Associate() takes no arguments: it binds the dimension to
    # whatever its own points already sit on.
    associated = obj.QueryInterface(k7.IDrawingObject1).Associate()
    # The constraint goes on the dimension; the geometry is what we watch.
    return {"subject": {"object": obj, "entity": dimension, "was": B_LINE, "kind": "dimension",
                        "associated": associated},
            "watch": subject}


def _describe_driving_dimension(entities) -> list[str]:
    b = entities["watch"]["entity"]
    length = ((b.X2 - b.X1) ** 2 + (b.Y2 - b.Y1) ** 2) ** 0.5
    facts = []
    if abs(length - DIMENSION_VALUE) < 1e-5:
        facts.append(f"the segment length became {DIMENSION_VALUE}")
    elif not _same((b.X1, b.Y1, b.X2, b.Y2), B_LINE):
        facts.append("the segment moved")
    facts.append(f"[length {length:.3f}, associated {entities['subject'].get('associated')}]")
    return facts


def _describe_dimension(entities) -> list[str]:
    """Which measurement of the subject became the value that was set."""
    b = entities["subject"]["entity"]
    facts = []
    if entities["subject"]["kind"] == "line":
        length = ((b.X2 - b.X1) ** 2 + (b.Y2 - b.Y1) ** 2) ** 0.5
        horizontal = abs(b.X2 - b.X1)
        vertical = abs(b.Y2 - b.Y1)
        for name, measured in (("length", length), ("horizontal span", horizontal),
                               ("vertical span", vertical)):
            if abs(measured - DIMENSION_VALUE) < 1e-5:
                facts.append(f"{name} = {DIMENSION_VALUE}")
        facts.append(f"[length {length:.3f} span {horizontal:.3f}x{vertical:.3f}]")
        return facts
    for name, measured in (("radius", b.Radius), ("diameter", b.Radius * 2)):
        if abs(measured - DIMENSION_VALUE) < 1e-5:
            facts.append(f"{name} = {DIMENSION_VALUE}")
    facts.append(f"[r {b.Radius:.3f} centre ({b.Xc:.3f},{b.Yc:.3f})]")
    return facts


def _describe_dimension_pair(entities) -> list[str]:
    """Which distance between the two objects became the value that was set."""
    a = entities["partner"]["entity"]
    b = entities["subject"]["entity"]
    facts = []
    for name, px, py in (("start", b.X1, b.Y1), ("end", b.X2, b.Y2)):
        for other, qx, qy in (("start", a.X1, a.Y1), ("end", a.X2, a.Y2)):
            distance = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
            if abs(distance - DIMENSION_VALUE) < 1e-5:
                facts.append(f"B {name} to A {other} = {DIMENSION_VALUE}")
    ax, ay = a.X2 - a.X1, a.Y2 - a.Y1
    bx, by = b.X2 - b.X1, b.Y2 - b.Y1
    import math
    angle = math.degrees(math.acos(max(-1.0, min(1.0,
        (ax * bx + ay * by) / (((ax * ax + ay * ay) ** 0.5) * ((bx * bx + by * by) ** 0.5))))))
    if abs(angle - DIMENSION_VALUE) < 1e-3 or abs(180 - angle - DIMENSION_VALUE) < 1e-3:
        facts.append(f"angle = {DIMENSION_VALUE} degrees")
    facts.append(f"[angle {angle:.3f} deg]")
    return facts


def _describe_lines(entities) -> list[str]:
    a = entities["partner"]["entity"]
    b = entities["subject"]["entity"]
    now = (b.X1, b.Y1, b.X2, b.Y2)
    facts = []
    if _same(now, entities["subject"]["was"]):
        facts.append("unchanged")
    if abs(b.Y1 - b.Y2) < TOLERANCE:
        facts.append("horizontal")
    if abs(b.X1 - b.X2) < TOLERANCE:
        facts.append("vertical")
    ax, ay = a.X2 - a.X1, a.Y2 - a.Y1
    bx, by = b.X2 - b.X1, b.Y2 - b.Y1
    if abs((ax * ax + ay * ay) ** 0.5 - (bx * bx + by * by) ** 0.5) < TOLERANCE:
        facts.append("equal length")
    if abs(ax * by - ay * bx) < TOLERANCE:
        facts.append("parallel")
    if abs(ax * bx + ay * by) < TOLERANCE:
        facts.append("perpendicular")
    if abs(ax * (b.Y1 - a.Y1) - ay * (b.X1 - a.X1)) < TOLERANCE:
        facts.append("start on the reference line")
    if abs(b.X1 - a.X1) < TOLERANCE and abs(b.Y1 - a.Y1) < TOLERANCE:
        facts.append("start on the reference start")
    midpoint = ((a.X1 + a.X2) / 2, (a.Y1 + a.Y2) / 2)
    if abs(b.X1 - midpoint[0]) < TOLERANCE and abs(b.Y1 - midpoint[1]) < TOLERANCE:
        facts.append("start on the reference midpoint")
    if not _same((a.X1, a.Y1, a.X2, a.Y2), entities["partner"]["was"]):
        facts.append("the reference moved too")
    # Always report the numbers. A constraint nothing above recognises still has
    # to be identifiable from what it did, and the alternative is a table row
    # reading "moved" with nowhere to go from there.
    facts.append(f"[B ({b.X1:.3f},{b.Y1:.3f})->({b.X2:.3f},{b.Y2:.3f}) "
                 f"A ({a.X1:.3f},{a.Y1:.3f})->({a.X2:.3f},{a.Y2:.3f})]")
    return facts


def _describe_circles(entities) -> list[str]:
    a = entities["partner"]["entity"]
    b = entities["subject"]["entity"]
    facts = []
    if _same((b.Xc, b.Yc, b.Radius), entities["subject"]["was"]):
        facts.append("unchanged")
    distance = ((b.Xc - a.Xc) ** 2 + (b.Yc - a.Yc) ** 2) ** 0.5
    if distance < TOLERANCE:
        facts.append("concentric")
    if abs(b.Radius - a.Radius) < TOLERANCE:
        facts.append("equal radius")
    if abs(distance - (a.Radius + b.Radius)) < TOLERANCE:
        facts.append("externally tangent")
    if abs(distance - abs(a.Radius - b.Radius)) < TOLERANCE:
        facts.append("internally tangent")
    if not _same((a.Xc, a.Yc, a.Radius), entities["partner"]["was"]):
        facts.append("the reference moved too")
    facts.append(f"[centre distance {distance:.3f}, r {b.Radius:.3f}]")
    return facts


def _describe_line_circle(entities) -> list[str]:
    a = entities["partner"]["entity"]
    b = entities["subject"]["entity"]
    facts = []
    if _same((b.Xc, b.Yc, b.Radius), entities["subject"]["was"]):
        facts.append("unchanged")
    ax, ay = a.X2 - a.X1, a.Y2 - a.Y1
    length = (ax * ax + ay * ay) ** 0.5
    gap = abs(ax * (b.Yc - a.Y1) - ay * (b.Xc - a.X1)) / length
    if abs(gap - b.Radius) < 1e-5:
        facts.append("tangent to the line")
    if gap < TOLERANCE:
        facts.append("centre on the line")
    facts.append(f"[gap {gap:.3f}, r {b.Radius:.3f}]")
    return facts


def _describe_unary(entities) -> list[str]:
    b = entities["subject"]["entity"]
    now = (b.X1, b.Y1, b.X2, b.Y2)
    if _same(now, entities["subject"]["was"]):
        return ["accepted, geometry unchanged"]
    return [f"moved to ({b.X1:.3f},{b.Y1:.3f})->({b.X2:.3f},{b.Y2:.3f})"]


def _same(left, right) -> bool:
    return all(abs(a - b) < TOLERANCE for a, b in zip(left, right))


SCENARIOS = {
    "lines": {
        "what": "two straight segments, the reference oblique",
        "build": _build_lines,
        "describe": _describe_lines,
    },
    "circles": {
        "what": "two circles, neither concentric nor tangent",
        "build": _build_circles,
        "describe": _describe_circles,
    },
    "line-circle": {
        "what": "a circle against a straight segment",
        "build": _build_line_circle,
        "describe": _describe_line_circle,
    },
    "symmetry": {
        "what": "two segments and a third set as the constraint's Axis",
        "build": _build_symmetry,
        "describe": _describe_lines,
    },
    "unary": {
        "what": "no partner at all, the shape a fixed constraint has",
        "build": _build_unary,
        "describe": _describe_unary,
    },
    "dimension": {
        "what": f"one segment with Value set to {DIMENSION_VALUE}",
        "build": _build_unary,
        "describe": _describe_dimension,
        "value": DIMENSION_VALUE,
    },
    "driving-dimension": {
        "what": f"a linear dimension over a segment, Value set to {DIMENSION_VALUE}",
        "build": _build_driving_dimension,
        "describe": _describe_driving_dimension,
        "value": DIMENSION_VALUE,
    },
    "dimension-pair": {
        "what": f"two segments with Value set to {DIMENSION_VALUE}",
        "build": _build_lines,
        "describe": _describe_dimension_pair,
        "value": DIMENSION_VALUE,
    },
}


if __name__ == "__main__":
    raise SystemExit(main())
