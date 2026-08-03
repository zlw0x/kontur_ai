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
                "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
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
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
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
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
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

    /// <summary>
    /// The prompts reach the model as text, and a placeholder is text that failed.
    /// </summary>
    /// <remarks>
    /// Both prompts are C# raw string literals, and the compilation one spells out
    /// nested JSON — so it needs a higher interpolation level than the others, and a
    /// `{{Version}}` in a `$$$` literal renders as the literal characters while a
    /// `{{{Version}}}` in a `$$` one renders the value wrapped in braces. Neither
    /// fails to compile. Both are invisible until an AI run reads the nonsense, which
    /// is the most expensive place to find out.
    /// </remarks>
    [Fact]
    public async Task EveryPlaceholderInEveryPromptIsFilledIn()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var invalid = valid.Replace(
                @"""type"": ""solid.extrude""", @"""type"": ""cut.extrude""",
                StringComparison.Ordinal);
            var runner = new FakeRunner(AnalysisWithShape(), invalid, valid);

            await new DrawingPipeline(runner, engine: new StubValidatingEngine())
                .RunAsync(workspace, [image]);

            Assert.Equal(3, runner.Prompts.Count);
            var compilation = runner.Prompts[1];
            var repair = runner.Prompts[2];

            // The version arrives as itself, not wrapped and not spelled out.
            Assert.Contains("canonical CAD-IR 1.10", compilation);
            Assert.Contains("CAD-IR 1.10 output schema", repair);
            foreach (var prompt in runner.Prompts)
            {
                Assert.DoesNotContain("{1.10}", prompt);
                Assert.DoesNotContain("CadIrVersion", prompt);
                Assert.DoesNotContain("PromptVersion", prompt);
            }

            // The repair prompt carries the failure and the candidate, not their names.
            Assert.DoesNotContain("{candidate}", repair);
            Assert.DoesNotContain("{errorCode}", repair);
            Assert.Contains("cut.extrude", repair);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// The compilation prompt describes every shape the output profile offers.
    /// </summary>
    /// <remarks>
    /// The profile constrains what the model *may* emit; the prompt is what tells it
    /// these shapes exist at all. A profile that grew without the prompt growing is a
    /// capability nothing will ever ask for (POSTMVP-016).
    /// </remarks>
    [Fact]
    public async Task TheCompilationPromptNamesEveryFeatureTheProfileOffers()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var runner = new FakeRunner(AnalysisWithShape(), valid);
            await new DrawingPipeline(runner, engine: new StubValidatingEngine())
                .RunAsync(workspace, [image]);

            var compilation = runner.Prompts[1];
            foreach (var offered in new[]
                     {
                         "solid.extrude", "cut.extrude", "datum.plane.offset", "feature.pattern",
                         "feature.fillet", "feature.chamfer", "feature.shell",
                         "through_all", "\"kind\":\"linear\"", "\"kind\":\"circular\"",
                     })
                Assert.Contains(offered, compilation);

            // The three rules a widened profile makes possible to get wrong.
            Assert.Contains("never both", compilation);
            Assert.Contains("count INCLUDES", compilation);
            Assert.Contains("count is REQUIRED", compilation);

            // A selection is spelled out verbatim rather than described, because the
            // profile refuses every predicate set but these (ADR-032) and a model
            // paraphrasing one produces a document the schema rejects.
            Assert.Contains("\"convexity\":\"convex\"", compilation);
            Assert.Contains("\"extreme_along\":\"axis.z\"", compilation);
            Assert.Contains("\"direction\":\"positive\"", compilation);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// The reading prompt asks for everything the claim can now check.
    /// </summary>
    /// <remarks>
    /// A claim field the reading stage is never told about is a field that arrives
    /// null on every run, and a check that never fires (ADR-032).
    /// </remarks>
    [Fact]
    public async Task TheAnalysisPromptAsksForEveryPartOfTheShapeTheClaimChecks()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var runner = new FakeRunner(AnalysisWithShape(), valid);
            await new DrawingPipeline(runner, engine: new StubValidatingEngine())
                .RunAsync(workspace, [image]);

            var analysis = runner.Prompts[0];
            foreach (var asked in new[]
                     {
                         "profile", "openings", "solids", "thickness_parameter",
                         "wall_parameter", "blends",
                     })
                Assert.Contains(asked, analysis);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// A wall and a set of blends reach the engine as part of the claim.
    /// </summary>
    [Fact]
    public async Task TheWallAndTheBlendsTheDrawingWasReadAsAreHandedToTheEngine()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var engine = new StubValidatingEngine();
            await new DrawingPipeline(
                new FakeRunner(AnalysisWithHollowShape(), valid), engine: engine)
                .RunAsync(workspace, [image]);

            var claim = JsonDocument.Parse(File.ReadAllText(engine.SawShapeClaim!)).RootElement;
            Assert.Equal("p_wall", claim.GetProperty("wall").GetString());
            var blends = claim.GetProperty("blends");
            Assert.Equal(1, blends.GetArrayLength());
            Assert.Equal("fillet", blends[0].GetProperty("kind").GetString());
            Assert.Equal(4, blends[0].GetProperty("count").GetInt32());
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// A reader who saw neither says neither, and the claim stays silent about both.
    /// </summary>
    /// <remarks>
    /// A `null` wall copied through would claim the part is hollow on behalf of
    /// somebody who did not say so, and an empty blend list is not a claim of zero.
    /// </remarks>
    [Fact]
    public async Task NothingSeenIsNothingClaimed()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var engine = new StubValidatingEngine();
            await new DrawingPipeline(
                new FakeRunner(AnalysisWithShape(), valid), engine: engine)
                .RunAsync(workspace, [image]);

            var claim = JsonDocument.Parse(File.ReadAllText(engine.SawShapeClaim!)).RootElement;
            Assert.False(claim.TryGetProperty("wall", out _));
            Assert.False(claim.TryGetProperty("blends", out _));
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    private static string AnalysisWithHollowShape() =>
        """
        {
          "schema_version":"0.1.0","stage":"drawing_analysis",
          "status":"success","confidence":1,"warnings":[],
          "result":{
            "ready_for_cad":true,"summary":"Housing 40 by 20 by 10, wall 2, R4 corners.",
            "parameters":[],
            "shape":{
              "profile":"rectangle",
              "openings":[],
              "solids":1,
              "thickness_parameter":"p_depth",
              "wall_parameter":"p_wall",
              "blends":[{"kind":"fillet","count":4}],
              "note":null
            },
            "questions":[]
          }
        }
        """;

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
              "wall_parameter":null,
              "blends":[],
              "note":null
            },
            "questions":[]
          }
        }
        """;

    /// <summary>
    /// A clarification round reuses the reading it was given, and does not look
    /// at the drawing again.
    /// </summary>
    /// <remarks>
    /// The vision call used to run before anything checked for answers, so every
    /// round re-read the image. Two costs: a second billed call, and a *fresh*
    /// set of question ids — the answers in hand are keyed by the old ones, so
    /// the compiling agent got values referring to questions that no longer
    /// existed, beside a reading nobody had answered.
    ///
    /// One runner call is the whole assertion: compilation, and no analysis.
    /// </remarks>
    [Fact]
    public async Task AClarificationRoundReusesTheReadingItWasGiven()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            Directory.CreateDirectory(Path.Combine(workspace, "context"));
            File.WriteAllText(
                Path.Combine(workspace, "context", "drawing-analysis.json"), ReadyAnalysis());
            var answers = Path.Combine(workspace, "context", "user-answers.json");
            File.WriteAllText(answers, """{"schema_version":"0.1.0","answers":[]}""");
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var runner = new FakeRunner(valid);

            var result = await new DrawingPipeline(runner, engine: new StubValidatingEngine())
                .RunAsync(workspace, [image], answers);

            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.Equal(1, runner.Calls);
            // Nothing was read this round, so nothing claims to have been.
            Assert.Null(result.AnalysisRun);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    /// <summary>
    /// With no reading carried in, the drawing is read — which is what an older
    /// API, or an order whose analysis could not be found, still produces.
    /// </summary>
    [Fact]
    public async Task WithNothingCarriedInTheDrawingIsReadAgain()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            Directory.CreateDirectory(Path.Combine(workspace, "context"));
            var answers = Path.Combine(workspace, "context", "user-answers.json");
            File.WriteAllText(answers, """{"schema_version":"0.1.0","answers":[]}""");
            var valid = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_10.json"));
            var runner = new FakeRunner(ReadyAnalysis(), valid);

            var result = await new DrawingPipeline(runner, engine: new StubValidatingEngine())
                .RunAsync(workspace, [image], answers);

            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.Equal(2, runner.Calls);
            Assert.NotNull(result.AnalysisRun);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

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

        /// <summary>Every prompt this runner was handed, in order.</summary>
        public List<string> Prompts { get; } = [];

        public async Task<CodexStageResult> RunAsync(
            CodexStageRequest request,
            CancellationToken cancellationToken = default)
        {
            Calls++;
            Prompts.Add(request.Prompt);
            var value = values.Dequeue();
            Directory.CreateDirectory(Path.GetDirectoryName(request.OutputPath)!);
            await File.WriteAllTextAsync(request.OutputPath, value, cancellationToken);
            var hash = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value)));
            return new(null, null, request.OutputPath, hash, Path.Combine(request.Workspace, "events.jsonl"));
        }
    }
}
