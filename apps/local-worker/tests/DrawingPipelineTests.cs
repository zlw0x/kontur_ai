using CadAi.CadEngine;
using System.Security.Cryptography;
using System.Text.Json;
using CadAi.CodexRunner;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

public sealed class DrawingPipelineTests
{
    [Fact]
    public async Task StopsForUnansweredClarification()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var runner = new FakeRunner(
                """
                {
                  "schema_version":"0.1.0","stage":"drawing_analysis",
                  "status":"need_user_input","confidence":0.8,"warnings":[],
                  "result":{
                    "ready_for_cad":false,"summary":"Depth is missing.",
                    "parameters":[],
                    "questions":[{"id":"q_depth","parameter_id":"depth","text":"What is the depth?"}]
                  }
                }
                """);
            var result = await new DrawingPipeline(runner, engine: new StubValidatingEngine()).RunAsync(workspace, [image]);
            Assert.Equal("WAITING_FOR_USER_ANSWERS", result.Status);
            Assert.Null(result.CadIrPath);
            Assert.Equal(1, runner.Calls);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    [Fact]
    public async Task RepairsAdapterInvalidCadIrWithinBudget()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(),
                "tests", "fixtures", "cad-ir", "plate.v1_5.json"));
            var invalid = valid.Replace(
                @"""type"": ""solid.extrude""",
                @"""type"": ""cut.extrude""",
                StringComparison.Ordinal);
            var runner = new FakeRunner(ReadyAnalysis(), invalid, valid);
            var result = await new DrawingPipeline(runner, engine: new StubValidatingEngine()).RunAsync(workspace, [image]);
            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.NotNull(result.CadIrPath);
            Assert.Equal(3, runner.Calls);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// The shape statement travels to the engine, and only when there is one.
    /// </summary>
    /// <remarks>
    /// The engine is handed a *shape claim*, not a drawing analysis: it has no
    /// business knowing that a drawing exists, and giving it the confidences, the
    /// page references and the questions would make it a reader of something it does
    /// not read.
    /// </remarks>
    [Fact]
    public async Task TheShapeTheDrawingWasReadAsIsHandedToTheEngine()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_5.json"));
            var engine = new StubValidatingEngine();
            var result = await new DrawingPipeline(
                new FakeRunner(AnalysisWithShape(), valid), engine: engine)
                .RunAsync(workspace, [image]);

            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.NotNull(engine.SawShapeClaim);
            var claim = JsonDocument.Parse(File.ReadAllText(engine.SawShapeClaim!)).RootElement;
            Assert.Equal("rectangle", claim.GetProperty("profile").GetString());
            Assert.Equal(1, claim.GetProperty("solids").GetInt32());
            Assert.Equal("p_depth", claim.GetProperty("thickness").GetString());
            Assert.Equal(1, claim.GetProperty("openings").GetArrayLength());
            // Nothing about the drawing crosses over: no confidence, no page, no
            // question, no summary.
            foreach (var absent in new[] { "confidence", "source", "questions", "summary" })
                Assert.False(claim.TryGetProperty(absent, out _), absent);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// An analysis with no shape leaves the compilation checked as it was before.
    /// </summary>
    /// <remarks>
    /// An older artifact, or a reading stage that could not settle the outline. The
    /// alternative — refusing the job — would make a field that did not exist last
    /// week into a reason nothing builds.
    /// </remarks>
    [Fact]
    public async Task AnAnalysisWithNoShapeStillCompiles()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_5.json"));
            var engine = new StubValidatingEngine();
            var result = await new DrawingPipeline(
                new FakeRunner(ReadyAnalysis(), valid), engine: engine)
                .RunAsync(workspace, [image]);

            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.Equal(1, engine.Validations);
            Assert.Null(engine.SawShapeClaim);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    private static string AnalysisWithShape() =>
        """
        {
          "schema_version":"0.1.0","stage":"drawing_analysis",
          "status":"success","confidence":1,"warnings":[],
          "result":{
            "ready_for_cad":true,"summary":"Plate 40 by 20 by 10, one hole.",
            "parameters":[],
            "shape":{
              "profile":"rectangle",
              "openings":[{"kind":"round","count":1}],
              "solids":1,
              "thickness_parameter":"p_depth",
              "note":null
            },
            "questions":[]
          }
        }
        """;

    private static string ReadyAnalysis() =>
        """
        {
          "schema_version":"0.1.0","stage":"drawing_analysis",
          "status":"success","confidence":1,"warnings":[],
          "result":{
            "ready_for_cad":true,"summary":"Plate 40 by 20 by 10.",
            "parameters":[],"questions":[]
          }
        }
        """;

    private static string Workspace()
    {
        var path = Path.Combine(Path.GetTempPath(), $"cad-ai-drawing-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    private static string CreateImagePlaceholder(string workspace)
    {
        var path = Path.Combine(workspace, "page.png");
        File.WriteAllBytes(path, [0x89, 0x50, 0x4E, 0x47]);
        return path;
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "AGENTS.md")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root not found.");
    }

    private sealed class FakeRunner(params string[] outputs) : ICodexRunner
    {
        private readonly Queue<string> values = new(outputs);
        public int Calls { get; private set; }

        public async Task<CodexStageResult> RunAsync(
            CodexStageRequest request,
            CancellationToken cancellationToken = default)
        {
            Calls++;
            var value = values.Dequeue();
            Directory.CreateDirectory(Path.GetDirectoryName(request.OutputPath)!);
            await File.WriteAllTextAsync(request.OutputPath, value, cancellationToken);
            var hash = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value)));
            return new(null, null, request.OutputPath, hash, Path.Combine(request.Workspace, "events.jsonl"));
        }
    }
}
