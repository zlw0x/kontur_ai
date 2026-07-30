using System.Text.Json;
using System.Text.Json.Serialization;

namespace CadAi.CadEngine;

public enum SelectorKind { Face, Edge }

public enum SurfaceType { Planar, Cylindrical, Conical, Spherical, Toroidal, Other }

public enum CurveType { Line, Circle, Arc, Ellipse, Spline, Other }

public enum SelectorAxis { X, Y, Z }

public enum AxisDirection { Positive, Negative }

public enum ExtremeKind { Minimum, Maximum }

public enum Convexity { Convex, Concave, Tangent }

public enum CardinalityKind { ExactlyOne, ZeroOrOne, OneOrMore, All, ExactlyN }

/// <summary>
/// A measured quantity and the tolerance it must be matched within.
/// </summary>
/// <remarks>
/// The tolerance is not optional. Comparing floating-point geometry for
/// equality is a bug waiting for the next rebuild, and a default would hide
/// that choice from whoever later wonders why a face stopped matching.
/// </remarks>
public sealed record Measurement(double Value, double Tolerance)
{
    public bool Matches(double measured) => Math.Abs(measured - Value) <= Tolerance;
}

public sealed record NormalPredicate(
    SelectorAxis? ParallelTo = null,
    SelectorAxis? PerpendicularTo = null,
    AxisDirection? Direction = null);

public sealed record PositionPredicate(
    SelectorAxis? ExtremeAlong = null,
    ExtremeKind? Extreme = null,
    SelectorAxis? CenterAlong = null,
    Measurement? CenterValueMm = null);

public sealed record AdjacencyPredicate(
    IReadOnlyList<SurfaceType> ContainsSurfaceTypes,
    int? FaceCount = null);

public sealed record FacePredicates(
    SurfaceType? SurfaceType = null,
    NormalPredicate? Normal = null,
    PositionPredicate? Position = null,
    Measurement? AreaMm2 = null,
    Measurement? RadiusMm = null,
    AdjacencyPredicate? Adjacent = null);

public sealed record EdgePredicates(
    CurveType? CurveType = null,
    Measurement? LengthMm = null,
    Measurement? RadiusMm = null,
    SelectorAxis? DirectionParallelTo = null,
    PositionPredicate? Position = null,
    AdjacencyPredicate? Adjacent = null,
    Convexity? Convexity = null);

public sealed record Cardinality(CardinalityKind Kind, int Value = 0)
{
    public bool IsSatisfiedBy(int count) => Kind switch
    {
        CardinalityKind.ExactlyOne => count == 1,
        CardinalityKind.ZeroOrOne => count <= 1,
        CardinalityKind.OneOrMore => count >= 1,
        CardinalityKind.All => true,
        CardinalityKind.ExactlyN => count == Value,
        _ => false
    };

    /// <summary>
    /// Which disappointment this is. Nothing matched, too many matched, and
    /// "not that many" call for three different repairs.
    /// </summary>
    public string FailureCode(int count) =>
        count == 0 ? "SELECTOR_NO_MATCH"
        : Kind is CardinalityKind.ExactlyOne or CardinalityKind.ZeroOrOne ? "SELECTOR_AMBIGUOUS"
        : "SELECTOR_CARDINALITY_MISMATCH";
}

public sealed record GeometrySelector(
    string Id,
    SelectorKind Kind,
    string FromResult,
    Cardinality Cardinality,
    FacePredicates? Face = null,
    EdgePredicates? Edge = null);

// --------------------------------------------------------------------------
// What the topology reader measured
// --------------------------------------------------------------------------

public readonly record struct Vector3(double X, double Y, double Z)
{
    public double Along(SelectorAxis axis) => axis switch
    {
        SelectorAxis.X => X,
        SelectorAxis.Y => Y,
        _ => Z
    };

    public double Length => Math.Sqrt(X * X + Y * Y + Z * Z);
}

public readonly record struct BoundingBox(Vector3 Min, Vector3 Max)
{
    public double MinAlong(SelectorAxis axis) => Min.Along(axis);
    public double MaxAlong(SelectorAxis axis) => Max.Along(axis);
    public double CenterAlong(SelectorAxis axis) => (Min.Along(axis) + Max.Along(axis)) / 2;
}

/// <summary>
/// A face as measured, with no COM object attached.
/// </summary>
/// <remarks>
/// Deliberately a plain value. A COM handle is not valid across a rebuild, a
/// reopen or a new KOMPAS process, so nothing downstream may hold one — and
/// keeping the descriptor free of them means the whole matching layer can be
/// tested without KOMPAS installed.
///
/// `Index` is a position in the collection at the moment of reading. It is
/// carried so the adapter can go back to the face it just measured within the
/// same session, and must never be written to a document or compared across
/// rebuilds; that is the exact mistake selectors exist to prevent.
/// </remarks>
public sealed record FaceDescriptor(
    int Index,
    SurfaceType SurfaceType,
    BoundingBox Bounds,
    double? AreaMm2 = null,
    double? RadiusMm = null,
    Vector3? Normal = null,
    IReadOnlyList<SurfaceType>? AdjacentSurfaceTypes = null,
    int AdjacentFaceCount = 0);

public sealed record EdgeDescriptor(
    int Index,
    CurveType CurveType,
    BoundingBox Bounds,
    double? LengthMm = null,
    double? RadiusMm = null,
    Vector3? Direction = null,
    IReadOnlyList<SurfaceType>? AdjacentSurfaceTypes = null,
    Convexity? Convexity = null);

public sealed record ResolutionStep(
    [property: JsonPropertyName("predicate")] string Predicate,
    [property: JsonPropertyName("before")] int Before,
    [property: JsonPropertyName("after")] int After);

public sealed record SelectorResolution(
    [property: JsonPropertyName("selector_id")] string SelectorId,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("initial_candidates")] int InitialCandidates,
    [property: JsonPropertyName("steps")] IReadOnlyList<ResolutionStep> Steps,
    [property: JsonPropertyName("result_count")] int ResultCount,
    [property: JsonPropertyName("satisfied")] bool Satisfied,
    [property: JsonPropertyName("error_code")] string? ErrorCode,
    [property: JsonIgnore] IReadOnlyList<int> MatchedIndexes)
{
    public string ToJson() => JsonSerializer.Serialize(this);
}

public sealed class SelectorException(string code, string safeMessage, SelectorResolution? resolution = null)
    : Exception(safeMessage)
{
    public string Code { get; } = code;
    public SelectorResolution? Resolution { get; } = resolution;
}
