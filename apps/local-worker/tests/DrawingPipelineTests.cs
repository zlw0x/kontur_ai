using System.Security.Cryptography;
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
            var result = await new DrawingPipeline(runner).RunAsync(workspace, [image]);
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
                "tests", "fixtures", "cad-ir", "plate.json"));
            var invalid = valid.Replace(
                @"""type"": ""extrude_add""",
                @"""type"": ""hole""",
                StringComparison.Ordinal);
            var runner = new FakeRunner(ReadyAnalysis(), invalid, valid);
            var result = await new DrawingPipeline(runner).RunAsync(workspace, [image]);
            Assert.Equal("CAD_IR_READY", result.Status);
            Assert.NotNull(result.CadIrPath);
            Assert.Equal(3, runner.Calls);
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
