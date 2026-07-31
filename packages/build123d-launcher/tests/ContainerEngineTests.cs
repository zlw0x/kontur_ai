using CadAi.CadEngine;
using Xunit;

namespace CadAi.Build123dLauncher.Tests;

/// <summary>
/// The launcher against a real container runtime, in the mode production uses.
/// </summary>
/// <remarks>
/// Everything else about container mode is checked by reading the argument list
/// the launcher builds — which is the right way to test that `--read-only` is
/// there and cannot check the one thing that matters about it: whether a real
/// daemon accepts the whole invocation and whether the results come back out of
/// the bind mount. Those are two hand-written descriptions of one contract, and
/// nothing but this stands between them and a silent drift.
///
/// It skips itself unless `CAD_ENGINE_IMAGE` names an image, because building one
/// needs a machine that can pull a base image and a checkout cannot assume it. CI
/// builds the image and sets the variable; a developer machine that has done the
/// same gets the same coverage, and everywhere else the suite stays runnable.
/// </remarks>
public sealed class ContainerEngineTests
{
    private const string ImageVariable = "CAD_ENGINE_IMAGE";

    private sealed class ContainerFactAttribute : FactAttribute
    {
        public ContainerFactAttribute()
        {
            if (Image is null)
                Skip = $"{ImageVariable} is unset, so there is no engine image to run";
        }
    }

    private static string? Image =>
        Environment.GetEnvironmentVariable(ImageVariable) is { Length: > 0 } value ? value : null;

    private static EngineLaunchOptions Options() => new()
    {
        Runtime = EngineRuntime.Container,
        Image = Image!,
        ContainerCommand =
            Environment.GetEnvironmentVariable("CAD_ENGINE_CONTAINER_COMMAND") ?? "docker",
    };

    private static string Root
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "AGENTS.md")))
                directory = directory.Parent;
            return directory?.FullName ?? throw new InvalidOperationException("no repository root");
        }
    }

    private static string JobWith(string fixture)
    {
        var job = Directory.CreateTempSubdirectory("cad-container-").FullName;
        File.Copy(
            Path.Combine(Root, "tests", "fixtures", "cad-ir", fixture),
            Path.Combine(job, "cad-ir.json"));
        return job;
    }

    [ContainerFact]
    public async Task TheImageDescribesItselfThroughTheLauncher()
    {
        var report = await new Build123dProcessEngine(Options()).DescribeAsync(
            [], CancellationToken.None);

        Assert.Equal("build123d", report.Engine.EngineId);
        Assert.Equal("opencascade", report.Engine.KernelId);
        Assert.Equal(["STEP", "STL"], report.Engine.Artifacts.Select(item => item.Kind));
        // The worker believes nothing the engine says about its own flags, so the
        // manifest it publishes has to arrive intact through the container boundary.
        Assert.NotEmpty(report.Capabilities);
    }

    [ContainerFact]
    public async Task AJobBuildsInsideTheContainerAndTheResultsComeBackOutOfTheMount()
    {
        var job = JobWith("lever-plate.v1_7.json");

        var result = await new Build123dProcessEngine(Options()).BuildAsync(
            new CadDocumentBuildRequest(job, []), CancellationToken.None);

        // Written by a process in a container with a read-only root, into the one
        // directory it was given, and read back here by digest.
        Assert.Equal(["STEP", "STL"], result.Artifacts.Select(item => item.Kind));
        foreach (var artifact in result.Artifacts)
        {
            var path = Path.Combine(job, "output", Path.GetFileName(artifact.Path));
            Assert.True(File.Exists(path), path);
            Assert.Equal(new FileInfo(path).Length, artifact.SizeBytes);
        }
    }

    [ContainerFact]
    public async Task AShapeClaimReachesTheEngineThroughItsOwnReadOnlyMount()
    {
        var job = JobWith("lever-plate.v1_7.json");
        var claim = Path.Combine(Directory.CreateTempSubdirectory("cad-claim-").FullName,
                                 "shape-claim.json");
        File.WriteAllText(claim, """{"profile":"rectangle","solids":3}""");

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            new Build123dProcessEngine(Options()).ValidateAsync(
                new CadDocumentValidateRequest(job, [], claim), CancellationToken.None));

        // The claim is mounted at its own path inside the container (ADR-025), so a
        // misread outline is contradicted there rather than here.
        Assert.Equal("SHAPE_CLAIM_CONTRADICTED", refused.Code);
        Assert.Contains("rectangle", refused.SafeMessage);
    }

    [ContainerFact]
    public async Task AFlagTheOperatorSetIsObeyedInsideTheContainer()
    {
        var job = JobWith("lever-plate.v1_7.json");

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            new Build123dProcessEngine(Options()).BuildAsync(
                new CadDocumentBuildRequest(job, ["sketch.arc"]), CancellationToken.None));

        Assert.Equal("CAPABILITY_DISABLED", refused.Code);
        Assert.Contains("sketch.arc", refused.SafeMessage);
        Assert.False(Directory.Exists(Path.Combine(job, "output")),
                     "a refused build leaves nothing behind");
    }
}
