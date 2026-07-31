using System.Diagnostics;
using CadAi.CadEngine;
using Xunit;

namespace CadAi.Build123dLauncher.Tests;

/// <summary>
/// The launcher against the engine it was written for.
/// </summary>
/// <remarks>
/// Everything else in this project runs against a stub, which is right for the
/// failure cases and useless for the one thing a stub cannot check: that the two
/// sides agree on the wire. The C# records here and the dictionaries the Python
/// worker prints are two hand-written descriptions of one format, in two
/// languages, in two directories, with nothing but this test between them and a
/// silent drift.
///
/// It runs in process mode, because a container image is a deployment artifact
/// and CI builds neither. Skipped where the engine is not installed, which keeps
/// the .NET suite runnable on a machine with no Python at all — the same property
/// the Python suite keeps for a machine with no CAD library.
/// </remarks>
public sealed class RealEngineTests
{
    /// <summary>A fact that skips itself when the engine is not installed.</summary>
    private sealed class EngineFactAttribute : FactAttribute
    {
        public EngineFactAttribute()
        {
            if (!RealEngine.Available)
                Skip = "the build123d engine is not installed on this machine";
        }
    }

    private static class RealEngine
    {
        private static readonly Lazy<string?> Interpreter = new(Probe);

        public static bool Available => Interpreter.Value is not null;

        public static EngineLaunchOptions Options() => new()
        {
            Runtime = EngineRuntime.Process,
            PythonCommand = Interpreter.Value!,
            WorkingDirectory = Root,
            Environment = new Dictionary<string, string>
            {
                // What the image bakes in, spelled out for a checkout.
                ["PYTHONPATH"] = string.Join(
                    Path.PathSeparator,
                    Path.Combine(Root, "packages", "cad-ir"),
                    Path.Combine(Root, "packages", "build123d-adapter"),
                    Path.Combine(Root, "apps", "cad-worker"))
            }
        };

        /// <summary>The first interpreter that can import the engine, or none.</summary>
        private static string? Probe()
        {
            foreach (var candidate in new[] { "python3", "python" })
            {
                try
                {
                    var start = new ProcessStartInfo(candidate)
                    {
                        ArgumentList = { "-c", "import build123d" },
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        UseShellExecute = false,
                        CreateNoWindow = true
                    };
                    using var process = Process.Start(start);
                    if (process is null) continue;
                    if (!process.WaitForExit(milliseconds: 120_000)) continue;
                    if (process.ExitCode == 0) return candidate;
                }
                catch (Exception error) when (error is not OutOfMemoryException)
                {
                    // No such binary on this machine. Try the next spelling.
                }
            }
            return null;
        }

        public static string Root { get; } = FindRoot();

        private static string FindRoot()
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "CadAi.sln")))
                directory = directory.Parent;
            return directory?.FullName
                ?? throw new InvalidOperationException("the repository root was not found");
        }
    }

    private static string JobWith(string fixture)
    {
        var job = Directory.CreateTempSubdirectory("cad-real-").FullName;
        File.Copy(
            Path.Combine(RealEngine.Root, "tests", "fixtures", "cad-ir", fixture),
            Path.Combine(job, "cad-ir.json"));
        return job;
    }

    [EngineFact]
    public async Task TheEngineDescribesItselfInTheShapeThisSideParses()
    {
        var report = await new Build123dProcessEngine(RealEngine.Options())
            .DescribeAsync([], CancellationToken.None);

        Assert.Equal("build123d", report.Engine.EngineId);
        Assert.Equal("opencascade", report.Engine.KernelId);
        Assert.Equal("1.7", report.Engine.CadIrVersion);
        Assert.NotEmpty(report.Engine.EngineVersion);
        Assert.Equal(["STEP", "STL"], report.Engine.Artifacts.Select(item => item.Kind));

        // Maturity, straight from the engine that decides it. Revolve is
        // experimental, which the API refuses on an ordinary claim.
        Assert.Equal("beta", report.Capabilities["sketch.arc"].Status);
        Assert.Equal("experimental", report.Capabilities["solid.revolve"].Status);
    }

    [EngineFact]
    public async Task AFlagPassedToTheRealEngineComesBackAppliedInItsManifest()
    {
        var report = await new Build123dProcessEngine(RealEngine.Options())
            .DescribeAsync(["sketch.slot"], CancellationToken.None);

        Assert.Equal("disabled", report.Capabilities["sketch.slot"].Status);
        Assert.Equal("beta", report.Capabilities["sketch.arc"].Status);
    }

    [EngineFact]
    public async Task ARealFixtureBuildsAndTheArtifactsMatchWhatTheEngineReported()
    {
        var job = JobWith("lever-plate.v1_7.json");
        var result = await new Build123dProcessEngine(RealEngine.Options())
            .BuildAsync(new CadDocumentBuildRequest(job, []), CancellationToken.None);

        Assert.Equal(["STEP", "STL"], result.Artifacts.Select(item => item.Kind));
        // The digests were compared against the bytes on this side on the way
        // through; reaching here at all is that check passing on real output.
        Assert.All(result.Artifacts, artifact => Assert.True(artifact.SizeBytes > 0));
        Assert.Equal("build123d", result.Engine!.EngineId);
        Assert.True(result.Operations![0].WallMs >= 0);
    }

    [EngineFact]
    public async Task ADisabledOperationReachesTheRealEngineAndStopsTheBuild()
    {
        // The whole rollback path, end to end: a key on this side becomes an
        // argument, the engine refuses the document, and the refusal arrives
        // back here as the code it was raised with rather than as an exit status.
        var job = JobWith("lever-plate.v1_7.json");
        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            new Build123dProcessEngine(RealEngine.Options()).BuildAsync(
                new CadDocumentBuildRequest(job, ["sketch.arc"]),
                CancellationToken.None));

        Assert.Equal("CAPABILITY_DISABLED", refused.Code);
        Assert.Equal("cad-ir", refused.Stage);
        Assert.Contains("sketch.arc", refused.SafeMessage);
        Assert.False(Directory.Exists(Path.Combine(job, "output")));
    }

    [EngineFact]
    public async Task AMisreadOutlineIsCaughtByTheRealEngineThroughTheRealCommandLine()
    {
        // The whole point of the shape claim, end to end. This document is valid,
        // builds, and measures exactly what it claims to measure; the only thing
        // wrong with it is that it is not the outline the drawing was read as.
        var job = JobWith("lever-plate.v1_7.json");
        var claim = Path.Combine(job, "shape-claim.json");
        File.WriteAllText(
            claim,
            """{"profile":"rectangle","openings":[{"kind":"round","count":2}],"solids":3}""");

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            new Build123dProcessEngine(RealEngine.Options()).ValidateAsync(
                new CadDocumentValidateRequest(job, [], claim), CancellationToken.None));

        Assert.Equal("SHAPE_CLAIM_CONTRADICTED", refused.Code);
        Assert.Equal("cad-ir", refused.Stage);
        Assert.Contains("rectangle", refused.SafeMessage);
    }

    [EngineFact]
    public async Task AnHonestReadingOfTheSameDocumentValidates()
    {
        var job = JobWith("lever-plate.v1_7.json");
        var claim = Path.Combine(job, "shape-claim.json");
        File.WriteAllText(
            claim,
            """{"profile":"closed_profile","openings":[{"kind":"round","count":2}],"solids":3}""");

        var required = await new Build123dProcessEngine(RealEngine.Options()).ValidateAsync(
            new CadDocumentValidateRequest(job, [], claim), CancellationToken.None);

        Assert.Contains("solid.contour_profile", required);
    }

    [EngineFact]
    public async Task ADocumentTheEngineRefusesArrivesAsItsOwnTypedFailure()
    {
        var job = Directory.CreateTempSubdirectory("cad-real-").FullName;
        File.WriteAllText(Path.Combine(job, "cad-ir.json"), "{\"schema_version\":\"1.5\"}");

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            new Build123dProcessEngine(RealEngine.Options()).BuildAsync(
                new CadDocumentBuildRequest(job, []), CancellationToken.None));

        Assert.Equal("CAD_IR_INVALID", refused.Code);
        Assert.Equal("prepare", refused.Stage);
    }
}
