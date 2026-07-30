"""Identify KOMPAS sketch ConstraintType values by what they do to geometry.

Unlike the topology and sketch probes, this one cannot read anything: the type
libraries export **no enumerations at all**, so the constraint constants do not
exist in any file on this machine. They can only be observed.

So each candidate type is applied to a deliberately wrong pair of line segments
and the resulting coordinates say which constraint it was.

    python scripts/probe_kompas_constraints.py            # A horizontal
    python scripts/probe_kompas_constraints.py --oblique   # A at 26.57 degrees

Both passes are needed. With a horizontal A, "make B horizontal" and "make B
parallel to A" produce the same answer, and the two types are indistinguishable.
The oblique pass separates them.

This one **does** start KOMPAS and build sketches, unlike the other probes. It
creates and closes its own throwaway documents and saves nothing.

Findings are written up in docs/TASK-POSTMVP-007-sketch-constraints.md.
"""

from __future__ import annotations

import argparse
import sys

K7 = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI7.tlb"

#: Types worth reporting. The full sweep from 0 to 39 showed everything outside
#: this set failing to create at all, so the range is recorded rather than
#: re-walked on every run.
CANDIDATES = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 17, 18, 19, 20)

#: The reference pair. B is neither parallel nor perpendicular to either A, and
#: its length differs from A's, so any of those becoming true is the constraint
#: speaking rather than a coincidence of the setup.
A_HORIZONTAL = (0.0, 0.0, 20.0, 0.0)
A_OBLIQUE = (0.0, 0.0, 20.0, 10.0)
B = (0.0, 14.0, 18.0, 20.0)

TOLERANCE = 1e-6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oblique", action="store_true", help="tilt the reference segment")
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
    reference = A_OBLIQUE if arguments.oblique else A_HORIZONTAL

    try:
        print(f"reference  A={_format(reference)}  B={_format(B)}")
        print("type  create valid  B after                              effect")
        for constraint_type in CANDIDATES:
            _attempt(k7, application, reference, constraint_type)
    finally:
        try:
            application.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


def _attempt(k7, application, reference, constraint_type: int) -> None:
    document, sketch, (a_object, a), (b_object, b) = _fresh_sketch(k7, application, reference)
    try:
        constraint = b_object.QueryInterface(k7.IDrawingObject1).NewConstraint()
        item = constraint.QueryInterface(k7.IParametriticConstraint)
        item.ConstraintType = constraint_type
        item.Partner = a_object
        created, valid = item.Create(), item.Valid
    except Exception as error:  # noqa: BLE001
        print(f"{constraint_type:>4}  raised {type(error).__name__}")
        document.Close(0)
        return

    # Read inside the edit. Once EndEdit runs the entity proxies stop answering
    # with coordinates and everything reads back as zero — which looks exactly
    # like a constraint that collapsed the geometry to the origin.
    after = _format((b.X1, b.Y1, b.X2, b.Y2))
    moved_reference = _format((a.X1, a.Y1, a.X2, a.Y2))
    effect = _describe(a, b) if after != _format(B) else ["unchanged"]
    sketch.EndEdit()

    note = ", ".join(effect) or "moved"
    if moved_reference != _format(reference):
        # A constraint may move either object. Saying which is which matters:
        # "B became parallel" and "both were rotated until they were parallel"
        # are different facts about the solver.
        note += f"  [A moved to {moved_reference}]"
    print(f"{constraint_type:>4}  {created!s:<6} {valid!s:<6} {after:<38} {note}")
    document.Close(0)


def _fresh_sketch(k7, application, reference):
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
    segments = view.LineSegments.QueryInterface(k7.ILineSegments)

    def line(coordinates):
        obj = segments.Add()
        segment = obj.QueryInterface(k7.ILineSegment)
        segment.X1, segment.Y1, segment.X2, segment.Y2 = coordinates
        segment.Update()
        return obj, segment

    return document, sketch, line(reference), line(B)


def _describe(a, b) -> list[str]:
    """What is now true of B relative to A."""
    facts = []
    if abs(b.Y1 - b.Y2) < TOLERANCE:
        facts.append("B horizontal")
    if abs(b.X1 - b.X2) < TOLERANCE:
        facts.append("B vertical")
    ax, ay = a.X2 - a.X1, a.Y2 - a.Y1
    bx, by = b.X2 - b.X1, b.Y2 - b.Y1
    if abs((ax * ax + ay * ay) ** 0.5 - (bx * bx + by * by) ** 0.5) < TOLERANCE:
        facts.append("equal length")
    if abs(ax * by - ay * bx) < TOLERANCE:
        facts.append("parallel to A")
    if abs(ax * bx + ay * by) < TOLERANCE:
        facts.append("perpendicular to A")
    for name, px, py in (("A start", a.X1, a.Y1), ("A end", a.X2, a.Y2)):
        for other, qx, qy in (("B start", b.X1, b.Y1), ("B end", b.X2, b.Y2)):
            if abs(px - qx) < TOLERANCE and abs(py - qy) < TOLERANCE:
                facts.append(f"{other} on {name}")
    if abs(ax * (b.Y1 - a.Y1) - ay * (b.X1 - a.X1)) < TOLERANCE:
        facts.append("B start on line A")
    return facts


def _format(coordinates) -> str:
    x1, y1, x2, y2 = coordinates
    return f"({x1:.3f},{y1:.3f})->({x2:.3f},{y2:.3f})"


if __name__ == "__main__":
    raise SystemExit(main())
