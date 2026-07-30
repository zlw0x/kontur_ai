using System.Text.Json;
using CadAi.KompasAdapter;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

/// <summary>
/// The parser is the last gate before COM, so what it refuses matters more than
/// what it accepts. Every rejection below is a document that satisfies the JSON
/// Schema and would still produce a wrong model or a failed build.
/// </summary>
public sealed class CadAdapterTests
{
    private static CadBuildPlan Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        return CadIrBuildPlanParser.Parse(document.RootElement);
    }

    private static string CodeOf(string json) =>
        Assert.Throws<CadAdapterException>(() => Parse(json)).Code;

    // --- what it builds ----------------------------------------------------

    [Fact]
    public void ParserResolvesParametersAndExpandsTheProfileIntoAContour()
    {
        var plan = Parse(Plate());

        var feature = Assert.IsType<ExtrudeFeaturePlan>(Assert.Single(plan.Features));
        Assert.False(feature.IsCut);
        Assert.Equal(10, feature.DepthMm);
        var outer = Assert.IsType<PathContourPlan>(feature.Sketch.Outer);
        Assert.Equal(4, outer.Segments.Count);
        Assert.Equal(800, Math.Abs(outer.SignedArea(0.01)), 6);
    }

    [Fact]
    public void ParserCarriesTheDocumentsOwnExpectationsThrough()
    {
        var plan = Parse(Plate());

        Assert.Equal(40, plan.Expectations.SizeXMm);
        Assert.Equal(20, plan.Expectations.SizeYMm);
        Assert.Equal(10, plan.Expectations.SizeZMm);
        Assert.Equal(1, plan.Expectations.BodyCount);
        Assert.Equal(0, plan.Expectations.ThroughHoleCount);
    }

    [Fact]
    public void ParserReadsAThroughCutAsAnIslandFreeContourOfItsOwn()
    {
        var plan = Parse(PlateWithHole(3, 2, -1));

        var cut = Assert.IsType<ExtrudeFeaturePlan>(plan.Features[1]);
        Assert.True(cut.IsCut);
        var circle = Assert.IsType<CircleContourPlan>(cut.Sketch.Outer);
        Assert.Equal(new Point2(2, -1), circle.Center);
        Assert.Equal(3, circle.Radius);
    }

    [Fact]
    public void ParserAcceptsALiteralInPlaceOfAParameterReference()
    {
        var plan = Parse(Plate().Replace(
            @"""width"":{""parameter"":""param.width""}", @"""width"":25", StringComparison.Ordinal));

        var outer = Assert.IsType<PathContourPlan>(plan.Base.Sketch.Outer);
        Assert.Equal(25 * 20, Math.Abs(outer.SignedArea(0.01)), 6);
    }

    [Fact]
    public void ParserBuildsASlotProfileFromTwoCentresAndARadius()
    {
        var plan = Parse(Plate().Replace(
            @"""outer"":{""type"":""rectangle"",""center"":[0,0],""width"":{""parameter"":""param.width""},""height"":{""parameter"":""param.height""}}",
            @"""outer"":{""type"":""slot"",""start"":[-10,0],""end"":[10,0],""radius"":4}",
            StringComparison.Ordinal));

        var outer = Assert.IsType<PathContourPlan>(plan.Base.Sketch.Outer);
        Assert.Equal(4, outer.Segments.Count);
        Assert.Equal(2, outer.Segments.OfType<ArcSegmentPlan>().Count());
    }

    [Fact]
    public void ParserBuildsAProfileWithAnIslandInIt()
    {
        var plan = Parse(Plate().Replace(
            @"""inner"":[]",
            @"""inner"":[{""type"":""circle"",""center"":[0,0],""radius"":4}]",
            StringComparison.Ordinal));

        var island = Assert.Single(plan.Base.Sketch.Inner);
        Assert.Equal(4, Assert.IsType<CircleContourPlan>(island).Radius);
    }

    [Fact]
    public void ParserReadsAnOffsetPlaneAndASketchThatSitsOnIt()
    {
        var plan = Parse(PlateWithRaisedBoss());

        var datum = Assert.IsType<DatumPlaneFeaturePlan>(plan.Features[1]);
        Assert.Equal("plane.raised", datum.ResultId);
        Assert.Equal(10, datum.OffsetMm);
        var boss = Assert.IsType<ExtrudeFeaturePlan>(plan.Features[2]);
        Assert.Equal("plane.raised", Assert.IsType<DatumPlanePlan>(boss.Sketch.Plane).ResultId);
    }

    [Fact]
    public void ParserReadsASketchPlaneNamedByASelector()
    {
        var plan = Parse(PlateWithBossOnTopFace());

        var boss = Assert.IsType<ExtrudeFeaturePlan>(plan.Features[1]);
        var selector = Assert.IsType<FacePlanePlan>(boss.Sketch.Plane).Selector;
        Assert.Equal("selector.top", selector.Id);
        Assert.Equal(CardinalityKind.ExactlyOne, selector.Cardinality.Kind);
        Assert.Equal(SurfaceType.Planar, selector.Face!.SurfaceType);
        Assert.Equal(SelectorAxis.Z, selector.Face.Normal!.ParallelTo);
        Assert.Equal(ExtremeKind.Maximum, selector.Face.Position!.Extreme);
    }

    [Fact]
    public void ParserReadsConstructionGeometryWithoutTreatingItAsAProfile()
    {
        var plan = Parse(Plate().Replace(
            @"""construction"":[]",
            @"""construction"":[{""type"":""point"",""id"":""point.centre"",""at"":[0,0]}]",
            StringComparison.Ordinal));

        var entity = Assert.Single(plan.Base.Sketch.Construction);
        Assert.Equal("point", entity.Kind);
        Assert.Equal(new Point2(0, 0), entity.At);
    }

    // --- what it refuses ---------------------------------------------------

    [Fact]
    public void ParserRejectsAnExpressionBecauseCadIrHasNone()
    {
        // The evaluator is gone with the expression language it served. A
        // document carrying one is from a schema this adapter does not build.
        Assert.Equal("CAD_IR_INVALID", CodeOf(Plate().Replace(
            @"""width"":{""parameter"":""param.width""}",
            @"""width"":{""expr"":""param.width / 2 + 5""}",
            StringComparison.Ordinal)));
    }

    /// <summary>
    /// A cut clear of the material leaves the solid unchanged and reports
    /// success, which is the quiet kind of wrong.
    /// </summary>
    [Fact]
    public void ParserRejectsACutThatWouldRemoveNothing()
    {
        Assert.Equal("CUT_OUTSIDE_BODY", CodeOf(PlateWithHole(3, 60, 0)));
    }

    [Fact]
    public void ParserRejectsAnUnclosedProfileBeforeAnyCom()
    {
        var open = @"""outer"":{""type"":""path"",""segments"":[" +
                  @"{""type"":""line"",""start"":[0,0],""end"":[10,0]}," +
                  @"{""type"":""line"",""start"":[10,0],""end"":[10,10]}," +
                  @"{""type"":""line"",""start"":[10,10],""end"":[1,10]}]}";
        Assert.Equal("SKETCH_CONTOUR_OPEN", CodeOf(Plate().Replace(
            @"""outer"":{""type"":""rectangle"",""center"":[0,0],""width"":{""parameter"":""param.width""},""height"":{""parameter"":""param.height""}}",
            open, StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsAnIslandOutsideTheProfile()
    {
        Assert.Equal("SKETCH_ISLAND_OUTSIDE_PROFILE", CodeOf(Plate().Replace(
            @"""inner"":[]",
            @"""inner"":[{""type"":""circle"",""center"":[100,0],""radius"":4}]",
            StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsUnresolvedParameter()
    {
        Assert.Equal("UNRESOLVED_PARAMETER_USED", CodeOf(Plate().Replace(
            @"""status"":""confirmed"",""value"":10",
            @"""status"":""unresolved"",""value"":10",
            StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserTreatsAMissingStatusAsConfirmed()
    {
        // `status` is optional; only an explicitly unresolved value blocks a
        // build.
        var plan = Parse(Plate().Replace(@"""status"":""confirmed"",", "", StringComparison.Ordinal));

        Assert.Equal(10, plan.Base.DepthMm);
    }

    [Fact]
    public void ParserRejectsAPlanWhoseFirstGeometricFeatureIsACut()
    {
        Assert.Equal("UNSUPPORTED_FEATURE_SET", CodeOf(Plate().Replace(
            @"""type"":""solid.extrude""", @"""type"":""cut.extrude""", StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsADocumentWithNoVersion()
    {
        Assert.Equal("CAD_IR_VERSION_MISSING",
            CodeOf(Plate().Replace(@"""schema_version"":""1.2"",", "", StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserDistinguishesATooNewVersionFromAnUnsupportedOne()
    {
        // "Too new" tells an operator to upgrade the worker. "Unsupported"
        // sends them looking for a malformed document.
        Assert.Equal("CAD_IR_VERSION_TOO_NEW", CodeOf(Plate().Replace(
            @"""schema_version"":""1.2""", @"""schema_version"":""1.3""", StringComparison.Ordinal)));
        Assert.Equal("CAD_IR_VERSION_UNSUPPORTED", CodeOf(Plate().Replace(
            @"""schema_version"":""1.2""", @"""schema_version"":""1.1""", StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsAForeignSchemaName()
    {
        Assert.Equal("CAD_IR_VERSION_UNSUPPORTED", CodeOf(Plate().Replace(
            @"""schema"":""cad-ai/cad-ir""", @"""schema"":""some-other/format""",
            StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsAParameterTypeItCannotUse()
    {
        Assert.Equal("UNSUPPORTED_PARAMETER_TYPE", CodeOf(Plate().Replace(
            @"""type"":""length""", @"""type"":""count""", StringComparison.Ordinal)));
    }

    /// <summary>
    /// A predicate the resolver does not implement would otherwise be ignored,
    /// which widens the selector: one meant to name a single face would match
    /// several.
    /// </summary>
    [Fact]
    public void ParserRejectsASelectorPredicateItDoesNotResolve()
    {
        Assert.Equal("SELECTOR_UNSUPPORTED_PREDICATE", CodeOf(PlateWithBossOnTopFace().Replace(
            @"""surface_type"":""planar""",
            @"""surface_type"":""planar"",""curvature"":""concave""",
            StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsAPlaneOffsetByNothing()
    {
        Assert.Equal("DIMENSION_OUT_OF_RANGE", CodeOf(PlateWithRaisedBoss().Replace(
            @"""offset_mm"":10", @"""offset_mm"":0", StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsASketchOnAPlaneNoFeatureProduced()
    {
        Assert.Equal("FEATURE_RESULT_UNAVAILABLE", CodeOf(PlateWithRaisedBoss().Replace(
            @"""result"":""plane.raised""", @"""result"":""plane.absent""",
            StringComparison.Ordinal)));
    }

    [Fact]
    public void ParserRejectsAMissingBoundingBoxExpectation()
    {
        var withoutBounds = Plate().Replace(
            @"{""id"":""expect.bounds"",""type"":""bounding_box"",""size_mm"":{""x"":40,""y"":20,""z"":10},""tolerance_mm"":0.05},",
            "", StringComparison.Ordinal);

        Assert.Equal("REQUIRED_EXPECTATION_MISSING", CodeOf(withoutBounds));
    }

    // --- the fake adapter --------------------------------------------------

    [Fact]
    public async Task FakeAdapterCreatesChecksummedArtifact()
    {
        var output = Path.Combine(Path.GetTempPath(), $"cad-ai-fake-{Guid.NewGuid():N}");
        try
        {
            var result = await new FakeCadAdapter().BuildAsync(
                new CadBuildRequest(Parse(PlateWithHole(3, 0, 0)), output), CancellationToken.None);

            var artifact = Assert.Single(result.Artifacts);
            Assert.Equal("FAKE_CAD", artifact.Kind);
            Assert.True(artifact.SizeBytes > 0);
            Assert.Matches("^[0-9A-F]{64}$", artifact.Sha256);
            Assert.Equal(2, result.Operations!.Count);
        }
        finally
        {
            if (Directory.Exists(output)) Directory.Delete(output, recursive: true);
        }
    }

    // --- fixtures ----------------------------------------------------------

    private const string Expectations =
        @"""expectations"":[" +
        @"{""id"":""expect.bounds"",""type"":""bounding_box"",""size_mm"":{""x"":40,""y"":20,""z"":10},""tolerance_mm"":0.05}," +
        @"{""id"":""expect.bodies"",""type"":""body_count"",""value"":1}]";

    private const string Parameters =
        @"""parameters"":[" +
        @"{""id"":""param.width"",""type"":""length"",""unit"":""mm"",""status"":""confirmed"",""value"":40}," +
        @"{""id"":""param.height"",""type"":""length"",""unit"":""mm"",""status"":""confirmed"",""value"":20}," +
        @"{""id"":""param.depth"",""type"":""length"",""unit"":""mm"",""status"":""confirmed"",""value"":10}]";

    private const string RectangleOuter =
        @"""outer"":{""type"":""rectangle"",""center"":[0,0],""width"":{""parameter"":""param.width""},""height"":{""parameter"":""param.height""}}";

    private static string Plate() =>
        "{" +
        @"""schema"":""cad-ai/cad-ir""," +
        @"""schema_version"":""1.2""," +
        @"""document"":{""units"":""mm""}," +
        Parameters + "," +
        @"""features"":[{" +
        @"""id"":""feature.base"",""type"":""solid.extrude"",""enabled"":true,""depends_on"":[]," +
        @"""produces"":[{""id"":""body.main"",""kind"":""solid_body""}]," +
        @"""inputs"":{""direction"":""+Z"",""distance"":{""parameter"":""param.depth""}," +
        @"""sketch"":{""id"":""sketch.base"",""plane"":{""on"":""base"",""plane"":""XY""}," +
        RectangleOuter + @",""inner"":[],""construction"":[]}}" +
        "}]," +
        Expectations + "," +
        @"""metadata"":{""generator"":""test"",""generator_version"":""1.0""}" +
        "}";

    private static string PlateWithHole(double radius, double centerX, double centerY) =>
        Plate().Replace("}]," + Expectations, "},{" +
            @"""id"":""feature.hole"",""type"":""cut.extrude"",""enabled"":true," +
            @"""depends_on"":[""feature.base""],""produces"":[]," +
            @"""inputs"":{""direction"":""+Z"",""through_all"":true," +
            @"""source_body"":{""result"":""body.main""}," +
            @"""sketch"":{""id"":""sketch.hole"",""plane"":{""on"":""base"",""plane"":""XY""}," +
            $@"""outer"":{{""type"":""circle"",""center"":[{centerX},{centerY}],""radius"":{radius}}}," +
            @"""inner"":[],""construction"":[]}}" +
            "}]," + Expectations, StringComparison.Ordinal);

    private static string PlateWithRaisedBoss() =>
        Plate().Replace("}]," + Expectations, "},{" +
            @"""id"":""feature.raised"",""type"":""datum.plane.offset"",""enabled"":true," +
            @"""depends_on"":[""feature.base""]," +
            @"""produces"":[{""id"":""plane.raised"",""kind"":""plane""}]," +
            @"""inputs"":{""base"":""XY"",""offset_mm"":10}" +
            "},{" +
            @"""id"":""feature.boss"",""type"":""solid.extrude"",""enabled"":true," +
            @"""depends_on"":[""feature.raised""],""produces"":[]," +
            @"""inputs"":{""direction"":""+Z"",""distance"":5," +
            @"""sketch"":{""id"":""sketch.boss"",""plane"":{""on"":""datum"",""plane"":{""result"":""plane.raised""}}," +
            @"""outer"":{""type"":""circle"",""center"":[0,0],""radius"":6}," +
            @"""inner"":[],""construction"":[]}}" +
            "}]," + Expectations, StringComparison.Ordinal);

    private static string PlateWithBossOnTopFace() =>
        Plate().Replace("}]," + Expectations, "},{" +
            @"""id"":""feature.boss"",""type"":""solid.extrude"",""enabled"":true," +
            @"""depends_on"":[""feature.base""],""produces"":[]," +
            @"""inputs"":{""direction"":""+Z"",""distance"":5," +
            @"""sketch"":{""id"":""sketch.boss"",""plane"":{""on"":""face"",""face"":{" +
            @"""id"":""selector.top"",""kind"":""face"",""from_result"":""body.main""," +
            @"""cardinality"":""exactly_one"",""where"":{""surface_type"":""planar""," +
            @"""normal"":{""parallel_to"":""axis.z"",""direction"":""positive""}," +
            @"""position"":{""extreme_along"":""axis.z"",""extreme"":""maximum""}}}}," +
            @"""outer"":{""type"":""circle"",""center"":[0,0],""radius"":6}," +
            @"""inner"":[],""construction"":[]}}" +
            "}]," + Expectations, StringComparison.Ordinal);
}
