namespace CadAi.CadEngine;

/// <summary>
/// Turns a selector into the faces or edges it names.
/// </summary>
/// <remarks>
/// Pure: it takes measured descriptors, not COM objects, so the whole matching
/// layer is testable on a machine without KOMPAS. Reading the topology is the
/// other half of the job and lives in <see cref="KompasTopologyReader"/>.
///
/// Predicates filter; they never score. There is no closest match and no
/// confidence threshold, because a selector that quietly picks one of two
/// candidates produces a plausible-looking wrong part — the failure mode this
/// whole layer exists to remove. When the predicates do not narrow to the
/// declared cardinality the resolution fails and carries a trace saying where
/// the candidates went.
/// </remarks>
public static class SelectorResolver
{
    /// <summary>
    /// How close two positions must be to count as the same extreme.
    /// </summary>
    /// <remarks>
    /// Two faces at z = 10 and z = 10.0000000001 are the same top face; an
    /// exact comparison would make which one wins depend on floating-point
    /// noise from the modelling kernel.
    /// </remarks>
    private const double ExtremeToleranceMm = 1e-6;

    public static SelectorResolution ResolveFaces(
        GeometrySelector selector,
        IReadOnlyList<FaceDescriptor> faces)
    {
        if (selector.Kind != SelectorKind.Face || selector.Face is null)
            throw new SelectorException(
                "SELECTOR_RESULT_KIND_MISMATCH", "A face resolver was given a non-face selector.");

        var steps = new List<ResolutionStep>();
        var candidates = faces.ToList();
        var initial = candidates.Count;
        var where = selector.Face;

        candidates = Filter(candidates, steps, $"surface_type={Lower(where.SurfaceType)}",
            where.SurfaceType is null, face => face.SurfaceType == where.SurfaceType);

        candidates = Filter(candidates, steps, $"normal {Describe(where.Normal)}",
            where.Normal is null, face => MatchesNormal(face.Normal, where.Normal!));

        candidates = Filter(candidates, steps, $"radius={Describe(where.RadiusMm)}",
            where.RadiusMm is null, face => face.RadiusMm is { } radius && where.RadiusMm!.Matches(radius));

        candidates = Filter(candidates, steps, $"area={Describe(where.AreaMm2)}",
            where.AreaMm2 is null, face => face.AreaMm2 is { } area && where.AreaMm2!.Matches(area));

        candidates = Filter(candidates, steps, $"adjacent {Describe(where.Adjacent)}",
            where.Adjacent is null,
            face => MatchesAdjacency(face.AdjacentSurfaceTypes, face.AdjacentFaceCount, where.Adjacent!));

        candidates = ApplyPosition(candidates, steps, where.Position,
            face => face.Bounds);

        return Conclude(selector, initial, steps, candidates.Select(face => face.Index).ToList());
    }

    public static SelectorResolution ResolveEdges(
        GeometrySelector selector,
        IReadOnlyList<EdgeDescriptor> edges)
    {
        if (selector.Kind != SelectorKind.Edge || selector.Edge is null)
            throw new SelectorException(
                "SELECTOR_RESULT_KIND_MISMATCH", "An edge resolver was given a non-edge selector.");

        var steps = new List<ResolutionStep>();
        var candidates = edges.ToList();
        var initial = candidates.Count;
        var where = selector.Edge;

        candidates = Filter(candidates, steps, $"curve_type={Lower(where.CurveType)}",
            where.CurveType is null, edge => edge.CurveType == where.CurveType);

        candidates = Filter(candidates, steps, $"radius={Describe(where.RadiusMm)}",
            where.RadiusMm is null, edge => edge.RadiusMm is { } radius && where.RadiusMm!.Matches(radius));

        candidates = Filter(candidates, steps, $"length={Describe(where.LengthMm)}",
            where.LengthMm is null, edge => edge.LengthMm is { } length && where.LengthMm!.Matches(length));

        candidates = Filter(candidates, steps, $"direction parallel to {Lower(where.DirectionParallelTo)}",
            where.DirectionParallelTo is null,
            edge => edge.Direction is { } direction && IsParallel(direction, where.DirectionParallelTo!.Value));

        candidates = Filter(candidates, steps, $"convexity={Lower(where.Convexity)}",
            where.Convexity is null, edge => edge.Convexity == where.Convexity);

        candidates = Filter(candidates, steps, $"adjacent {Describe(where.Adjacent)}",
            where.Adjacent is null,
            edge => MatchesAdjacency(edge.AdjacentSurfaceTypes, edge.AdjacentSurfaceTypes?.Count ?? 0, where.Adjacent!));

        candidates = ApplyPosition(candidates, steps, where.Position, edge => edge.Bounds);

        return Conclude(selector, initial, steps, candidates.Select(edge => edge.Index).ToList());
    }

    private static List<T> Filter<T>(
        List<T> candidates,
        List<ResolutionStep> steps,
        string description,
        bool skip,
        Func<T, bool> predicate)
    {
        if (skip) return candidates;
        var before = candidates.Count;
        var kept = candidates.Where(predicate).ToList();
        steps.Add(new ResolutionStep(description, before, kept.Count));
        return kept;
    }

    /// <summary>
    /// Position is applied last, and the extreme is applied after the centre.
    /// </summary>
    /// <remarks>
    /// An extreme is a ranking over whatever survived, not a test on a single
    /// candidate: "furthest along Z" of a set that still contains both end
    /// faces means something different from "furthest along Z" of all faces.
    /// Applying it before the cheaper filters would silently answer a
    /// different question.
    /// </remarks>
    private static List<T> ApplyPosition<T>(
        List<T> candidates,
        List<ResolutionStep> steps,
        PositionPredicate? position,
        Func<T, BoundingBox> bounds)
    {
        if (position is null) return candidates;

        if (position.CenterAlong is { } centerAxis && position.CenterValueMm is { } expected)
        {
            candidates = Filter(candidates, steps,
                $"centre on {Lower(centerAxis)} = {Describe(expected)}", false,
                item => expected.Matches(bounds(item).CenterAlong(centerAxis)));
        }

        if (position.ExtremeAlong is { } extremeAxis && position.Extreme is { } extreme)
        {
            var before = candidates.Count;
            if (before > 0)
            {
                var measure = extreme == ExtremeKind.Maximum
                    ? (Func<T, double>)(item => bounds(item).MaxAlong(extremeAxis))
                    : item => bounds(item).MinAlong(extremeAxis);
                var best = extreme == ExtremeKind.Maximum
                    ? candidates.Max(measure)
                    : candidates.Min(measure);
                candidates = candidates
                    .Where(item => Math.Abs(measure(item) - best) <= ExtremeToleranceMm)
                    .ToList();
            }
            steps.Add(new ResolutionStep(
                $"{Lower(extreme)} position on {Lower(extremeAxis)}", before, candidates.Count));
        }

        return candidates;
    }

    private static SelectorResolution Conclude(
        GeometrySelector selector,
        int initial,
        List<ResolutionStep> steps,
        List<int> matched)
    {
        var satisfied = selector.Cardinality.IsSatisfiedBy(matched.Count);
        return new SelectorResolution(
            selector.Id,
            selector.Kind == SelectorKind.Face ? "face" : "edge",
            initial,
            steps,
            matched.Count,
            satisfied,
            satisfied ? null : selector.Cardinality.FailureCode(matched.Count),
            matched);
    }

    private static bool MatchesNormal(Vector3? normal, NormalPredicate predicate)
    {
        if (normal is not { } vector || vector.Length < 1e-9) return false;
        if (predicate.ParallelTo is { } parallel)
        {
            if (!IsParallel(vector, parallel)) return false;
            if (predicate.Direction is { } direction)
            {
                var component = vector.Along(parallel);
                return direction == AxisDirection.Positive ? component > 0 : component < 0;
            }
            return true;
        }
        // Perpendicular to an axis means the component along it is zero.
        return predicate.PerpendicularTo is { } perpendicular &&
               Math.Abs(vector.Along(perpendicular)) <= AngleTolerance * vector.Length;
    }

    /// <summary>
    /// A normal within about 0.06 degrees of the axis counts as along it.
    /// </summary>
    /// <remarks>
    /// Modelling kernels do not produce exactly (0, 0, 1); a face built as
    /// planar comes back with a normal a few ulps off. Requiring exactness
    /// would make every selector fail on real geometry.
    /// </remarks>
    private const double AngleTolerance = 1e-3;

    private static bool IsParallel(Vector3 vector, SelectorAxis axis)
    {
        var length = vector.Length;
        if (length < 1e-9) return false;
        var along = Math.Abs(vector.Along(axis));
        var others = Math.Sqrt(Math.Max(length * length - along * along, 0));
        return others <= AngleTolerance * length;
    }

    private static bool MatchesAdjacency(
        IReadOnlyList<SurfaceType>? adjacent,
        int adjacentCount,
        AdjacencyPredicate predicate)
    {
        if (adjacent is null) return false;
        if (predicate.FaceCount is { } expected && adjacentCount != expected) return false;
        return predicate.ContainsSurfaceTypes.All(adjacent.Contains);
    }

    // Takes object? so it accepts both an enum and a nullable enum; the
    // generic form cannot infer T from an already-unwrapped value.
    private static string Lower(object? value) =>
        value is null ? "any" : value.ToString()!.ToLowerInvariant();

    private static string Describe(Measurement? measurement) =>
        measurement is null ? "any" : $"{measurement.Value}±{measurement.Tolerance}";

    private static string Describe(NormalPredicate? normal)
    {
        if (normal is null) return "any";
        if (normal.ParallelTo is { } parallel)
        {
            var sense = normal.Direction is { } direction
                ? (direction == AxisDirection.Positive ? "+" : "-")
                : "";
            return $"parallel to {sense}{Lower(parallel)}";
        }
        return $"perpendicular to {Lower(normal.PerpendicularTo)}";
    }

    private static string Describe(AdjacencyPredicate? adjacency)
    {
        if (adjacency is null) return "any";
        var types = string.Join("+", adjacency.ContainsSurfaceTypes.Select(item => item.ToString().ToLowerInvariant()));
        return adjacency.FaceCount is { } count ? $"{types} across {count} faces" : types;
    }
}
