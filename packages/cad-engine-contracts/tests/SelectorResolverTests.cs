using CadAi.CadEngine;
using Xunit;

namespace CadAi.CadEngine.Tests;

/// <summary>
/// The resolver is exercised against a measured plate rather than a live
/// model, because the descriptors are plain values by design. What KOMPAS
/// actually reports is checked separately, by the topology reader and the real
/// acceptance run.
/// </summary>
public sealed class SelectorResolverTests
{
    private const double Width = 60, Height = 30, Depth = 8, HoleRadius = 2.5;

    /// <summary>
    /// A 60 x 30 x 8 plate with two Ø5 through holes: six planar faces and two
    /// cylinders, exactly what the confirmed MVP builds.
    /// </summary>
    private static List<FaceDescriptor> PlateFaces()
    {
        var faces = new List<FaceDescriptor>
        {
            Planar(0, new Vector3(0, 0, 1), Box(-Width / 2, -Height / 2, Depth, Width / 2, Height / 2, Depth), Width * Height),
            Planar(1, new Vector3(0, 0, -1), Box(-Width / 2, -Height / 2, 0, Width / 2, Height / 2, 0), Width * Height),
            Planar(2, new Vector3(1, 0, 0), Box(Width / 2, -Height / 2, 0, Width / 2, Height / 2, Depth), Height * Depth),
            Planar(3, new Vector3(-1, 0, 0), Box(-Width / 2, -Height / 2, 0, -Width / 2, Height / 2, Depth), Height * Depth),
            Planar(4, new Vector3(0, 1, 0), Box(-Width / 2, Height / 2, 0, Width / 2, Height / 2, Depth), Width * Depth),
            Planar(5, new Vector3(0, -1, 0), Box(-Width / 2, -Height / 2, 0, Width / 2, -Height / 2, Depth), Width * Depth),
        };
        faces.Add(Cylinder(6, -15));
        faces.Add(Cylinder(7, 15));
        return faces;
    }

    private static FaceDescriptor Planar(int index, Vector3 normal, BoundingBox bounds, double area) =>
        new(index, SurfaceType.Planar, bounds, area, null, normal,
            [SurfaceType.Planar, SurfaceType.Cylindrical], 4);

    private static FaceDescriptor Cylinder(int index, double x) =>
        new(index, SurfaceType.Cylindrical,
            Box(x - HoleRadius, -HoleRadius, 0, x + HoleRadius, HoleRadius, Depth),
            2 * Math.PI * HoleRadius * Depth, HoleRadius, null, [SurfaceType.Planar], 2);

    private static BoundingBox Box(double x1, double y1, double z1, double x2, double y2, double z2) =>
        new(new Vector3(x1, y1, z1), new Vector3(x2, y2, z2));

    private static GeometrySelector FaceSelector(
        FacePredicates where, CardinalityKind kind = CardinalityKind.ExactlyOne, int n = 0) =>
        new("selector.test", SelectorKind.Face, "body.main", new Cardinality(kind, n), Face: where);

    private static GeometrySelector EdgeSelector(
        EdgePredicates where, CardinalityKind kind = CardinalityKind.ExactlyOne, int n = 0) =>
        new("selector.test", SelectorKind.Edge, "body.main", new Cardinality(kind, n), Edge: where);

    // --- the headline case -------------------------------------------------

    [Fact]
    public void TheTopFaceIsFoundByMeaningAndIsNotTheBottomOne()
    {
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Positive),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum)));

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Equal(0, Assert.Single(resolution.MatchedIndexes));
        Assert.Null(resolution.ErrorCode);
    }

    [Fact]
    public void TheSameSelectorFindsTheSameFaceAfterTheWidthChanges()
    {
        // What an index cannot do. The plate grows, the face list may be
        // reordered by the kernel, and "the planar face furthest along +Z" is
        // still the top face.
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Positive),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum)));

        var widened = PlateFaces()
            .Select(face => face with { Index = 7 - face.Index })
            .Reverse()
            .ToList();

        var resolution = SelectorResolver.ResolveFaces(selector, widened);

        Assert.True(resolution.Satisfied);
        var matched = widened.Single(face => face.Index == resolution.MatchedIndexes[0]);
        Assert.Equal(Depth, matched.Bounds.MaxAlong(SelectorAxis.Z));
        Assert.Equal(new Vector3(0, 0, 1), matched.Normal);
    }

    [Fact]
    public void TheHoleWallIsFoundByRadiusAndSurfaceType()
    {
        var selector = FaceSelector(
            new FacePredicates(
                SurfaceType: SurfaceType.Cylindrical,
                RadiusMm: new Measurement(HoleRadius, 0.01)),
            CardinalityKind.ExactlyN, 2);

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Equal([6, 7], resolution.MatchedIndexes);
    }

    // --- symmetry is the proof of determinism ------------------------------

    [Fact]
    public void TwoIdenticalSideFacesAreAmbiguousRatherThanArbitrary()
    {
        // The test that shows the resolver never guesses. Both side faces are
        // planar and perpendicular to X; picking the first would be a
        // plausible-looking wrong answer.
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.X)));

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.False(resolution.Satisfied);
        Assert.Equal("SELECTOR_AMBIGUOUS", resolution.ErrorCode);
        Assert.Equal(2, resolution.ResultCount);
    }

    [Fact]
    public void AddingTheExtremePredicateResolvesTheSymmetryToExactlyOne()
    {
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.X),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.X, Extreme: ExtremeKind.Maximum)));

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Equal(2, Assert.Single(resolution.MatchedIndexes));
    }

    [Fact]
    public void DirectionSeparatesTheTwoFacesAnAxisAloneCannot()
    {
        var negative = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Negative)));

        var resolution = SelectorResolver.ResolveFaces(negative, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Equal(1, Assert.Single(resolution.MatchedIndexes));
    }

    // --- cardinality -------------------------------------------------------

    [Fact]
    public void NoMatchIsDistinguishedFromTooMany()
    {
        var impossible = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Spherical));

        var resolution = SelectorResolver.ResolveFaces(impossible, PlateFaces());

        Assert.Equal("SELECTOR_NO_MATCH", resolution.ErrorCode);
        Assert.Equal(0, resolution.ResultCount);
    }

    [Fact]
    public void AWrongCountIsItsOwnFailure()
    {
        var threeHoles = FaceSelector(
            new FacePredicates(SurfaceType: SurfaceType.Cylindrical),
            CardinalityKind.ExactlyN, 3);

        var resolution = SelectorResolver.ResolveFaces(threeHoles, PlateFaces());

        // The document claims three holes and the part has two. That the count
        // is wrong is the useful signal, not something to absorb.
        Assert.Equal("SELECTOR_CARDINALITY_MISMATCH", resolution.ErrorCode);
        Assert.Equal(2, resolution.ResultCount);
    }

    [Fact]
    public void AllAcceptsWhateverSurvives()
    {
        var everyPlanarFace = FaceSelector(
            new FacePredicates(SurfaceType: SurfaceType.Planar), CardinalityKind.All);

        var resolution = SelectorResolver.ResolveFaces(everyPlanarFace, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Equal(6, resolution.ResultCount);
    }

    // --- the trace ---------------------------------------------------------

    [Fact]
    public void TheTraceSaysWhereEachCandidateWent()
    {
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum)));

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.Equal(8, resolution.InitialCandidates);
        Assert.Equal(
            [(8, 6), (6, 2), (2, 1)],
            resolution.Steps.Select(step => (step.Before, step.After)).ToArray());
        Assert.Contains("surface_type=planar", resolution.Steps[0].Predicate);
        Assert.Contains("parallel to z", resolution.Steps[1].Predicate);
        Assert.Contains("maximum position on z", resolution.Steps[2].Predicate);
    }

    [Fact]
    public void AFailedResolutionStillCarriesItsTrace()
    {
        // What a repair agent reads. "Two candidates after the normal filter"
        // says to add a position predicate; "no match" alone says nothing.
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.X)));

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.False(resolution.Satisfied);
        Assert.Equal(2, resolution.Steps[^1].After);
        Assert.Contains("\"error_code\":\"SELECTOR_AMBIGUOUS\"", resolution.ToJson());
    }

    [Fact]
    public void ATraceNeverReportsMoreCandidatesThanItReceived()
    {
        var selector = FaceSelector(
            new FacePredicates(SurfaceType: SurfaceType.Planar), CardinalityKind.All);

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.All(resolution.Steps, step => Assert.True(step.After <= step.Before));
    }

    // --- tolerance ---------------------------------------------------------

    [Fact]
    public void AKernelNormalThatIsNotExactlyAxisAlignedStillMatches()
    {
        // Modelling kernels do not return exactly (0, 0, 1). Requiring
        // exactness would make every selector fail on real geometry.
        var faces = PlateFaces();
        faces[0] = faces[0] with { Normal = new Vector3(1e-9, -2e-9, 0.9999999999) };
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Positive),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum)));

        Assert.True(SelectorResolver.ResolveFaces(selector, faces).Satisfied);
    }

    [Fact]
    public void ARadiusOutsideItsToleranceDoesNotMatch()
    {
        var selector = FaceSelector(
            new FacePredicates(
                SurfaceType: SurfaceType.Cylindrical,
                RadiusMm: new Measurement(3.0, 0.01)),
            CardinalityKind.ZeroOrOne);

        var resolution = SelectorResolver.ResolveFaces(selector, PlateFaces());

        Assert.True(resolution.Satisfied);
        Assert.Empty(resolution.MatchedIndexes);
    }

    // --- edges -------------------------------------------------------------

    private static List<EdgeDescriptor> PlateEdges()
    {
        var edges = new List<EdgeDescriptor>();
        for (var index = 0; index < 4; index++)
        {
            edges.Add(new EdgeDescriptor(
                index, CurveType.Line,
                Box(-Width / 2, -Height / 2, Depth, Width / 2, Height / 2, Depth),
                Width, null, new Vector3(1, 0, 0), [SurfaceType.Planar], Convexity.Convex));
        }
        edges.Add(new EdgeDescriptor(
            4, CurveType.Circle, Box(-17.5, -2.5, Depth, -12.5, 2.5, Depth),
            2 * Math.PI * HoleRadius, HoleRadius, null,
            [SurfaceType.Planar, SurfaceType.Cylindrical], Convexity.Concave));
        edges.Add(new EdgeDescriptor(
            5, CurveType.Circle, Box(12.5, -2.5, Depth, 17.5, 2.5, Depth),
            2 * Math.PI * HoleRadius, HoleRadius, null,
            [SurfaceType.Planar, SurfaceType.Cylindrical], Convexity.Concave));
        return edges;
    }

    [Fact]
    public void HoleRimsAreFoundByCurveTypeRadiusAndWhatTheyTouch()
    {
        var selector = EdgeSelector(
            new EdgePredicates(
                CurveType: CurveType.Circle,
                RadiusMm: new Measurement(HoleRadius, 0.01),
                Adjacent: new AdjacencyPredicate([SurfaceType.Planar, SurfaceType.Cylindrical])),
            CardinalityKind.ExactlyN, 2);

        var resolution = SelectorResolver.ResolveEdges(selector, PlateEdges());

        Assert.True(resolution.Satisfied);
        Assert.Equal([4, 5], resolution.MatchedIndexes);
    }

    [Fact]
    public void ConvexitySeparatesAnInnerRimFromAnOuterEdge()
    {
        var selector = EdgeSelector(
            new EdgePredicates(Convexity: Convexity.Concave), CardinalityKind.ExactlyN, 2);

        Assert.True(SelectorResolver.ResolveEdges(selector, PlateEdges()).Satisfied);
    }

    [Fact]
    public void AFaceSelectorHandedToTheEdgeResolverIsARefusalNotAGuess()
    {
        var faceSelector = FaceSelector(new FacePredicates(SurfaceType: SurfaceType.Planar));

        var error = Assert.Throws<SelectorException>(
            () => SelectorResolver.ResolveEdges(faceSelector, PlateEdges()));
        Assert.Equal("SELECTOR_RESULT_KIND_MISMATCH", error.Code);
    }

    [Fact]
    public void ResolutionIsDeterministicAcrossRepeatedCallsAndInputOrder()
    {
        var selector = FaceSelector(new FacePredicates(
            SurfaceType: SurfaceType.Planar,
            Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Positive),
            Position: new PositionPredicate(ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum)));
        var faces = PlateFaces();

        var first = SelectorResolver.ResolveFaces(selector, faces);
        var again = SelectorResolver.ResolveFaces(selector, faces);
        var shuffled = SelectorResolver.ResolveFaces(selector, Enumerable.Reverse(faces).ToList());

        Assert.Equal(first.MatchedIndexes, again.MatchedIndexes);
        Assert.Equal(first.MatchedIndexes, shuffled.MatchedIndexes);
    }
}
