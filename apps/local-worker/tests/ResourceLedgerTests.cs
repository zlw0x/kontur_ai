using System.Security.Cryptography;
using System.Text;
using CadAi.CodexRunner;
using CadAi.KompasAdapter;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

public sealed class ResourceLedgerTests
{
    [Fact]
    public void ScopeRecordsWallTimeAndOutcome()
    {
        var ledger = new ResourceLedger("job-1");
        using (var scope = ledger.Begin(
            ledger.Key("cad", "session", "1"), ResourceEventType.CAD_SESSION, ResourceStage.KOMPAS_STARTUP))
        {
            Thread.Sleep(5);
            scope.Succeeded();
        }

        var recorded = Assert.Single(ledger.Events);
        Assert.Equal("job:job-1:attempt:1:cad:session:1", recorded.EventKey);
        Assert.Equal("CAD_SESSION", recorded.EventType);
        Assert.True(recorded.Success);
        Assert.Null(recorded.FailureCode);
        Assert.NotNull(recorded.WallMs);
        Assert.True(recorded.WallMs >= 1);
        Assert.NotNull(recorded.FinishedAt);
        Assert.True(recorded.FinishedAt >= recorded.StartedAt);
    }

    [Fact]
    public void AStageThatThrowsIsStillRecordedAsAFailure()
    {
        var ledger = new ResourceLedger("job-1");

        // Typed explicitly: a lambda that always throws is convertible to any
        // delegate, and xUnit would bind the obsolete Func<Task> overload.
        Action failing = () =>
        {
            using var scope = ledger.Begin(
                ledger.Key("cad", "session", "1"), ResourceEventType.CAD_SESSION, ResourceStage.DOCUMENT_BUILD);
            throw new InvalidOperationException("boom");
        };
        Assert.Throws<InvalidOperationException>(failing);

        var recorded = Assert.Single(ledger.Events);
        // Silence here would hide the cost of exactly the runs worth explaining.
        Assert.False(recorded.Success);
        Assert.Equal("UNCAUGHT_ERROR", recorded.FailureCode);
    }

    [Fact]
    public void ExplicitFailureCodeSurvivesToTheEvent()
    {
        var ledger = new ResourceLedger("job-1");
        using (var scope = ledger.Begin(
            ledger.Key("validate", "geometry", "1"),
            ResourceEventType.VALIDATION,
            ResourceStage.GEOMETRY_VALIDATION))
        {
            scope.Failed("GEOMETRY_VALIDATION_FAILED");
        }

        Assert.Equal("GEOMETRY_VALIDATION_FAILED", Assert.Single(ledger.Events).FailureCode);
    }

    [Fact]
    public void EventKeysAreDeterministicSoAResendIsARelay()
    {
        var first = new ResourceLedger("job-1");
        var second = new ResourceLedger("job-1");

        Assert.Equal(
            first.Key("ai", "drawing_analysis", "1"),
            second.Key("ai", "drawing_analysis", "1"));
    }

    [Fact]
    public void ARetriedAttemptGetsItsOwnKeysRatherThanCollidingWithTheFirst()
    {
        // Found by the acceptance run's recovery test. A retry re-measures the
        // same stages; sharing keys with the abandoned attempt would make the
        // ledger reject the whole batch as a collision and lose the retry's
        // measurements silently.
        var firstAttempt = new ResourceLedger("job-1", attempt: 1);
        var secondAttempt = new ResourceLedger("job-1", attempt: 2);

        Assert.NotEqual(
            firstAttempt.Key("ai", "drawing_analysis", "1"),
            secondAttempt.Key("ai", "drawing_analysis", "1"));
        Assert.Contains(":attempt:2:", secondAttempt.Key("ai", "drawing_analysis", "1"));
    }

    [Fact]
    public void TheRecordedAttemptMatchesTheAttemptTheJobIsOn()
    {
        var ledger = new ResourceLedger("job-1", attempt: 3);
        using (var scope = ledger.Begin(
            ledger.Key("cad", "session", "1"), ResourceEventType.CAD_SESSION, ResourceStage.KOMPAS_STARTUP))
        {
            scope.Succeeded();
        }

        Assert.Equal(3, Assert.Single(ledger.Events).AttemptNo);
    }

    [Fact]
    public void UnknownCodexUsageIsReportedAsUnknownNotAsZero()
    {
        var result = new CodexStageResult(
            "thread-1", null, "out.json", "SHA", "events.jsonl",
            new CodexUsageResolution(CodexUsageReading.Unknown, null, KnownCliVersion: true));

        var usage = result.ToAiUsage("drawing-mvp-2");

        Assert.Equal("UNKNOWN", usage.TokenSource);
        Assert.Null(usage.InputTokens);
        Assert.Null(usage.OutputTokens);
        Assert.Null(usage.TotalTokens);
    }

    [Fact]
    public void MeasuredCodexUsageCarriesItsSourceAndCounts()
    {
        var reading = new CodexUsageReading(CodexTokenSource.Structured, 1000, 400, 90, 30, 1090);
        var result = new CodexStageResult(
            "thread-1", null, "out.json", "SHA", "events.jsonl",
            new CodexUsageResolution(reading, "structured-jsonl", KnownCliVersion: true),
            new CodexProcessMetrics(120, 40, 900_000, 0),
            "codex-cli 0.145.0",
            "gpt-5.6-terra",
            "medium");

        var usage = result.ToAiUsage("drawing-mvp-2");
        Assert.Equal("STRUCTURED", usage.TokenSource);
        Assert.Equal(1000, usage.InputTokens);
        Assert.Equal(400, usage.CachedInputTokens);
        Assert.Equal("gpt-5.6-terra", usage.RequestedModel);
        Assert.Equal("medium", usage.RequestedReasoningEffort);
        Assert.Equal("drawing-mvp-2", usage.PromptVersion);
        Assert.Equal("codex-cli 0.145.0", usage.CliVersion);
        // The CLI reported no model, so the request is all that is confirmed.
        Assert.Null(usage.ObservedModel);
        Assert.Equal("EXPLICIT_NOT_REPORTED", usage.ModelObservationStatus);

        var process = result.ToProcessUsage();
        Assert.NotNull(process);
        Assert.Equal(120, process.CpuUserMs);
        Assert.Equal(900_000, process.PeakMemoryBytes);
    }

    [Fact]
    public void WarningsAreRecordedWithoutFailingAnything()
    {
        var ledger = new ResourceLedger("job-1");
        ledger.Warn("job:job-1:ai:1:usage-warning", ResourceStage.DRAWING_ANALYSIS,
            "CODEX_USAGE_UNRESOLVED", "cli=codex-cli 9.9.9 source=Unknown");

        var recorded = Assert.Single(ledger.Events);
        Assert.Equal("WARNING", recorded.EventType);
        Assert.True(recorded.Success);
        Assert.Equal("CODEX_USAGE_UNRESOLVED", recorded.Metadata["code"]);
    }

    [Fact]
    public void LongDetailIsBoundedBeforeItReachesTheApi()
    {
        var ledger = new ResourceLedger("job-1");
        ledger.Warn("job:job-1:w", ResourceStage.CLEANUP, "CODE", new string('x', 5_000));

        Assert.Equal(500, Assert.Single(ledger.Events).Metadata["detail"].Length);
    }

    [Fact]
    public async Task DrawingPipelineRecordsAnAiRunPerCodexStage()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var ledger = new ResourceLedger("job-1");
            var valid = await File.ReadAllTextAsync(
                Path.Combine(FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_1.json"));
            var runner = new FakeRunner(ReadyAnalysis(), valid);

            var result = await new DrawingPipeline(runner, ledger: ledger).RunAsync(workspace, [image]);

            Assert.Equal("CAD_IR_READY", result.Status);
            var aiRuns = ledger.Events.Where(item => item.EventType == "AI_RUN").ToArray();
            Assert.Equal(2, aiRuns.Length);
            Assert.Contains(aiRuns, item => item.AgentRole == "DRAWING_EXTRACTION");
            Assert.Contains(aiRuns, item => item.AgentRole == "CAD_IR_COMPILATION");
            Assert.Contains(ledger.Events, item => item.EventType == "VALIDATION" && item.Success);
            Assert.All(aiRuns, item => Assert.Equal("drawing-mvp-2", item.Ai!.PromptVersion));
            // Every run names the model the routing profile chose, and carries
            // the profile version that chose it.
            Assert.All(aiRuns, item => Assert.Equal("gpt-5.6-terra", item.Ai!.RequestedModel));
            Assert.All(aiRuns, item => Assert.Equal(
                CodexRoutingProfile.CurrentVersion, item.Ai!.RoutingProfileVersion));
            Assert.All(aiRuns, item => Assert.NotNull(item.Ai!.ProvenanceSha256));
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    [Fact]
    public async Task ARepairLoopIsVisibleAsIterationsAndAFailedValidation()
    {
        var workspace = Workspace();
        try
        {
            var image = CreateImagePlaceholder(workspace);
            var ledger = new ResourceLedger("job-1");
            var valid = await File.ReadAllTextAsync(
                Path.Combine(FindRepositoryRoot(), "tests", "fixtures", "cad-ir", "plate.v1_1.json"));
            var invalid = valid.Replace(
                @"""type"": ""solid.extrude""", @"""type"": ""cut.extrude""", StringComparison.Ordinal);
            var runner = new FakeRunner(ReadyAnalysis(), invalid, valid);

            await new DrawingPipeline(runner, ledger: ledger).RunAsync(workspace, [image]);

            Assert.Single(ledger.Events, item => item.EventType == "REPAIR_ITERATION");
            Assert.Single(ledger.Events, item => item.AgentRole == "REPAIR");
            // The rejected candidate must be visible, not just the retry.
            var validations = ledger.Events.Where(item => item.EventType == "VALIDATION").ToArray();
            Assert.Contains(validations, item => !item.Success);
            Assert.Contains(validations, item => item.Success);
        }
        finally { Directory.Delete(workspace, recursive: true); }
    }

    [Fact]
    public void FailedCadOperationsTravelOutWithTheException()
    {
        var measured = new[]
        {
            new CadOperationRecord("kompas_startup", "activation", 4_000, true),
            new CadOperationRecord("FEATURE_FAILED", "feature", 900, false, "FEATURE_FAILED")
        };
        var error = new CadAdapterException("FEATURE_FAILED", "feature", "safe").WithOperations(measured);

        // A build that dies after four seconds of startup still consumed them.
        Assert.Equal(2, error.Operations.Count);
        Assert.Equal(4_000, error.Operations[0].WallMs);
        Assert.False(error.Operations[1].Success);
    }

    [Fact]
    public void TheCapabilityManifestDeclaresOnlyTheConfirmedMvpVocabulary()
    {
        var manifest = WorkerCapabilities.Manifest("22.0", "codex-cli 0.145.0");

        Assert.Equal("1.0", manifest.SchemaVersion);
        Assert.Equal([WorkerCapabilities.CadIrVersion], manifest.CadIrVersions);
        Assert.Equal("stable", manifest.Capabilities["solid.rectangular_prism"].Status);
        Assert.Equal("1.0", manifest.Capabilities["solid.rectangular_prism"].Version);
        Assert.Equal("stable", manifest.Capabilities["feature.hole.simple_through"].Status);
        // Nothing beyond the confirmed MVP may be advertised: a key here tells
        // the API to start scheduling that operation on this machine.
        Assert.DoesNotContain("solid.revolve", manifest.Capabilities.Keys);
        Assert.DoesNotContain("feature.shell", manifest.Capabilities.Keys);
        Assert.Equal(8, manifest.Capabilities.Count);
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
        var path = Path.Combine(Path.GetTempPath(), $"cad-ai-ledger-{Guid.NewGuid():N}");
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

        public async Task<CodexStageResult> RunAsync(
            CodexStageRequest request,
            CancellationToken cancellationToken = default)
        {
            var value = values.Dequeue();
            Directory.CreateDirectory(Path.GetDirectoryName(request.OutputPath)!);
            await File.WriteAllTextAsync(request.OutputPath, value, cancellationToken);
            var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
            return new CodexStageResult(
                "thread-1", null, request.OutputPath, hash,
                Path.Combine(request.Workspace, "events.jsonl"),
                new CodexUsageResolution(
                    new CodexUsageReading(CodexTokenSource.Structured, 1000, 200, 50, 10, 1060),
                    "structured-jsonl",
                    KnownCliVersion: true),
                new CodexProcessMetrics(50, 10, 400_000, 0),
                "codex-cli 0.145.0",
                request.Model,
                request.ReasoningEffort,
                request.Routing,
                CodexModelObservation.Compare(request.Model, null, request.ReasoningEffort, null),
                request.Routing is null || request.PromptBundleSha256 is null
                    ? null
                    : CodexProvenance.Fingerprint(
                        hash, request.PromptBundleSha256, request.Routing, "codex-cli 0.145.0"));
        }
    }
}
