namespace CadAi.CadEngine;

/// <summary>
/// A sketch with every parameter already resolved to a number.
/// </summary>
/// <remarks>
/// The CAD-IR side of the boundary allows a coordinate to be a named
/// parameter, because that is what keeps a part parametric. Nothing below this
/// point does: the parser substitutes, and everything after it works on
/// numbers, so no geometric check has to carry a parameter table around.
///
/// Shapes are expanded here too. A slot is two lines and two arcs, a hexagon
/// is six lines, and the adapter never learns what a slot is — which is the
/// only reason there is one implementation of the expansion rather than one in
/// the validator and another in the builder.
/// </remarks>
public readonly record struct Point2(double X, double Y)
{
    public double DistanceTo(Point2 other) => Math.Sqrt(Squared(X - other.X) + Squared(Y - other.Y));

    private static double Squared(double value) => value * value;
}

public abstract record SketchSegment
{
    public abstract Point2 Start { get; }
    public abstract Point2 End { get; }

    /// <summary>The sketch-local name, when the document gave one.</summary>
    public string? Id { get; init; }
}

public sealed record LineSegmentPlan(Point2 From, Point2 To) : SketchSegment
{
    public override Point2 Start => From;
    public override Point2 End => To;
    public double Length => From.DistanceTo(To);
}

public sealed record ArcSegmentPlan(Point2 From, Point2 To, Point2 Center, bool CounterClockwise)
    : SketchSegment
{
    public override Point2 Start => From;
    public override Point2 End => To;

    public double StartRadius => Center.DistanceTo(From);
    public double EndRadius => Center.DistanceTo(To);

    /// <summary>Degrees, measured the way KOMPAS measures them.</summary>
    public double StartAngleDegrees => Angle(From);
    public double EndAngleDegrees => Angle(To);

    private double Angle(Point2 point) =>
        Math.Atan2(point.Y - Center.Y, point.X - Center.X) * 180 / Math.PI;

    /// <summary>How far round the arc goes, in degrees, always positive.</summary>
    public double SweepDegrees
    {
        get
        {
            var sweep = CounterClockwise
                ? EndAngleDegrees - StartAngleDegrees
                : StartAngleDegrees - EndAngleDegrees;
            while (sweep <= 0) sweep += 360;
            while (sweep > 360) sweep -= 360;
            return sweep;
        }
    }
}

public abstract record ContourPlan
{
    /// <summary>The sketch-local name, when the document gave one.</summary>
    public string? Id { get; init; }

    /// <summary>
    /// The contour as a closed polygon, for the checks that need one.
    /// </summary>
    /// <remarks>
    /// Arcs are tessellated. Deliberately an approximation: an exact arc–arc
    /// intersection test is a disproportionate amount of numerically delicate
    /// code for a tolerance nothing else in this pipeline is tighter than.
    /// </remarks>
    public abstract IReadOnlyList<Point2> Tessellate(double toleranceMm);

    /// <summary>Signed area of the tessellation; positive when anticlockwise.</summary>
    public double SignedArea(double toleranceMm)
    {
        var points = Tessellate(toleranceMm);
        var total = 0.0;
        for (var index = 0; index < points.Count; index++)
        {
            var current = points[index];
            var next = points[(index + 1) % points.Count];
            total += current.X * next.Y - next.X * current.Y;
        }
        return total / 2;
    }
}

/// <summary>A full circle, kept whole because KOMPAS draws one natively.</summary>
public sealed record CircleContourPlan(Point2 Center, double Radius) : ContourPlan
{
    public override IReadOnlyList<Point2> Tessellate(double toleranceMm)
    {
        var steps = SketchGeometry.ArcSteps(Radius, 360, toleranceMm);
        var points = new List<Point2>(steps);
        for (var step = 0; step < steps; step++)
        {
            var angle = 2 * Math.PI * step / steps;
            points.Add(new Point2(Center.X + Radius * Math.Cos(angle), Center.Y + Radius * Math.Sin(angle)));
        }
        return points;
    }
}

public sealed record PathContourPlan(IReadOnlyList<SketchSegment> Segments) : ContourPlan
{
    public override IReadOnlyList<Point2> Tessellate(double toleranceMm)
    {
        var points = new List<Point2>();
        foreach (var segment in Segments)
        {
            // Each segment contributes its start and its interior; the next
            // segment contributes the shared endpoint, so nothing is doubled.
            points.Add(segment.Start);
            if (segment is ArcSegmentPlan arc) points.AddRange(SketchGeometry.ArcInterior(arc, toleranceMm));
        }
        return points;
    }
}

public abstract record SketchPlanePlan;

public sealed record BasePlanePlan(string Name) : SketchPlanePlan;

public sealed record DatumPlanePlan(string ResultId) : SketchPlanePlan;

/// <summary>
/// A plane on a face the build has to find, described by what the face means.
/// </summary>
/// <remarks>
/// Carries the selector, not a face index. Resolution happens against the
/// model as it then is, and the answer is verified against what the selector
/// measured before anything is sketched on it — see ADR-020.
/// </remarks>
public sealed record FacePlanePlan(GeometrySelector Selector) : SketchPlanePlan;

public sealed record ConstructionEntityPlan(string Id, string Kind, ContourPlan? Shape, Point2? At);

public sealed record SketchPlan(
    string Id,
    SketchPlanePlan Plane,
    ContourPlan Outer,
    IReadOnlyList<ContourPlan> Inner,
    IReadOnlyList<ConstructionEntityPlan> Construction,
    IReadOnlyList<SketchConstraintPlan>? Constraints = null,
    IReadOnlyList<DrivingDimensionPlan>? Dimensions = null)
{
    public IReadOnlyList<SketchConstraintPlan> Declared => Constraints ?? [];
    public IReadOnlyList<DrivingDimensionPlan> Measured => Dimensions ?? [];

    /// <summary>
    /// Everything in this sketch a constraint can name, flattened.
    /// </summary>
    /// <remarks>
    /// Named entities only. An unnamed segment cannot be constrained and does not
    /// need to appear, and leaving it out keeps the degree-of-freedom count
    /// honest about what the constraints are actually holding.
    /// </remarks>
    public IReadOnlyList<ConstrainedEntity> NamedEntities()
    {
        var entities = new List<ConstrainedEntity>();
        foreach (var contour in new[] { Outer }.Concat(Inner))
            Collect(contour, entities);
        foreach (var entity in Construction)
        {
            if (entity.At is { } point)
                entities.Add(new ConstrainedEntity(entity.Id, "point", point, point));
            else if (entity.Shape is { } shape)
                Collect(shape, entities, entity.Id);
        }
        return entities;
    }

    private static void Collect(ContourPlan contour, List<ConstrainedEntity> into, string? id = null)
    {
        switch (contour)
        {
            case CircleContourPlan circle:
                if ((id ?? circle.Id) is { } circleId)
                    into.Add(new ConstrainedEntity(
                        circleId, "circle", circle.Center, circle.Center, circle.Center, circle.Radius));
                return;
            case PathContourPlan path:
                foreach (var segment in path.Segments)
                {
                    // A construction line or arc is one segment carrying the
                    // entity's own name, so the override applies here too — and
                    // an axis of symmetry is exactly such a line.
                    var segmentId = path.Segments.Count == 1 ? id ?? segment.Id : segment.Id;
                    if (segmentId is null) continue;
                    into.Add(segment switch
                    {
                        ArcSegmentPlan arc => new ConstrainedEntity(
                            segmentId, "arc", arc.From, arc.To, arc.Center, arc.StartRadius),
                        _ => new ConstrainedEntity(segmentId, "line", segment.Start, segment.End)
                    });
                }
                return;
        }
    }
}

public static class SketchGeometry
{
    /// <summary>
    /// How far a tessellated chord may sit from the true arc.
    /// </summary>
    /// <remarks>
    /// A hundredth of a millimetre: finer than any tolerance a drawing states,
    /// and coarse enough that a 3 mm fillet is twelve segments rather than
    /// twelve hundred.
    /// </remarks>
    public const double TessellationToleranceMm = 0.01;

    /// <summary>
    /// How close two coordinates must be to be the same point.
    /// </summary>
    /// <remarks>
    /// A nanometre. Coordinates arrive written out explicitly, so two points
    /// meant to coincide are written identically and only floating-point
    /// arithmetic separates them. Anything looser would start closing gaps the
    /// document did not intend to have — which this milestone does not do.
    /// </remarks>
    public const double PointToleranceMm = 1e-6;

    /// <summary>
    /// The tessellation is also capped relative to the radius.
    /// </summary>
    /// <remarks>
    /// An absolute sagitta alone is too coarse for small geometry: a hundredth
    /// of a millimetre on a Ø1 hole is a sixteen-sided polygon holding 97% of
    /// the circle's area, and the containment test would then disagree with the
    /// document about whether something sits inside it. A thousandth of the
    /// radius keeps every arc within 0.1% whatever its size.
    /// </remarks>
    private const double RelativeToleranceFraction = 1e-3;

    internal static int ArcSteps(double radius, double sweepDegrees, double toleranceMm)
    {
        if (radius <= 0 || sweepDegrees <= 0) return 2;
        // Sagitta of one chord: r(1 - cos(theta/2)). Solve for theta.
        var effective = Math.Min(toleranceMm, radius * RelativeToleranceFraction);
        var ratio = Math.Clamp(1 - effective / radius, -1, 1);
        var maxStep = 2 * Math.Acos(ratio);
        if (maxStep <= 0) return 256;
        var steps = (int)Math.Ceiling(sweepDegrees * Math.PI / 180 / maxStep);
        return Math.Clamp(steps, 2, 256);
    }

    /// <summary>The arc's points between its endpoints, both excluded.</summary>
    internal static IEnumerable<Point2> ArcInterior(ArcSegmentPlan arc, double toleranceMm)
    {
        var radius = arc.StartRadius;
        var steps = ArcSteps(radius, arc.SweepDegrees, toleranceMm);
        var start = arc.StartAngleDegrees * Math.PI / 180;
        var sweep = arc.SweepDegrees * Math.PI / 180 * (arc.CounterClockwise ? 1 : -1);
        for (var step = 1; step < steps; step++)
        {
            var angle = start + sweep * step / steps;
            yield return new Point2(
                arc.Center.X + radius * Math.Cos(angle),
                arc.Center.Y + radius * Math.Sin(angle));
        }
    }

    // --- shape expansion ---------------------------------------------------

    public static ContourPlan Rectangle(Point2 center, double width, double height, double rotationDegrees)
    {
        var halfWidth = width / 2;
        var halfHeight = height / 2;
        Point2[] corners =
        [
            new(-halfWidth, -halfHeight), new(halfWidth, -halfHeight),
            new(halfWidth, halfHeight), new(-halfWidth, halfHeight)
        ];
        return Polygon(corners.Select(corner => Place(center, corner, rotationDegrees)).ToArray());
    }

    public static ContourPlan RegularPolygon(
        Point2 center, int sides, double circumradius, double rotationDegrees)
    {
        var corners = new Point2[sides];
        for (var index = 0; index < sides; index++)
        {
            var angle = (rotationDegrees + 360.0 * index / sides) * Math.PI / 180;
            corners[index] = new Point2(
                center.X + circumradius * Math.Cos(angle),
                center.Y + circumradius * Math.Sin(angle));
        }
        return Polygon(corners);
    }

    /// <summary>
    /// A slot: the straight flanks between two end-cap centres, capped by
    /// semicircles.
    /// </summary>
    /// <remarks>
    /// The flanks are offset perpendicular to the axis, so a slot whose ends
    /// are not axis-aligned works without a special case. A slot with
    /// coincident ends is a circle, and saying so here is better than emitting
    /// two zero-length lines for the validator to reject.
    /// </remarks>
    public static ContourPlan Slot(Point2 start, Point2 end, double radius)
    {
        var length = start.DistanceTo(end);
        if (length <= PointToleranceMm) return new CircleContourPlan(start, radius);
        var normalX = -(end.Y - start.Y) / length * radius;
        var normalY = (end.X - start.X) / length * radius;
        var startLeft = new Point2(start.X + normalX, start.Y + normalY);
        var endLeft = new Point2(end.X + normalX, end.Y + normalY);
        var endRight = new Point2(end.X - normalX, end.Y - normalY);
        var startRight = new Point2(start.X - normalX, start.Y - normalY);
        return new PathContourPlan([
            new LineSegmentPlan(startLeft, endLeft),
            new ArcSegmentPlan(endLeft, endRight, end, CounterClockwise: false),
            new LineSegmentPlan(endRight, startRight),
            new ArcSegmentPlan(startRight, startLeft, start, CounterClockwise: false)
        ]);
    }

    private static ContourPlan Polygon(IReadOnlyList<Point2> corners)
    {
        var segments = new List<SketchSegment>(corners.Count);
        for (var index = 0; index < corners.Count; index++)
            segments.Add(new LineSegmentPlan(corners[index], corners[(index + 1) % corners.Count]));
        return new PathContourPlan(segments);
    }

    /// <summary>Rotate an offset about the origin, then place it at a centre.</summary>
    private static Point2 Place(Point2 center, Point2 offset, double degrees)
    {
        if (degrees == 0) return new Point2(center.X + offset.X, center.Y + offset.Y);
        var radians = degrees * Math.PI / 180;
        var cos = Math.Cos(radians);
        var sin = Math.Sin(radians);
        return new Point2(
            center.X + offset.X * cos - offset.Y * sin,
            center.Y + offset.X * sin + offset.Y * cos);
    }
}
