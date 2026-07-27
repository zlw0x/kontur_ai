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
    public void ParserEvaluatesBoundedArithmeticExpression()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""width"":{""param"":""p_width""}",
            @"""width"":{""expr"":""p_width / 2 + 5""}",
            StringComparison.Ordinal));
        var plan = CadIrBuildPlanParser.Parse(document.RootElement);
        Assert.Equal(25, plan.Width);
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
    public void ParserRejectsUnsupportedFeatureWithoutPartialBuild()
    {
        using var document = JsonDocument.Parse(ValidCadIr().Replace(
            @"""type"":""extrude_add""",
            @"""type"":""hole""",
            StringComparison.Ordinal));
        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement));
        Assert.Equal("UNSUPPORTED_FEATURE_TYPE", error.Code);
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
          "schema_version":"0.1.0",
          "parameters":[
            {"id":"p_width","status":"confirmed","value":40},
            {"id":"p_height","status":"confirmed","value":20},
            {"id":"p_depth","status":"confirmed","value":10}
          ],
          "features":[{
            "id":"f_base","type":"extrude_add","enabled":true,"depends_on":[],
            "inputs":{
              "direction":"+Z",
              "distance":{"expr":"p_depth"},
              "sketch":{"plane":"XY","entities":[{
                "id":"rect","type":"center_rectangle","center":[0,0],
                "width":{"param":"p_width"},"height":{"param":"p_height"}
              }]}
            }
          }]
        }
        """;

    private static string ValidCadIrWithHole(double radius, double centerX, double centerY) =>
        $$"""
        {
          "schema_version":"0.1.0",
          "parameters":[
            {"id":"p_width","status":"confirmed","value":40},
            {"id":"p_height","status":"confirmed","value":20},
            {"id":"p_depth","status":"confirmed","value":10},
            {"id":"p_radius","status":"confirmed","value":{{radius}}}
          ],
          "features":[{
            "id":"f_base","type":"extrude_add","enabled":true,"depends_on":[],
            "inputs":{
              "direction":"+Z","distance":{"param":"p_depth"},
              "sketch":{"plane":"XY","entities":[{
                "id":"rect","type":"center_rectangle","center":[0,0],
                "width":{"param":"p_width"},"height":{"param":"p_height"}
              }]}
            }
          },{
            "id":"f_hole","type":"extrude_cut","enabled":true,"depends_on":["f_base"],
            "inputs":{
              "direction":"+Z","through_all":true,
              "sketch":{"plane":"XY","entities":[{
                "id":"hole","type":"circle","center":[{{centerX}},{{centerY}}],
                "radius":{"param":"p_radius"}
              }]}
            }
          }]
        }
        """;
}
