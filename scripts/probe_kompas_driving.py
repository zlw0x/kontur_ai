"""Find out how a KOMPAS dimension is made to *drive* the geometry it measures.

POSTMVP-007 delivered dimensions that KOMPAS measures and reports: the document
states 60, the model is built at 60, and the variable reads back 60 in a fresh
process. That is what the confirmatory design needs and it is genuinely useful —
but nothing in it *drives*. Setting the value does not move the geometry, so the
delivered model is annotated rather than parametric, and a customer who edits the
number in KOMPAS gets a different result from one who edits it through us.

Four readings were ruled out already, all recorded in
docs/TASK-POSTMVP-007-sketch-constraints.md: `Value` before `Create`, `Value`
after `Create`, naming a `Variable` and looking it up, and `Expression` set to a
literal. What was left was the part's variable table and a parametric mode.

    python scripts/probe_kompas_driving.py --members       # what exists at all
    python scripts/probe_kompas_driving.py --scenario table
    python scripts/probe_kompas_driving.py --scenario angle

`--members` comes first on purpose. Every wrong turn in this milestone so far
started with assuming a member existed rather than looking; the type libraries
are the only authority on this machine and they cost one call to consult.

Scenarios:

* `table` — build a segment of a known length, dimension it, bind the dimension
  to a named variable, then try to change that variable through the part's
  variable table and see whether the segment follows.
* `angle` — `IAngleDimensions.Add` returned nothing for every type tried in the
  previous probe. This looks again with the argument forms the other dimension
  collections turned out to want, and reports what each one answers.

Nothing is saved. Each attempt builds a throwaway part and closes it.
"""

from __future__ import annotations

import argparse
import sys

K7 = r"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI7.tlb"

#: The dimension is bound to this name, and the table is asked to change it.
VARIABLE = "probe_len"
#: The segment is built at this length and the variable is set to the other one.
BUILT_LENGTH = 16.0
DRIVEN_LENGTH = 50.0
#: The angle scenario builds 30 degrees and asks for this one.
DRIVEN_ANGLE = 55.0
#: Measured in POSTMVP-007: on an associated dimension, type 13 creates a
#: variable whose value reads back as what KOMPAS measured.
DRIVING_DIMENSION = 13


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=("table", "angle", "angle-drive", "all"), default="all")
    parser.add_argument(
        "--members",
        action="store_true",
        help="print what the part, the sketch and the document expose, and exit",
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
            return _members(k7, application)
        if arguments.scenario in ("table", "all"):
            _table(k7, application)
        if arguments.scenario in ("angle", "all"):
            _angle(k7, application)
        if arguments.scenario in ("angle-drive", "all"):
            _angle_drive(k7, application)
    finally:
        try:
            application.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


# --------------------------------------------------------------------------
# What exists
# --------------------------------------------------------------------------


def _members(k7, application) -> int:
    """Print the members of everything a variable could plausibly hang off."""
    document = application.Documents.Add(4, False)
    try:
        top = document.QueryInterface(k7.IKompasDocument3D).TopPart
        interfaces = [
            ("IKompasDocument3D", document.QueryInterface(k7.IKompasDocument3D)),
            ("IPart7", top.QueryInterface(k7.IPart7)),
        ]
        # The variable table is a *property* of the part, not an interface the
        # part can be cast to. Every QueryInterface attempt at it fails with a
        # COMError, which reads like "this build has no variable table" and is
        # what sent the previous probe looking for a spreadsheet that was never
        # reachable that way.
        part = top.QueryInterface(k7.IPart7)
        try:
            interfaces.append(("IPart7.VariableTable", part.VariableTable))
        except Exception as error:  # noqa: BLE001
            print(f"-- part.VariableTable: {type(error).__name__}: {error}")
        for name in ("IKompasDocument3D1", "IPart8"):
            candidate = getattr(k7, name, None)
            if candidate is None:
                print(f"-- {name}: not in the type library")
                continue
            for source_name, source in (("document", document), ("part", top)):
                try:
                    interfaces.append((f"{name} (via {source_name})",
                                       source.QueryInterface(candidate)))
                except Exception as error:  # noqa: BLE001
                    print(f"-- {name} via {source_name}: {type(error).__name__}")

        for name, item in interfaces:
            print(f"\n== {name}")
            for member in sorted(m for m in dir(item) if not m.startswith("_")):
                print(f"   {member}")
    finally:
        document.Close(0)
    return 0


# --------------------------------------------------------------------------
# Does a variable drive the geometry?
# --------------------------------------------------------------------------


def _table(k7, application) -> None:
    """Every combination of switch and setter, each in its own document.

    One document per attempt on purpose. A variable that has already been written
    to, in a model that has already been rebuilt, is not the same starting state
    as a fresh one, and a matrix run in a single document would report the
    *sequence* rather than the switches.
    """
    print(f"\n== table: a {BUILT_LENGTH} mm segment, its variable set to {DRIVEN_LENGTH}")
    print("fixed  external  setter      variable  segment   verdict")
    for fixed in (False, True):
        for external in (None, True):
            for setter in ("Value", "Expression"):
                _drive(k7, application, fixed, external, setter)


def _drive(k7, application, fixed: bool, external, setter: str) -> None:
    document = application.Documents.Add(4, False)
    label = (f"{str(fixed):<5}  {str(external):<8}  {setter:<10}")
    try:
        top = document.QueryInterface(k7.IKompasDocument3D).TopPart
        part = top.QueryInterface(k7.IPart7)
        container = top.QueryInterface(k7.IModelContainer)
        handle = container.Sketchs.QueryInterface(k7.ISketchs).Add()
        sketch = handle.QueryInterface(k7.ISketch)
        sketch.Plane = part.DefaultObject(1)
        active, view = _open(k7, sketch)

        line_object = view.LineSegments.QueryInterface(k7.ILineSegments).Add()
        line = line_object.QueryInterface(k7.ILineSegment)
        line.X1, line.Y1, line.X2, line.Y2 = 0.0, 0.0, BUILT_LENGTH, 0.0
        line.Update()

        symbols = view.QueryInterface(k7.ISymbols2DContainer)
        dimension_object = symbols.LineDimensions.QueryInterface(k7.ILineDimensions).Add()
        dimension = dimension_object.QueryInterface(k7.ILineDimension)
        dimension.X1, dimension.Y1 = 0.0, 0.0
        dimension.X2, dimension.Y2 = BUILT_LENGTH, 0.0
        dimension.X3, dimension.Y3 = 0.0, -8.0
        dimension_object.QueryInterface(k7.IDrawingObject).Update()
        dimension_object.QueryInterface(k7.IDrawingObject1).Associate()

        constraint = dimension_object.QueryInterface(k7.IDrawingObject1).NewConstraint()
        item = constraint.QueryInterface(k7.IParametriticConstraint)
        item.ConstraintType = DRIVING_DIMENSION
        item.Variable = VARIABLE
        if not item.Create():
            print(f"{label}  constraint refused")
            return
        # Type 14 is the other one that creates on an associated dimension and
        # yields no variable of its own. A type that attaches to a dimension and
        # names nothing is what a *fix* looks like — and a fixed dimension is
        # exactly the thing that imposes its value instead of reporting it.
        if fixed:
            second = dimension_object.QueryInterface(k7.IDrawingObject1).NewConstraint()
            other = second.QueryInterface(k7.IParametriticConstraint)
            other.ConstraintType = 14
            if not other.Create():
                print(f"{label}  type 14 refused")
                return
        # Closed, rebuilt and reopened before the variable is touched. The
        # variable is readable inside the edit that created it — an earlier run of
        # this probe concluded otherwise, and was wrong: it had already called
        # EndEdit, and a view proxy from a closed edit answers nothing at all,
        # which is indistinguishable from a variable that was never created.
        sketch.EndEdit()
        _rebuild(k7, document, part, quiet=True)

        active, view = _open(k7, sketch)
        found = active.Variable(VARIABLE)
        if found is None:
            print(f"{label}  no variable")
            sketch.EndEdit()
            return
        variable = found.QueryInterface(k7.IVariable7)
        # `External` is KOMPAS's own word for a variable that may be set from
        # outside the model rather than computed by it.
        if external is not None:
            try:
                variable.External = external
            except Exception as error:  # noqa: BLE001
                print(f"{label}  External refused: {type(error).__name__}")
                sketch.EndEdit()
                return
        try:
            if setter == "Value":
                variable.Value = DRIVEN_LENGTH
            else:
                variable.Expression = str(DRIVEN_LENGTH)
        except Exception as error:  # noqa: BLE001
            print(f"{label}  {setter} refused: {type(error).__name__}")
            sketch.EndEdit()
            return
        sketch.EndEdit()
        _rebuild(k7, document, part, quiet=True)

        # Re-found rather than remembered: the proxy from the previous edit
        # answers zero for every coordinate, which reads as a sketch that
        # collapsed to the origin and is really just a stale pointer.
        active, view = _open(k7, sketch)
        length, value = _measure(k7, active, view)
        verdict = "DRIVEN" if abs(length - DRIVEN_LENGTH) < 1e-5 else "unchanged"
        print(f"{label}  {value:<8.3f}  {length:<8.4f}  {verdict}")
        sketch.EndEdit()
    except Exception as error:  # noqa: BLE001
        print(f"{label}  {type(error).__name__}: {error}")
    finally:
        document.Close(0)


def _measure(k7, active, view):
    """The first segment in the sketch, and what the variable now says."""
    segments = view.LineSegments.QueryInterface(k7.ILineSegments)
    length = 0.0
    if segments.Count:
        line = segments.LineSegment(0).QueryInterface(k7.ILineSegment)
        length = ((line.X2 - line.X1) ** 2 + (line.Y2 - line.Y1) ** 2) ** 0.5
    found = active.Variable(VARIABLE)
    value = found.QueryInterface(k7.IVariable7).Value if found is not None else float("nan")
    return length, value


def _report_variables(k7, part, active, when: str) -> None:
    """Everything that could be called a variable, from both ends.

    The part's table and the view's lookup are separate answers, and which of
    them knows about the dimension is itself the finding.
    """
    try:
        table = part.VariableTable
        print(f"   [{when}] table: {table.RowsCount} rows x {table.ColumnsCount} columns, "
              f"names {table.VarNames}")
    except Exception as error:  # noqa: BLE001
        print(f"   [{when}] table: {type(error).__name__}: {error}")
    for name in (VARIABLE, VARIABLE.lower(), VARIABLE.upper(), "v" + VARIABLE):
        try:
            found = active.Variable(name)
        except Exception as error:  # noqa: BLE001
            print(f"   [{when}] Variable({name!r}): {type(error).__name__}")
            continue
        if found is not None:
            print(f"   [{when}] Variable({name!r}) -> "
                  f"{found.QueryInterface(k7.IVariable7).Value}")


def _rebuild(k7, document, part, quiet: bool = False) -> None:
    """Regenerate the model. `RebuildModel` wants a Redraw argument; the document
    level takes none and answers True."""
    try:
        answer = document.QueryInterface(k7.IKompasDocument3D).RebuildDocument()
        if not quiet:
            print(f"   RebuildDocument: {answer}")
    except Exception as error:  # noqa: BLE001
        if not quiet:
            print(f"   RebuildDocument: {type(error).__name__}: {error}")


def _open(k7, sketch):
    """Enter the sketch and hand back both faces of its active view.

    `Variable` lives on `IView` and the geometry collections on
    `IDrawingContainer`; they are the same object seen through two interfaces,
    and asking the wrong one for the other's member fails as a plain missing
    attribute rather than as anything that suggests the cast.
    """
    fragment = sketch.BeginEdit()
    active = (
        fragment.QueryInterface(k7.IFragmentDocument)
        .ViewsAndLayersManager.QueryInterface(k7.IViewsAndLayersManager)
        .Views.QueryInterface(k7.IViews)
        .ActiveView
    )
    return active.QueryInterface(k7.IView), active.QueryInterface(k7.IDrawingContainer)


# --------------------------------------------------------------------------
# Angular dimensions
# --------------------------------------------------------------------------


def _angle(k7, application) -> None:
    """`IAngleDimensions.Add` answered with nothing before. Ask it differently."""
    print("\n== angle: what IAngleDimensions.Add answers, by argument form")
    document = application.Documents.Add(4, False)
    try:
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
        symbols = view.QueryInterface(k7.ISymbols2DContainer)
        dimensions = symbols.AngleDimensions.QueryInterface(k7.IAngleDimensions)
        print(f"   collection: {[m for m in dir(dimensions) if not m.startswith('_')]}")
        # Swept rather than guessed, the same as the constraint types. `Add` takes
        # a `DimType` and answers None for every small value, so either the
        # constants live somewhere else entirely or the collection needs something
        # else first — and a sweep is what separates those two.
        made = []
        for candidate in range(-2, 65):
            try:
                answer = dimensions.Add(candidate)
            except Exception as error:  # noqa: BLE001
                print(f"   Add({candidate}): {type(error).__name__}: {error}")
                continue
            if answer:
                made.append(candidate)
                item = answer.QueryInterface(k7.IAngleDimension)
                print(f"   Add({candidate}): created — "
                      f"members {[m for m in dir(item) if not m.startswith('_')]}")
        if not made:
            print(f"   Add(-2..64): every value answered None; collection count "
                  f"{dimensions.Count}")
        sketch.EndEdit()
    finally:
        document.Close(0)


def _angle_drive(k7, application) -> None:
    """Does an angular dimension drive the angle, the same way a linear one does?

    Built as two segments from a common corner, the second at a known 30 degrees,
    with the dimension told which two objects it measures through `BaseObject1`
    and `BaseObject2` rather than by where its own points happen to sit.
    """
    import math

    print(f"\n== angle-drive: two segments at 30 degrees, driven to {DRIVEN_ANGLE}")
    print("type  external  setter      variable  angle     verdict")
    for dimension_type in (10, 39):
        for setter in ("Value", "Expression"):
            document = application.Documents.Add(4, False)
            label = f"{dimension_type:<4}  {'None':<8}  {setter:<10}"
            try:
                top = document.QueryInterface(k7.IKompasDocument3D).TopPart
                part = top.QueryInterface(k7.IPart7)
                container = top.QueryInterface(k7.IModelContainer)
                handle = container.Sketchs.QueryInterface(k7.ISketchs).Add()
                sketch = handle.QueryInterface(k7.ISketch)
                sketch.Plane = part.DefaultObject(1)
                active, view = _open(k7, sketch)

                segments = view.LineSegments.QueryInterface(k7.ILineSegments)
                base_object = segments.Add()
                base = base_object.QueryInterface(k7.ILineSegment)
                base.X1, base.Y1, base.X2, base.Y2 = 0.0, 0.0, 40.0, 0.0
                base.Update()
                arm_object = segments.Add()
                arm = arm_object.QueryInterface(k7.ILineSegment)
                arm.X1, arm.Y1 = 0.0, 0.0
                arm.X2 = 40.0 * math.cos(math.radians(30.0))
                arm.Y2 = 40.0 * math.sin(math.radians(30.0))
                arm.Update()

                symbols = view.QueryInterface(k7.ISymbols2DContainer)
                dimension_object = (
                    symbols.AngleDimensions.QueryInterface(k7.IAngleDimensions)
                    .Add(dimension_type)
                )
                dimension = dimension_object.QueryInterface(k7.IAngleDimension)
                dimension.BaseObject1 = base_object
                dimension.BaseObject2 = arm_object
                dimension.Xc, dimension.Yc = 0.0, 0.0
                dimension.Radius = 25.0
                print(f"{label}  drawn "
                      f"{dimension_object.QueryInterface(k7.IDrawingObject).Update()}, "
                      f"bound {dimension_object.QueryInterface(k7.IDrawingObject1).Associate()}")

                for constraint_type in (DRIVING_DIMENSION, 14):
                    constraint = dimension_object.QueryInterface(k7.IDrawingObject1).NewConstraint()
                    item = constraint.QueryInterface(k7.IParametriticConstraint)
                    item.ConstraintType = constraint_type
                    if constraint_type == DRIVING_DIMENSION:
                        item.Variable = VARIABLE
                    if not item.Create():
                        print(f"{label}  type {constraint_type} refused")
                        raise StopIteration
                sketch.EndEdit()
                _rebuild(k7, document, part, quiet=True)

                active, view = _open(k7, sketch)
                found = active.Variable(VARIABLE)
                if found is None:
                    print(f"{label}  no variable")
                    sketch.EndEdit()
                    continue
                variable = found.QueryInterface(k7.IVariable7)
                if setter == "Value":
                    variable.Value = DRIVEN_ANGLE
                else:
                    variable.Expression = str(DRIVEN_ANGLE)
                sketch.EndEdit()
                _rebuild(k7, document, part, quiet=True)

                active, view = _open(k7, sketch)
                segments = view.LineSegments.QueryInterface(k7.ILineSegments)
                angle = float("nan")
                if segments.Count >= 2:
                    one = segments.LineSegment(0).QueryInterface(k7.ILineSegment)
                    two = segments.LineSegment(1).QueryInterface(k7.ILineSegment)
                    angle = abs(
                        math.degrees(math.atan2(two.Y2 - two.Y1, two.X2 - two.X1))
                        - math.degrees(math.atan2(one.Y2 - one.Y1, one.X2 - one.X1)))
                found = active.Variable(VARIABLE)
                value = (found.QueryInterface(k7.IVariable7).Value
                         if found is not None else float("nan"))
                verdict = "DRIVEN" if abs(angle - DRIVEN_ANGLE) < 1e-3 else "unchanged"
                print(f"{label}  {value:<8.3f}  {angle:<8.3f}  {verdict}")
                sketch.EndEdit()
            except StopIteration:
                pass
            except Exception as error:  # noqa: BLE001
                print(f"{label}  {type(error).__name__}: {error}")
            finally:
                document.Close(0)


if __name__ == "__main__":
    raise SystemExit(main())
