using System.Text.Json;
using CadAi.KompasAdapter;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

public sealed class CadAdapterTests
{
    [Fact]
    public void ParserBuildsBoundedRectangleExtrusionPlan()
    {
        using var document = JsonDocument.Parse(ValidCadIr());
        var plan = CadIrBuildPlanParser.Parse(document.RootElement);
        Assert.Equal((0, 0, 40, 20, 10), (plan.CenterX, plan.CenterY, plan.Width, plan.Height, plan.Depth));
        Assert.Empty(plan.CircularCuts ?? []);
    }

    [Fact]
    public void ParserBuildsContainedCircularThroughCut()
    {
        using var document = JsonDocument.Parse(ValidCadIrWithHole(3, 2, -1));

        var plan = CadIrBuildPlanParser.Parse(document.RootElement);
        var cut = Assert.Single(plan.CircularCuts ?? []);
        Assert.Equal(new CircularCutPlan(2, -1, 3), cut);
    }

    [Fact]
    public void ParserAcceptsALiteralInPlaceOfAParameterReference()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""width"":{""parameter"":""param.width""}",
            @"""width"":25",
            StringComparison.Ordinal));

        var plan = CadIrBuildPlanParser.Parse(document.RootElement);
        Assert.Equal(25, plan.Width);
    }

    [Fact]
    public void ParserRejectsAnExpressionBecauseVersion1_1HasNone()
    {
        // The evaluator is gone with the expression language it served. A
        // document carrying one is from a schema this adapter does not build.
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""width"":{""parameter"":""param.width""}",
            @"""width"":{""expr"":""param.width / 2 + 5""}",
            StringComparison.Ordinal));

        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("CAD_IR_INVALID", error.Code);
    }

    [Fact]
    public void ParserRejectsCircularCutOutsideBody()
    {
        using var document = JsonDocument.Parse(ValidCadIrWithHole(11, 0, 0));

        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("HOLE_OUTSIDE_BODY", error.Code);
    }

    [Fact]
    public void ParserRejectsUnresolvedParameter()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""status"":""confirmed"",""value"":10",
            @"""status"":""unresolved"",""value"":10",
            StringComparison.Ordinal));
        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("UNRESOLVED_PARAMETER_USED", error.Code);
    }

    [Fact]
    public void ParserTreatsAMissingStatusAsConfirmed()
    {
        // `status` is optional in 1.1; only an explicitly unresolved value
        // blocks a build.
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""status"":""confirmed"",", "", StringComparison.Ordinal));

        Assert.Equal(40, CadIrBuildPlanParser.Parse(document.RootElement).Width);
    }

    [Fact]
    public void ParserRejectsUnsupportedFeatureWithoutPartialBuild()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""type"":""solid.extrude""",
            @"""type"":""cut.extrude""",
            StringComparison.Ordinal));
        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("UNSUPPORTED_FEATURE_TYPE", error.Code);
    }

    [Fact]
    public void ParserRejectsADocumentWithNoVersion()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""schema_version"":""1.1"",", "", StringComparison.Ordinal));

        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("CAD_IR_VERSION_MISSING", error.Code);
    }

    [Fact]
    public void ParserDistinguishesATooNewVersionFromAnUnsupportedOne()
    {
        // "Too new" tells an operator to upgrade the worker. "Unsupported"
        // sends them looking for a malformed document.
        using var future = JsonDocument.Parse(ValidCadIr().Replace(
            @"""schema_version"":""1.1""", @"""schema_version"":""1.2""", StringComparison.Ordinal));
        Assert.Equal(
            "CAD_IR_VERSION_TOO_NEW",
            Assert.Throws<CadAdapterException>(() => CadIrBuildPlanParser.Parse(future.RootElement)).Code);

        using var legacy = JsonDocument.Parse(ValidCadIr().Replace(
            @"""schema_version"":""1.1""", @"""schema_version"":""0.1.0""", StringComparison.Ordinal));
        Assert.Equal(
            "CAD_IR_VERSION_UNSUPPORTED",
            Assert.Throws<CadAdapterException>(() => CadIrBuildPlanParser.Parse(legacy.RootElement)).Code);
    }

    [Fact]
    public void ParserRejectsAForeignSchemaName()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""schema"":""cad-ai/cad-ir""",
            @"""schema"":""some-other/format""",
            StringComparison.Ordinal));

        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("CAD_IR_VERSION_UNSUPPORTED", error.Code);
    }

    [Fact]
    public void ParserRejectsANonLengthParameter()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""type"":""length""", @"""type"":""angle""", StringComparison.Ordinal));

        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("UNSUPPORTED_PARAMETER_TYPE", error.Code);
    }

    [Fact]
    public async Task FakeAdapterCreatesChecksummedArtifact()
    {
        var output = Path.Combine(Path.GetTempPath(), $"cad-ai-fake-{Guid.NewGuid():N}");
        try
        {
            var result = await new FakeCadAdapter().BuildAsync(
                new CadBuildRequest(new RectangleExtrusionPlan(0, 0, 40, 20, 10), output),
                CancellationToken.None);
            var artifact = Assert.Single(result.Artifacts);
            Assert.Equal("FAKE_CAD", artifact.Kind);
            Assert.True(artifact.SizeBytes > 0);
            Assert.Matches("^[0-9A-F]{64}$", artifact.Sha256);
        }
        finally
        {
            if (Directory.Exists(output))
                Directory.Delete(output, recursive: true);
        }
    }

    private static string ValidCadIr() =>
        """
        {
          "schema":"cad-ai/cad-ir",
          "schema_version":"1.1",
          "document":{"units":"mm"},
          "parameters":[
            {"id":"param.width","type":"length","unit":"mm","status":"confirmed","value":40},
            {"id":"param.height","type":"length","unit":"mm","status":"confirmed","value":20},
            {"id":"param.depth","type":"length","unit":"mm","status":"confirmed","value":10}
          ],
          "features":[{
            "id":"feature.base","type":"solid.extrude","enabled":true,"depends_on":[],
            "produces":[{"id":"body.main","kind":"solid_body"}],
            "inputs":{
              "direction":"+Z",
              "distance":{"parameter":"param.depth"},
              "sketch":{"id":"sketch.base","plane":"XY","entities":[{
                "id":"rect.base","type":"center_rectangle","center":[0,0],
                "width":{"parameter":"param.width"},"height":{"parameter":"param.height"}
              }]}
            }
          }],
          "metadata":{"generator":"test","generator_version":"1.0"}
        }
        """;

    private static string ValidCadIrWithHole(double radius, double centerX, double centerY) =>
        $$"""
        {
          "schema":"cad-ai/cad-ir",
          "schema_version":"1.1",
          "document":{"units":"mm"},
          "parameters":[
            {"id":"param.width","type":"length","unit":"mm","status":"confirmed","value":40},
            {"id":"param.height","type":"length","unit":"mm","status":"confirmed","value":20},
            {"id":"param.depth","type":"length","unit":"mm","status":"confirmed","value":10},
            {"id":"param.radius","type":"length","unit":"mm","status":"confirmed","value":{{radius}}}
          ],
          "features":[{
            "id":"feature.base","type":"solid.extrude","enabled":true,"depends_on":[],
            "produces":[{"id":"body.main","kind":"solid_body"}],
            "inputs":{
              "direction":"+Z","distance":{"parameter":"param.depth"},
              "sketch":{"id":"sketch.base","plane":"XY","entities":[{
                "id":"rect.base","type":"center_rectangle","center":[0,0],
                "width":{"parameter":"param.width"},"height":{"parameter":"param.height"}
              }]}
            }
          },{
            "id":"feature.hole","type":"cut.extrude","enabled":true,"depends_on":["feature.base"],
            "produces":[],
            "inputs":{
              "direction":"+Z","through_all":true,
              "source_body":{"result":"body.main"},
              "sketch":{"id":"sketch.hole","plane":"XY","entities":[{
                "id":"circle.hole","type":"circle","center":[{{centerX}},{{centerY}}],
                "radius":{"parameter":"param.radius"}
              }]}
            }
          }],
          "metadata":{"generator":"test","generator_version":"1.0"}
        }
        """;
}
