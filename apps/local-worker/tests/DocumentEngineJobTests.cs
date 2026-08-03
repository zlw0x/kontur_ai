using System.Text.Json;
using CadAi.Build123dLauncher;
using CadAi.CadEngine;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// A job built by the engine that reads the document itself (ENGINE-MIG-007).
/// </summary>
/// <remarks>
/// The branch matters more than the build. A worker with two engines has to send
/// each job to the one it was configured for, hand it the flags the operator set,
/// and produce the same envelope either way — and it must never quietly fall back
/// to the other engine, because the two produce different files from the same
/// document and a customer would be the one to notice.
/// </remarks>
public sealed class DocumentEngineJobTests
{
    /// <summary>An engine that writes what a real one writes, and nothing more.</summary>
    private sealed class StubEngine(bool refuse = false) : ICadDocumentEngine
    {
        public IReadOnlyCollection<string>? SawDisabled { get; private set; }
        public string? SawJobDirectory { get; private set; }

        public Task<CadEngineReport> DescribeAsync(
            IReadOnlyCollection<string> disabledCapabilities, CancellationToken cancellationToken) =>
            Task.FromResult(new CadEngineReport(Identity(), new Dictionary<string, CadCapabilityDeclaration>
            {
                ["solid.rectangular_prism"] = new("beta", "1.0"),
                ["solid.revolve"] = new("experimental", "1.0"),
                ["sketch.slot"] = new(
                    disabledCapabilities.Contains("sketch.slot") ? "disabled" : "beta", "1.0")
            }));

        public Task<IReadOnlyCollection<string>> ValidateAsync(
            CadDocumentValidateRequest request, CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyCollection<string>>(["solid.rectangular_prism"]);

        public Task<CadBuildResult> BuildAsync(
            CadDocumentBuildRequest request, CancellationToken cancellationToken)
        {
            SawJobDirectory = request.JobDirectory;
            SawDisabled = request.DisabledCapabilities;
            if (refuse)
                throw new CadAdapterException(
                    "CAPABILITY_DISABLED", "cad-ir", "the arc in sketch.plate needs sketch.arc.");

            var output = Directory.CreateDirectory(Path.Combine(request.JobDirectory, "output")).FullName;
            File.WriteAllText(Path.Combine(output, "model.step"), "ISO-10303-21;");
            File.WriteAllText(Path.Combine(output, "model.stl"), "solid");
            // The engine writes its own report; this side is expected to carry it
            // through rather than restate it.
            File.WriteAllText(
                Path.Combine(output, "validation-report.json"),
                """{"valid":true,"checks":[{"name":"positive_volume","passed":true,"detail":"8000 mm3."}]}""");
            return Task.FromResult(new CadBuildResult(
                [
                    CadArtifact.Read("STEP", Path.Combine(output, "model.step")),
                    CadArtifact.Read("STL", Path.Combine(output, "model.stl"))
                ],
                [new CadOperationRecord("document_build", "feature", 12, Success: true)],
                Identity()));
        }

        private static CadEngineDescription Identity() => new(
            "build123d", "0.11.1", "opencascade", "7.9.3.1.1", WorkerCapabilities.CadIrVersion,
            [new CadArtifactKind("STEP", "model.step"), new CadArtifactKind("STL", "model.stl")]);
    }

    private static string JobWith(string fixture)
    {
        var job = Directory.CreateTempSubdirectory("cad-job-").FullName;
        File.Copy(
            Path.Combine(RepositoryRoot(), "tests", "fixtures", "cad-ir", fixture),
            Path.Combine(job, "cad-ir.json"));
        return job;
    }

    private static string RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "CadAi.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("no repository root");
    }

    private static WorkerPaths PathsIn(string root) =>
        new(root, Path.Combine(root, "jobs"), Path.Combine(root, "worker.json"),
            Path.Combine(root, "credential.dpapi"));

    [Fact]
    public async Task AJobBuiltByTheDocumentEngineProducesTheSameEnvelope()
    {
        var job = JobWith("plate.v1_11.json");
        var engine = new StubEngine();

        var code = await LocalCadJobHandler.RunAsync(job, PathsIn(job), engine);

        Assert.Equal(0, code);
        Assert.Equal(job, engine.SawJobDirectory);

        var state = JsonDocument.Parse(File.ReadAllText(Path.Combine(job, "state.json")));
        Assert.Equal("COMPLETED", state.RootElement.GetProperty("status").GetString());

        var report = JsonDocument.Parse(
            File.ReadAllText(Path.Combine(job, "output", "validation-report.json"))).RootElement;
        Assert.Equal("build123d", report.GetProperty("adapter").GetString());
        Assert.Equal("opencascade", report.GetProperty("engine").GetProperty("kernel_id").GetString());
        Assert.Equal(2, report.GetProperty("artifacts").GetArrayLength());
        // The engine's own measurements are carried through whole. Restating
        // them as a boolean here would throw away the only evidence anyone has
        // that the model is right.
        Assert.True(report.GetProperty("geometry").GetProperty("valid").GetBoolean());
        Assert.Equal(
            "positive_volume",
            report.GetProperty("geometry").GetProperty("checks")[0].GetProperty("name").GetString());
    }

    [Fact]
    public async Task TheOperatorsFlagsTravelWithTheJob()
    {
        var job = JobWith("plate.v1_11.json");
        var paths = PathsIn(job);
        var flags = FeatureFlags.AllEnabled;
        flags.Disable("sketch.slot");
        flags.Save(paths);
        var engine = new StubEngine();

        await LocalCadJobHandler.RunAsync(job, paths, engine);

        // The rollback switch is on the worker and the engine is a container
        // started per job, so the only way a flag reaches the thing that builds
        // is if this hands it over.
        Assert.Equal(["sketch.slot"], engine.SawDisabled);
    }

    [Fact]
    public async Task ARefusedBuildFailsTheJobAndLeavesNoOutputBehind()
    {
        var job = JobWith("plate.v1_11.json");
        var refused = await Assert.ThrowsAsync<WorkerException>(() =>
            LocalCadJobHandler.RunAsync(job, PathsIn(job), new StubEngine(refuse: true)));

        Assert.Equal("CAPABILITY_DISABLED", refused.Code);
        var state = JsonDocument.Parse(File.ReadAllText(Path.Combine(job, "state.json")));
        Assert.Equal("FAILED", state.RootElement.GetProperty("status").GetString());
        Assert.Equal("CAPABILITY_DISABLED", state.RootElement.GetProperty("code").GetString());
        // An empty `output/` beside a failed job reads like a build that ran.
        Assert.False(Directory.Exists(Path.Combine(job, "output")));
    }

    [Fact]
    public async Task TheFakeEngineFinishesAJobAndProducesNothingDeliverable()
    {
        // `--fake-cad` is how CI and the smoke test exercise the lease, the
        // ledger and the upload path with no engine at all. The one file it
        // writes is named for what it is, so nothing downstream can mistake it
        // for a model.
        var job = JobWith("plate.v1_11.json");

        var code = await LocalCadJobHandler.RunAsync(
            job, PathsIn(job), new FakeDocumentEngine(WorkerCapabilities.CadIrVersion));

        Assert.Equal(0, code);
        Assert.True(File.Exists(Path.Combine(job, "output", FakeDocumentEngine.FileName)));
        Assert.False(File.Exists(Path.Combine(job, "output", "model.step")));
    }

    // --- what the worker publishes ------------------------------------------

    [Fact]
    public async Task TheManifestOfADocumentEngineWorkerComesFromTheEngine()
    {
        var report = await new StubEngine().DescribeAsync([], default);
        var manifest = WorkerCapabilities.ManifestFor(report, codexCliVersion: "1.2.3");

        Assert.Equal("build123d", manifest.Engine!.EngineId);
        Assert.Equal("opencascade", manifest.Engine.KernelId);
        Assert.Equal("7.9.3.1.1", manifest.Engine.KernelVersion);
        Assert.Equal(["1.11"], manifest.CadIrVersions);
        Assert.Equal("1.2.3", manifest.CodexCliVersion);

        // Straight from the engine, including the maturity it decides. Nothing
        // KOMPAS-only appears, because the engine never declared it.
        Assert.Equal("experimental", manifest.Capabilities["solid.revolve"].Status);
        Assert.DoesNotContain("export.m3d", manifest.Capabilities.Keys);
    }

    [Fact]
    public async Task AFlagReachesTheManifestAndTheBuildFromOneSource()
    {
        var flags = FeatureFlags.AllEnabled;
        flags.Disable("sketch.slot");
        var report = await new StubEngine().DescribeAsync([.. flags.Disabled], default);

        Assert.Equal("disabled", WorkerCapabilities.ManifestFor(report).Capabilities["sketch.slot"].Status);
    }

    // --- choosing an engine --------------------------------------------------

    [Fact]
    public void ThereIsOneRealEngineAndAWorkerWithNoConfigurationStillGetsIt()
    {
        // A container by default, which is the mode with the isolation ADR-023
        // asks for. A worker enrolled before the setting existed does not have to
        // be reconfigured to keep working.
        Assert.IsType<Build123dProcessEngine>(WorkerEngine.Select(null));
        Assert.IsType<Build123dProcessEngine>(WorkerEngine.Select(new CadEngineConfig()));
        Assert.Equal("container", new CadEngineConfig().Runtime);
    }

    [Fact]
    public void AskingForTheFakeGetsTheFakeWhateverIsConfigured()
    {
        Assert.IsType<FakeDocumentEngine>(
            WorkerEngine.Select(new CadEngineConfig(), fake: true));
    }

    [Fact]
    public void ARuntimeNobodyImplementsIsRefusedRatherThanGuessedAt()
    {
        var refused = Assert.Throws<WorkerException>(() =>
            WorkerEngine.Select(new CadEngineConfig(Runtime: "kubernetes")));
        Assert.Equal("CONFIG_INVALID", refused.Code);
    }
}
