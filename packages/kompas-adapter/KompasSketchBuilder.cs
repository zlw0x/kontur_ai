using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

/// <summary>
/// Draws a planned sketch in KOMPAS and extrudes it.
/// </summary>
/// <remarks>
/// It knows about lines, arcs and circles, and nothing else. Slots, hexagons
/// and rotated rectangles were expanded into those by the parser, so there is
/// one implementation of that arithmetic rather than one here and another in
/// the validator.
///
/// Stateful because the model is: an auxiliary plane created by one feature is
/// what a later sketch sits on, so the planes a build has produced have to be
/// remembered across features. They are held as COM objects for the life of
/// one build and released with it — nothing outside this class ever sees one.
///
/// Runs on the caller's STA thread. See ADR-011.
/// </remarks>
internal sealed class KompasSketchBuilder(object document, double baseDepthMm) : IDisposable
{
    private const int PlaneXY = 1; // o3d_planeXOY
    private const int PlaneXZ = 2; // o3d_planeXOZ
    private const int PlaneYZ = 3; // o3d_planeYOZ
    private const int BaseExtrusion = 24; // o3d_baseExtrusion
    private const int CutExtrusion = 26; // o3d_cutExtrusion
    private const int OffsetPlane = 14; // IPlanes3D.Add, probed live; see TASK-POSTMVP-006
    private const int CutOperation = 2; // ksOperationCut

    private readonly Dictionary<string, object> planes = new(StringComparer.Ordinal);
    private readonly List<object> owned = [];

    /// <summary>Build one feature; returns the operation code for the ledger.</summary>
    public string Build(CadFeaturePlan feature, int number) => feature switch
    {
        DatumPlaneFeaturePlan plane => BuildDatumPlane(plane, number),
        ExtrudeFeaturePlan { IsCut: false } extrude => BuildExtrusion(extrude, "rectangular_prism"),
        ExtrudeFeaturePlan extrude => BuildExtrusion(extrude, $"cut_{number:D3}"),
        _ => throw KompasApi7Adapter.Failure(
            "UNSUPPORTED_FEATURE_TYPE", "feature", "The plan contains a feature this adapter cannot build.")
    };

    private string BuildDatumPlane(DatumPlaneFeaturePlan feature, int number)
    {
        object? topPartObject = null;
        try
        {
            topPartObject = ((IKompasDocument3D)document).TopPart;
            var container = (IAuxiliaryGeomContainer)topPartObject;
            var planeObject = ((IPlanes3D)container.Planes3D).Add(OffsetPlane)
                ?? throw KompasApi7Adapter.Failure(
                    "DATUM_PLANE_FAILED", "feature", "KOMPAS did not create an offset plane.");
            var offset = (IPlane3DByOffset)planeObject;
            offset.BasePlane = ResolveBase(feature, (IPart7)topPartObject);
            // KOMPAS takes a magnitude and a side, so a negative offset in the
            // document is the same plane reached from the other direction.
            offset.Offset = Math.Abs(feature.OffsetMm);
            offset.Direction = feature.Flip ^ (feature.OffsetMm >= 0);
            if (!((IModelObject)planeObject).Update())
                throw KompasApi7Adapter.Failure(
                    "DATUM_PLANE_FAILED", "feature", $"KOMPAS rejected offset plane {feature.ResultId}.");
            planes[feature.ResultId] = planeObject;
            owned.Add(planeObject);
            return $"datum_plane_{number:D3}";
        }
        finally { KompasApi7Adapter.Release(topPartObject); }
    }

    private object ResolveBase(DatumPlaneFeaturePlan feature, IPart7 part)
    {
        if (feature.BaseResultId is { } result)
            return planes.TryGetValue(result, out var plane)
                ? plane
                : throw KompasApi7Adapter.Failure(
                    "FEATURE_RESULT_UNAVAILABLE", "feature", $"No plane named {result} has been built.");
        return part.DefaultObject(BasePlaneConstant(feature.BasePlaneName));
    }

    private string BuildExtrusion(ExtrudeFeaturePlan feature, string operationCode)
    {
        object? topPartObject = null;
        object? sketchObject = null;
        object? extrusionObject = null;
        try
        {
            topPartObject = ((IKompasDocument3D)document).TopPart;
            var part = (IPart7)topPartObject;
            sketchObject = ((ISketchs)part.Sketchs).Add();
            var sketch = (ISketch)sketchObject;
            sketch.Plane = ResolvePlane(feature.Sketch.Plane, part);
            Draw(sketch, feature.Sketch);

            extrusionObject = ((IExtrusions)part.Extrusions).Add(
                feature.IsCut ? CutExtrusion : BaseExtrusion);
            var extrusion = (IExtrusion)extrusionObject;
            if (feature.IsCut) ((IExtrusion1)extrusionObject).OperationResult = CutOperation;
            extrusion.Sketch = sketchObject;
            // A cut sketched on the base plane enters the +Z body from below,
            // which is dtReverse; everything else grows along its own normal.
            extrusion.Direction = feature.IsCut && feature.Sketch.Plane is BasePlanePlan ? 1 : 0;
            var depth = feature.DepthMm > 0 ? feature.DepthMm : baseDepthMm;
            if (!extrusion.SetSideParameters(!feature.IsCut, 0, depth, 0, false, null) ||
                !extrusion.Update() ||
                !part.RebuildModel(false))
                throw KompasApi7Adapter.Failure(
                    feature.IsCut ? "FEATURE_BUILD_FAILED" : "FEATURE_BUILD_FAILED",
                    "feature",
                    $"KOMPAS did not build {feature.Id}.");
            return operationCode;
        }
        finally
        {
            KompasApi7Adapter.Release(extrusionObject);
            KompasApi7Adapter.Release(sketchObject);
            KompasApi7Adapter.Release(topPartObject);
        }
    }

    private object ResolvePlane(SketchPlanePlan plane, IPart7 part) => plane switch
    {
        BasePlanePlan basePlane => part.DefaultObject(BasePlaneConstant(basePlane.Name)),
        DatumPlanePlan datum => planes.TryGetValue(datum.ResultId, out var built)
            ? built
            : throw KompasApi7Adapter.Failure(
                "FEATURE_RESULT_UNAVAILABLE", "sketch", $"No plane named {datum.ResultId} has been built."),
        FacePlanePlan face => KompasFaceBridge.Resolve(document, part, face.Selector),
        _ => throw KompasApi7Adapter.Failure(
            "UNSUPPORTED_SKETCH_PLANE", "sketch", "The sketch names a plane this adapter cannot resolve.")
    };

    private static int BasePlaneConstant(string? name) => name switch
    {
        "XY" or null => PlaneXY,
        "XZ" => PlaneXZ,
        "YZ" => PlaneYZ,
        _ => throw KompasApi7Adapter.Failure(
            "UNSUPPORTED_PLANE", "sketch", $"{name} is not a base plane.")
    };

    // --- drawing -----------------------------------------------------------

    private static void Draw(ISketch sketch, SketchPlan plan)
    {
        object? fragmentObject = null;
        try
        {
            fragmentObject = sketch.BeginEdit();
            var fragment = (IFragmentDocument)fragmentObject;
            var manager = (IViewsAndLayersManager)fragment.ViewsAndLayersManager;
            var view = (IView)((IViews)manager.Views).ActiveView;

            DrawContour(view, plan.Outer);
            foreach (var island in plan.Inner) DrawContour(view, island);
            // Construction geometry is drawn last and never as a profile. It
            // exists so a later milestone has something to constrain against;
            // KOMPAS ignores it when deciding what to extrude only because it
            // is not a closed contour of its own.
            foreach (var entity in plan.Construction) DrawConstruction(view, entity);

            if (!sketch.EndEdit())
                throw KompasApi7Adapter.Failure(
                    "SKETCH_INVALID", "sketch", "KOMPAS did not close sketch editing.");
        }
        finally { KompasApi7Adapter.Release(fragmentObject); }
    }

    private static void DrawContour(IView view, ContourPlan contour)
    {
        switch (contour)
        {
            case CircleContourPlan circle:
                DrawCircle(view, circle.Center, circle.Radius);
                return;
            case PathContourPlan path:
                foreach (var segment in path.Segments) DrawSegment(view, segment);
                return;
            default:
                throw KompasApi7Adapter.Failure(
                    "UNSUPPORTED_CONTOUR", "sketch", "The sketch contains a contour kind this adapter cannot draw.");
        }
    }

    private static void DrawConstruction(IView view, ConstructionEntityPlan entity)
    {
        if (entity.At is { } point)
        {
            var pointObject = ((IPoints)view.Points).Add();
            try
            {
                var drawn = (IPoint)pointObject;
                drawn.X = point.X;
                drawn.Y = point.Y;
                if (!drawn.Update())
                    throw KompasApi7Adapter.Failure(
                        "SKETCH_INVALID", "sketch", $"KOMPAS rejected construction point {entity.Id}.");
            }
            finally { KompasApi7Adapter.Release(pointObject); }
            return;
        }
        if (entity.Shape is { } shape) DrawContour(view, shape);
    }

    private static void DrawSegment(IView view, SketchSegment segment)
    {
        switch (segment)
        {
            case LineSegmentPlan line:
            {
                var lineObject = ((ILineSegments)view.LineSegments).Add();
                try
                {
                    var drawn = (ILineSegment)lineObject;
                    drawn.X1 = line.From.X; drawn.Y1 = line.From.Y;
                    drawn.X2 = line.To.X; drawn.Y2 = line.To.Y;
                    if (!drawn.Update())
                        throw KompasApi7Adapter.Failure(
                            "SKETCH_INVALID", "sketch", "KOMPAS rejected a line segment.");
                }
                finally { KompasApi7Adapter.Release(lineObject); }
                return;
            }
            case ArcSegmentPlan arc:
            {
                var arcObject = ((IArcs)view.Arcs).Add();
                try
                {
                    // Centre, radius and two angles. The endpoint properties
                    // exist but leave Update() returning false with the radius
                    // at zero — measured on KOMPAS v22, see TASK-POSTMVP-006.
                    var drawn = (IArc)arcObject;
                    drawn.Xc = arc.Center.X;
                    drawn.Yc = arc.Center.Y;
                    drawn.Radius = arc.StartRadius;
                    drawn.Angle1 = arc.CounterClockwise ? arc.StartAngleDegrees : arc.EndAngleDegrees;
                    drawn.Angle2 = arc.CounterClockwise ? arc.EndAngleDegrees : arc.StartAngleDegrees;
                    drawn.Direction = 1;
                    if (!drawn.Update())
                        throw KompasApi7Adapter.Failure(
                            "SKETCH_INVALID", "sketch", "KOMPAS rejected an arc.");
                }
                finally { KompasApi7Adapter.Release(arcObject); }
                return;
            }
            default:
                throw KompasApi7Adapter.Failure(
                    "UNSUPPORTED_SEGMENT", "sketch", "The sketch contains a segment kind this adapter cannot draw.");
        }
    }

    private static void DrawCircle(IView view, Point2 center, double radius)
    {
        var circleObject = ((ICircles)view.Circles).Add();
        try
        {
            var drawn = (ICircle)circleObject;
            drawn.Xc = center.X;
            drawn.Yc = center.Y;
            drawn.Radius = radius;
            if (!drawn.Update())
                throw KompasApi7Adapter.Failure(
                    "SKETCH_INVALID", "sketch", "KOMPAS rejected a circle.");
        }
        finally { KompasApi7Adapter.Release(circleObject); }
    }

    public void Dispose()
    {
        foreach (var plane in owned) KompasApi7Adapter.Release(plane);
        owned.Clear();
        planes.Clear();
    }
}
