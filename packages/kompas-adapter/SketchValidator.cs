namespace CadAi.KompasAdapter;

/// <summary>
/// The gate a sketch passes before any COM object exists.
/// </summary>
/// <remarks>
/// Everything here is geometry, which is why it lives on this side of the
/// boundary rather than in the Python contracts: it needs the parameters
/// resolved, and the AI path hands its CAD-IR straight to this adapter, so a
/// check that only existed on the API would not protect the machine that runs
/// KOMPAS.
///
/// Nothing is repaired. A gap smaller than the tolerance is not closed, a
/// self-intersection is not trimmed, and a reversed island is not flipped —
/// each of those is a guess about what the document meant, and a guess that
/// builds is worse than a refusal that explains. Auto-repair is explicitly out
/// of scope for this milestone.
/// </remarks>
public static class SketchValidator
{
    private const double Tolerance = SketchGeometry.PointToleranceMm;
    private const double Tessellation = SketchGeometry.TessellationToleranceMm;

    /// <summary>Check a sketch, or throw the first thing wrong with it.</summary>
    public static void Validate(SketchPlan sketch)
    {
        Check(sketch.Outer, "outer contour");
        for (var index = 0; index < sketch.Inner.Count; index++)
            Check(sketch.Inner[index], $"island {index + 1}");

        var outer = sketch.Outer.Tessellate(Tessellation);
        for (var index = 0; index < sketch.Inner.Count; index++)
        {
            var island = sketch.Inner[index].Tessellate(Tessellation);
            var label = $"island {index + 1}";
            if (Crosses(outer, island))
                throw Invalid("SKETCH_CONTOURS_INTERSECT", $"The {label} crosses the outer contour.");
            if (!Inside(outer, island))
                throw Invalid("SKETCH_ISLAND_OUTSIDE_PROFILE",
                    $"The {label} is not inside the outer contour.");
        }

        for (var first = 0; first < sketch.Inner.Count; first++)
        for (var second = first + 1; second < sketch.Inner.Count; second++)
        {
            var left = sketch.Inner[first].Tessellate(Tessellation);
            var right = sketch.Inner[second].Tessellate(Tessellation);
            var labels = $"islands {first + 1} and {second + 1}";
            if (Crosses(left, right))
                throw Invalid("SKETCH_CONTOURS_INTERSECT", $"{Capitalise(labels)} cross each other.");
            // An island inside an island is nesting two levels deep. The
            // document cannot express it, so finding one geometrically means
            // two islands were written that happen to contain one another.
            if (Inside(left, right) || Inside(right, left))
                throw Invalid("SKETCH_ISLAND_NESTED", $"{Capitalise(labels)} are nested.");
        }
    }

    private static void Check(ContourPlan contour, string label)
    {
        switch (contour)
        {
            case CircleContourPlan circle:
                if (!(circle.Radius > Tolerance))
                    throw Invalid("SKETCH_SEGMENT_DEGENERATE", $"The {label} is a circle of no radius.");
                return;
            case PathContourPlan path:
                CheckPath(path, label);
                return;
            default:
                throw Invalid("SKETCH_UNSUPPORTED_CONTOUR", $"The {label} is of an unsupported kind.");
        }
    }

    private static void CheckPath(PathContourPlan path, string label)
    {
        var segments = path.Segments;
        if (segments.Count < 2)
            throw Invalid("SKETCH_CONTOUR_OPEN", $"The {label} has too few segments to bound a region.");

        for (var index = 0; index < segments.Count; index++)
        {
            var segment = segments[index];
            var position = $"{label}, segment {index + 1}";
            if (segment.Start.DistanceTo(segment.End) <= Tolerance && segment is LineSegmentPlan)
                throw Invalid("SKETCH_SEGMENT_DEGENERATE", $"The {position} has zero length.");
            if (segment is ArcSegmentPlan arc)
            {
                if (!(arc.StartRadius > Tolerance))
                    throw Invalid("SKETCH_SEGMENT_DEGENERATE", $"The {position} is an arc of no radius.");
                if (Math.Abs(arc.StartRadius - arc.EndRadius) > 1e-4 * Math.Max(arc.StartRadius, 1))
                    // Both endpoints have to be on the same circle, or the
                    // centre does not describe the arc that was meant.
                    throw Invalid("SKETCH_ARC_INCONSISTENT",
                        $"The {position} has endpoints at different distances from its centre " +
                        $"({arc.StartRadius:F4} and {arc.EndRadius:F4} mm).");
            }

            // Consecutive segments must meet, and the last must meet the first.
            var next = segments[(index + 1) % segments.Count];
            var gap = segment.End.DistanceTo(next.Start);
            if (gap > Tolerance)
                throw Invalid("SKETCH_CONTOUR_OPEN",
                    index == segments.Count - 1
                        ? $"The {label} does not close: its last segment ends {gap:F4} mm from where " +
                          "its first begins."
                        : $"The {position} ends {gap:F4} mm from where segment {index + 2} begins.");
        }

        for (var first = 0; first < segments.Count; first++)
        for (var second = first + 1; second < segments.Count; second++)
        {
            if (SameEndpoints(segments[first], segments[second]))
                throw Invalid("SKETCH_SEGMENT_DUPLICATE",
                    $"The {label} draws segments {first + 1} and {second + 1} between the same points.");
        }

        if (SelfIntersects(path.Tessellate(Tessellation)))
            throw Invalid("SKETCH_SELF_INTERSECTION", $"The {label} crosses itself.");
    }

    private static bool SameEndpoints(SketchSegment left, SketchSegment right) =>
        (left.Start.DistanceTo(right.Start) <= Tolerance && left.End.DistanceTo(right.End) <= Tolerance) ||
        (left.Start.DistanceTo(right.End) <= Tolerance && left.End.DistanceTo(right.Start) <= Tolerance);

    // --- polygon predicates ------------------------------------------------

    /// <remarks>
    /// Adjacent edges share a vertex by construction, so they are skipped: a
    /// shared endpoint is not a crossing. Everything else that touches is one.
    /// </remarks>
    private static bool SelfIntersects(IReadOnlyList<Point2> polygon)
    {
        var count = polygon.Count;
        for (var first = 0; first < count; first++)
        for (var second = first + 1; second < count; second++)
        {
            if (second == first + 1 || (first == 0 && second == count - 1)) continue;
            if (SegmentsCross(
                    polygon[first], polygon[(first + 1) % count],
                    polygon[second], polygon[(second + 1) % count]))
                return true;
        }
        return false;
    }

    private static bool Crosses(IReadOnlyList<Point2> left, IReadOnlyList<Point2> right)
    {
        for (var first = 0; first < left.Count; first++)
        for (var second = 0; second < right.Count; second++)
        {
            if (SegmentsCross(
                    left[first], left[(first + 1) % left.Count],
                    right[second], right[(second + 1) % right.Count]))
                return true;
        }
        return false;
    }

    /// <summary>Is every vertex of `inner` within `outer`?</summary>
    private static bool Inside(IReadOnlyList<Point2> outer, IReadOnlyList<Point2> inner) =>
        inner.All(point => Contains(outer, point));

    private static bool Contains(IReadOnlyList<Point2> polygon, Point2 point)
    {
        var inside = false;
        for (var index = 0; index < polygon.Count; index++)
        {
            var current = polygon[index];
            var previous = polygon[(index + polygon.Count - 1) % polygon.Count];
            if ((current.Y > point.Y) != (previous.Y > point.Y))
            {
                var crossingX = current.X +
                                (point.Y - current.Y) / (previous.Y - current.Y) * (previous.X - current.X);
                if (point.X < crossingX) inside = !inside;
            }
        }
        return inside;
    }

    private static bool SegmentsCross(Point2 a1, Point2 a2, Point2 b1, Point2 b2)
    {
        var d1 = Cross(b1, b2, a1);
        var d2 = Cross(b1, b2, a2);
        var d3 = Cross(a1, a2, b1);
        var d4 = Cross(a1, a2, b2);
        if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
            ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0)))
            return true;
        // Collinear overlap: two edges lying along each other is a crossing
        // even though no orientation test changes sign.
        return (Math.Abs(d1) <= Tolerance && OnSegment(b1, b2, a1)) ||
               (Math.Abs(d2) <= Tolerance && OnSegment(b1, b2, a2)) ||
               (Math.Abs(d3) <= Tolerance && OnSegment(a1, a2, b1)) ||
               (Math.Abs(d4) <= Tolerance && OnSegment(a1, a2, b2));
    }

    private static double Cross(Point2 from, Point2 to, Point2 point) =>
        (to.X - from.X) * (point.Y - from.Y) - (to.Y - from.Y) * (point.X - from.X);

    private static bool OnSegment(Point2 from, Point2 to, Point2 point) =>
        point.X >= Math.Min(from.X, to.X) - Tolerance &&
        point.X <= Math.Max(from.X, to.X) + Tolerance &&
        point.Y >= Math.Min(from.Y, to.Y) - Tolerance &&
        point.Y <= Math.Max(from.Y, to.Y) + Tolerance &&
        // A shared endpoint is contact, not a crossing.
        point.DistanceTo(from) > Tolerance && point.DistanceTo(to) > Tolerance;

    private static string Capitalise(string value) =>
        value.Length == 0 ? value : char.ToUpperInvariant(value[0]) + value[1..];

    private static CadAdapterException Invalid(string code, string message) =>
        new(code, "sketch", message);
}
