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
internal sealed class KompasSketchBuilder(
    object document,
    double baseDepthMm,
    KompasApi5Session api5) : IDisposable
{
    private const int PlaneXY = 1; // o3d_planeXOY
    private const int PlaneXZ = 2; // o3d_planeXOZ
    private const int PlaneYZ = 3; // o3d_planeYOZ
    private const int BaseExtrusion = 24; // o3d_baseExtrusion: always a new body
    private const int BossExtrusion = 25; // adds to the body it stands on
    private const int CutExtrusion = 26; // o3d_cutExtrusion
    private const int OffsetPlane = 14; // IPlanes3D.Add, probed live; see TASK-POSTMVP-006
    private const int CutOperation = 2; // ksOperationCut

    private readonly Dictionary<string, object> planes = new(StringComparer.Ordinal);
    private readonly List<object> owned = [];
    private bool hasBody;

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

    /// <summary>What the last sketch's constraints did, for the ledger.</summary>
    public KompasConstraintApplier.Outcome? LastConstraintOutcome { get; private set; }

    private string BuildExtrusion(ExtrudeFeaturePlan feature, string operationCode)
    {
        KompasConstraintApplier.Outcome? constraintOutcome = null;
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
            constraintOutcome = Draw(sketch, feature.Sketch);

            // The first solid extrusion is the base; every later one is a boss.
            // A base extrusion always makes a *new* body, whatever the geometry
            // touches — measured on KOMPAS v22, where a second base extrusion
            // over the first left two bodies and only type 25 left one.
            extrusionObject = ((IExtrusions)part.Extrusions).Add(
                feature.IsCut ? CutExtrusion : hasBody ? BossExtrusion : BaseExtrusion);
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
            if (!feature.IsCut) hasBody = true;
            LastConstraintOutcome = constraintOutcome;
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
        FacePlanePlan face => KompasFaceBridge.Resolve(api5, part, face.Selector),
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

    private static KompasConstraintApplier.Outcome? Draw(ISketch sketch, SketchPlan plan)
    {
        object? fragmentObject = null;
        // Keyed by the sketch-local name the document gave, so a constraint can
        // find the COM object that was drawn for the entity it names.
        var drawn = new Dictionary<string, object>(StringComparer.Ordinal);
        try
        {
            fragmentObject = sketch.BeginEdit();
            var fragment = (IFragmentDocument)fragmentObject;
            var manager = (IViewsAndLayersManager)fragment.ViewsAndLayersManager;
            var view = (IView)((IViews)manager.Views).ActiveView;

            DrawContour(view, plan.Outer, KompasSketchStyles.Profile, drawn);
            foreach (var island in plan.Inner)
                DrawContour(view, island, KompasSketchStyles.Profile, drawn);
            // Construction geometry has to carry the construction style, not
            // just be drawn last. A centre line at profile style inside a
            // closed contour makes the extrusion fail outright — found by the
            // first real acceptance run, which is exactly what a centre line on
            // a drawing would have produced.
            foreach (var entity in plan.Construction)
                DrawConstruction(view, entity, KompasSketchStyles.Construction, drawn);

            KompasConstraintApplier.Outcome? outcome = null;
            if (plan.Declared.Count > 0 || plan.Measured.Count > 0)
            {
                outcome = KompasConstraintApplier.Apply(view, plan, drawn);
                // Every constraint was already checked true of these coordinates,
                // so a solver correction here means the document and the kernel
                // disagree about the part.
                KompasConstraintApplier.RequireGeometryUnmoved(plan, drawn);
            }

            if (!sketch.EndEdit())
                throw KompasApi7Adapter.Failure(
                    "SKETCH_INVALID", "sketch", "KOMPAS did not close sketch editing.");
            return outcome;
        }
        finally
        {
            foreach (var handle in drawn.Values) KompasApi7Adapter.Release(handle);
            KompasApi7Adapter.Release(fragmentObject);
        }
    }

    private static void DrawContour(
        IView view,
        ContourPlan contour,
        int style,
        Dictionary<string, object>? drawn = null,
        string? nameOverride = null)
    {
        switch (contour)
        {
            case CircleContourPlan circle:
                Remember(drawn, nameOverride ?? contour.Id,
                    DrawCircle(view, circle.Center, circle.Radius, style));
                return;
            case PathContourPlan path:
                foreach (var segment in path.Segments)
                    Remember(drawn, nameOverride ?? segment.Id, DrawSegment(view, segment, style));
                return;
            default:
                throw KompasApi7Adapter.Failure(
                    "UNSUPPORTED_CONTOUR", "sketch", "The sketch contains a contour kind this adapter cannot draw.");
        }
    }

    private static void DrawConstruction(
        IView view,
        ConstructionEntityPlan entity,
        int style,
        Dictionary<string, object>? collected = null)
    {
        if (entity.At is { } point)
        {
            var pointObject = ((IPoints)view.Points).Add();
            var drawn = (IPoint)pointObject;
            drawn.X = point.X;
            drawn.Y = point.Y;
            drawn.Style = style;
            if (!drawn.Update())
                throw KompasApi7Adapter.Failure(
                    "SKETCH_INVALID", "sketch", $"KOMPAS rejected construction point {entity.Id}.");
            Remember(collected, entity.Id, pointObject);
            return;
        }
        if (entity.Shape is { } shape) DrawContour(view, shape, style, collected, entity.Id);
    }

    /// <remarks>
    /// The handle is returned rather than released, because a constraint has to be
    /// able to name the entity it was drawn for. Whoever collected them releases
    /// them when the sketch is closed.
    /// </remarks>
    private static object DrawSegment(IView view, SketchSegment segment, int style)
    {
        switch (segment)
        {
            case LineSegmentPlan line:
            {
                var lineObject = ((ILineSegments)view.LineSegments).Add();
                var drawn = (ILineSegment)lineObject;
                drawn.X1 = line.From.X; drawn.Y1 = line.From.Y;
                drawn.X2 = line.To.X; drawn.Y2 = line.To.Y;
                drawn.Style = style;
                if (!drawn.Update())
                    throw KompasApi7Adapter.Failure(
                        "SKETCH_INVALID", "sketch", "KOMPAS rejected a line segment.");
                return lineObject;
            }
            case ArcSegmentPlan arc:
            {
                var arcObject = ((IArcs)view.Arcs).Add();
                // Centre, radius and two angles. The endpoint properties exist
                // but leave Update() returning false with the radius at zero —
                // measured on KOMPAS v22, see TASK-POSTMVP-006.
                var drawn = (IArc)arcObject;
                drawn.Xc = arc.Center.X;
                drawn.Yc = arc.Center.Y;
                drawn.Radius = arc.StartRadius;
                // Direction 0 sweeps anticlockwise from Angle1 to Angle2; 1 and
                // -1 both sweep clockwise. Measured by extruding a half-disc and
                // reading which side the material landed on. A clockwise arc is
                // therefore the same arc traversed anticlockwise from its end to
                // its start.
                drawn.Angle1 = arc.CounterClockwise ? arc.StartAngleDegrees : arc.EndAngleDegrees;
                drawn.Angle2 = arc.CounterClockwise ? arc.EndAngleDegrees : arc.StartAngleDegrees;
                drawn.Direction = 0;
                drawn.Style = style;
                if (!drawn.Update())
                    throw KompasApi7Adapter.Failure(
                        "SKETCH_INVALID", "sketch", "KOMPAS rejected an arc.");
                return arcObject;
            }
            default:
                throw KompasApi7Adapter.Failure(
                    "UNSUPPORTED_SEGMENT", "sketch", "The sketch contains a segment kind this adapter cannot draw.");
        }
    }

    /// <summary>Record a drawn handle under the name the document gave it.</summary>
    private static void Remember(Dictionary<string, object>? drawn, string? id, object handle)
    {
        if (drawn is not null && id is not null) drawn[id] = handle;
        else KompasApi7Adapter.Release(handle);
    }

    private static object DrawCircle(IView view, Point2 center, double radius, int style)
    {
        var circleObject = ((ICircles)view.Circles).Add();
        var drawn = (ICircle)circleObject;
        drawn.Xc = center.X;
        drawn.Yc = center.Y;
        drawn.Radius = radius;
        drawn.Style = style;
        if (!drawn.Update())
            throw KompasApi7Adapter.Failure(
                "SKETCH_INVALID", "sketch", "KOMPAS rejected a circle.");
        return circleObject;
    }

    public void Dispose()
    {
        foreach (var plane in owned) KompasApi7Adapter.Release(plane);
        owned.Clear();
        planes.Clear();
    }
}
