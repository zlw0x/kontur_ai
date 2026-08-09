using CadAi.CadEngine;
using CadAi.CodexRunner;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// What an online order is actually handed, as opposed to what a hand-run one is.
/// </summary>
/// <remarks>
/// Every other test in this project supplies the pipeline an engine of its own —
/// <see cref="StubValidatingEngine"/> — and is therefore blind to what a *caller*
/// assembles. That blind spot cost a milestone's worth of checking.
///
/// The claim loop built its pipeline with no engine and no feature flags.
/// `DrawingPipeline.ValidateAsync` opens with `if (engine is null) return;`, and
/// its own comment says a missing engine "is only ever the case in a test: every
/// real path passes one in". The claim loop is the path every online order takes.
/// So for every order that arrived through the web: the trusted semantic gate
/// never ran on the generated document, the shape claim was written and never
/// read, the compile-stage repair loop could not fire, and an operator's rollback
/// of an operation was not applied to validation.
///
/// None of it showed up in a run, because the nine acceptance runs used
/// `analyze-drawing`, which passes both. A defect that only exists on the path
/// nobody exercises by hand is exactly what a wiring test is for.
///
/// These assert the assembly, not the behaviour. What the engine then does with
/// the document is `DrawingPipelineTests` and `DocumentEngineJobTests`; that it is
/// *there to do it* is here.
/// </remarks>
public sealed class ClaimedJobWiringTests : IDisposable
{
    private readonly string root = Path.Combine(
        Path.GetTempPath(), $"cad-ai-wiring-{Guid.NewGuid():N}");

    private WorkerPaths Paths() => new(
        StateRoot: root,
        WorkspaceRoot: Path.Combine(root, "work"),
        ConfigPath: Path.Combine(root, "config.json"),
        CredentialPath: Path.Combine(root, "credential.bin"));

    public void Dispose()
    {
        if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
    }

    private DrawingPipeline Build() =>
        ClaimLoop.CreateDrawingPipeline(
            Paths(),
            // `fake: true` keeps this off a container and a real interpreter. The
            // question here is whether an engine arrives, not which one.
            WorkerEngine.EngineSelection.For(config: null, fake: true),
            new ResourceLedger("job-wiring", 1),
            // And a stub runner for the same reason: constructing a real
            // LocalCodexRunner searches the machine for the CLI and throws when it
            // is absent, so these three assertions could only run where Codex is
            // installed. Whether this machine can reach a model is not the question.
            new UnusedRunner());

    /// <summary>A runner these tests never call. They assert assembly, not a run.</summary>
    private sealed class UnusedRunner : ICodexRunner
    {
        public Task<CodexStageResult> RunAsync(
            CodexStageRequest request, CancellationToken cancellationToken = default) =>
            throw new InvalidOperationException("a wiring test does not run a stage");
    }

    /// <summary>
    /// The claimed-job pipeline is given something to check the document against.
    /// </summary>
    /// <remarks>
    /// The one assertion that would have caught it. A null here is not a crash and
    /// not a slow path — it is every check downstream quietly agreeing with
    /// whatever the model wrote.
    /// </remarks>
    [Fact]
    public void AnOnlineOrderIsCheckedAgainstAnEngine()
    {
        Assert.NotNull(Build().ValidatingEngine);
    }

    /// <summary>
    /// A rollback the operator performed reaches the check, not only the build.
    /// </summary>
    /// <remarks>
    /// Half-applied flags are worse than none. Validation would accept a document
    /// using a disabled operation and the build would then refuse it — the repair
    /// loop caused by two halves of this worker disagreeing that
    /// `DrawingPipeline`'s own remarks warn about.
    /// </remarks>
    [Fact]
    public void AnOperatorsRollbackReachesTheCheckAndNotOnlyTheBuild()
    {
        Directory.CreateDirectory(root);
        File.WriteAllText(
            Path.Combine(root, FeatureFlags.FileName),
            """{"version":1,"disabled":["feature.shell"]}""");

        Assert.Contains("feature.shell", Build().DisabledCapabilities);
    }

    /// <summary>
    /// With no flag file, nothing is disabled.
    /// </summary>
    /// <remarks>
    /// The other direction, and the one that matters on a fresh machine: a missing
    /// file must not read as "everything is off". `FeatureFlagsTests` pins that for
    /// the file; this pins that the claim loop does not add anything of its own on
    /// the way.
    /// </remarks>
    [Fact]
    public void WithNoFlagFileTheOnlineOrderDisablesNothing()
    {
        Assert.Empty(Build().DisabledCapabilities);
    }

    /// <summary>
    /// The version a worker offers is the engine's, not this build's constant.
    /// </summary>
    /// <remarks>
    /// Found by a real order through the web path. `supported_cad_ir` decides whether
    /// the API leases a job at all, and it was `WorkerCapabilities.CadIrVersion` --
    /// the constant compiled into this worker. The manifest sent in the same request
    /// carried the version the *engine* reports, and nothing compared the two.
    ///
    /// So a worker built for CAD-IR 1.12 with a container image that speaks 1.11 was
    /// leased a 1.12 job. It paid for the reading and the compilation, and the engine
    /// refused the document with `CAD_IR_VERSION_TOO_NEW@$.schema_version`. The check
    /// that would have withheld the job existed and was reading the wrong number.
    ///
    /// The engine's answer wins, for the reason the launcher compares digests against
    /// the bytes on disk: what a component *is* beats what something upstream believes
    /// about it.
    /// </remarks>
    [Fact]
    public void TheManifestAndTheOfferNameTheSameCadIrVersion()
    {
        var report = new CadEngineReport(
            new CadEngineDescription(
                "build123d", "0.11.1", "OpenCascade", "7.9.3",
                // An engine image older than this worker build, which is the case
                // the real run hit.
                CadIrVersion: "1.11",
                Artifacts: []),
            new Dictionary<string, CadCapabilityDeclaration>(StringComparer.Ordinal)
            {
                ["solid.extrude"] = new("beta", "1.0"),
            });

        var manifest = WorkerCapabilities.ManifestFor(report);

        Assert.Equal(["1.11"], manifest.CadIrVersions);
        // And it is deliberately *not* the constant this worker was built with: the
        // whole defect was the two being allowed to differ.
        Assert.NotEqual(WorkerCapabilities.CadIrVersion, manifest.CadIrVersions[0]);
    }
}
