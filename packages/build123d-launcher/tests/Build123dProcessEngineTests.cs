using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CadAi.CadEngine;
using Xunit;

namespace CadAi.Build123dLauncher.Tests;

/// <summary>
/// The seam between the worker and the engine, and every way the far side can
/// answer.
/// </summary>
/// <remarks>
/// A child process is a boundary, and the interesting cases are all about not
/// believing what crosses it: a digest that does not match the bytes, a flag that
/// did not arrive, an artifact that was promised and is not there, a crash with
/// nothing on stdout. None of those needs a real engine to reproduce, and all of
/// them would be awkward to arrange with one.
///
/// The command line is asserted directly rather than through behaviour. It is the
/// one place where this side decides what to execute, so what it decides is worth
/// stating in a test rather than inferring.
/// </remarks>
public sealed class Build123dProcessEngineTests
{
    private sealed class StubRunner(params EngineProcessResult[] results) : IEngineProcessRunner
    {
        private int index;

        public List<EngineInvocation> Invocations { get; } = [];
        public Exception? Throws { get; init; }

        public Task<EngineProcessResult> RunAsync(
            EngineInvocation invocation,
            EngineLaunchOptions options,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            Invocations.Add(invocation);
            if (Throws is not null) throw Throws;
            return Task.FromResult(results[Math.Min(index++, results.Length - 1)]);
        }
    }

    private static EngineProcessResult Ok(object payload) =>
        new(0, JsonSerializer.Serialize(payload), "");

    private static object Engine() => new
    {
        engine_id = "build123d",
        engine_version = "0.11.1",
        kernel_id = "opencascade",
        kernel_version = "7.9.3.1.1",
        cad_ir_version = "1.7",
        artifacts = new[]
        {
            new { kind = "STEP", file = "model.step", required = true },
            new { kind = "STL", file = "model.stl", required = true }
        }
    };

    private static object Described(params string[] disabled) => new
    {
        engine_id = "build123d",
        engine_version = "0.11.1",
        kernel_id = "opencascade",
        kernel_version = "7.9.3.1.1",
        cad_ir_version = "1.7",
        artifacts = new[]
        {
            new { kind = "STEP", file = "model.step", required = true },
            new { kind = "STL", file = "model.stl", required = true }
        },
        capabilities = new[] { "sketch.arc", "sketch.slot", "export.step", "export.stl" }
            .ToDictionary(
                key => key,
                key => new { status = disabled.Contains(key) ? "disabled" : "beta", version = "1.0" })
    };

    /// <summary>A job directory with the two files the engine says it wrote.</summary>
    private static (string Job, object Payload) Built(params string[] disabled)
    {
        var job = Directory.CreateTempSubdirectory("cad-launcher-").FullName;
        var output = Directory.CreateDirectory(Path.Combine(job, "output")).FullName;
        var artifacts = new List<object>();
        foreach (var (kind, name, bytes) in new[]
                 {
                     ("STEP", "model.step", "ISO-10303-21;"u8.ToArray()),
                     ("STL", "model.stl", "solid"u8.ToArray())
                 })
        {
            File.WriteAllBytes(Path.Combine(output, name), bytes);
            artifacts.Add(new
            {
                kind,
                file = name,
                size_bytes = (long)bytes.Length,
                sha256 = Convert.ToHexString(SHA256.HashData(bytes))
            });
        }
        return (job, new
        {
            status = "COMPLETED",
            engine = Engine(),
            disabled_capabilities = disabled,
            verified = true,
            artifacts
        });
    }

    private static Build123dProcessEngine EngineWith(
        IEngineProcessRunner runner,
        EngineLaunchOptions? options = null) =>
        new(options ?? new EngineLaunchOptions(), runner);

    // --- the command line ---------------------------------------------------

    [Fact]
    public void ContainerModeAsksForEverythingTheDecisionPromised()
    {
        var invocation = EngineCommandLine.Build(
            new EngineLaunchOptions { Image = "cad-ai/cad-worker:2026-07-31" },
            Path.GetFullPath("/tmp/job-1"),
            []);

        Assert.Equal("docker", invocation.FileName);
        // Read-only root, no network, not root, one bind mount. Every one of
        // these is in ADR-023 and every one of them is stated per invocation
        // rather than left to how the image happens to be run.
        Assert.Contains("--read-only", invocation.Arguments);
        Assert.Equal("none", ValueAfter(invocation, "--network"));
        // The user that owns the job directory, because a container running as
        // anyone else cannot write the results into a bind mount owned by the
        // worker. On Windows the flag is left off: the runtime's file ownership
        // for a bind mount does not work that way.
        if (OperatingSystem.IsWindows())
            Assert.DoesNotContain("--user", invocation.Arguments);
        else
            Assert.Equal(
                $"{Unix.geteuid()}:{Unix.getegid()}", ValueAfter(invocation, "--user"));
        Assert.Equal(
            $"type=bind,src={Path.GetFullPath("/tmp/job-1")},dst=/work",
            ValueAfter(invocation, "--mount"));
        // The image, and then the engine's own arguments. The job is mounted, so
        // the path the engine is told about is the container's, not this one's.
        Assert.Equal("cad-ai/cad-worker:2026-07-31", invocation.Arguments[^4]);
        Assert.Equal(["build", "--job", "/work"], invocation.Arguments.TakeLast(3));
    }

    [Fact]
    public void AnExplicitContainerUserOverridesTheDefaultAndAnEmptyOneOmitsIt()
    {
        var named = EngineCommandLine.Build(
            new EngineLaunchOptions { ContainerUser = "4242:4242" }, Path.GetFullPath("/tmp/j"), []);
        Assert.Equal("4242:4242", ValueAfter(named, "--user"));

        // Left to the runtime, which is what a deployment with its own idea of
        // container identity — rootless podman, user namespaces — will want.
        var unset = EngineCommandLine.Build(
            new EngineLaunchOptions { ContainerUser = null }, Path.GetFullPath("/tmp/j"), []);
        Assert.DoesNotContain("--user", unset.Arguments);
    }

    [Fact]
    public void AShapeClaimIsMountedReadOnlyAndNamedByItsPathInsideTheContainer()
    {
        var invocation = EngineCommandLine.Validate(
            new EngineLaunchOptions { Image = "cad-ai/cad-worker:ci" },
            Path.GetFullPath("/tmp/job-4"),
            [],
            Path.GetFullPath("/tmp/claim.json"));

        // Its own mount rather than a file in the job directory: the claim is what
        // the drawing was read as, and putting it where the engine writes results
        // would make it look like one of them. Read-only, because the engine has no
        // business changing what it is being checked against.
        Assert.Contains(
            $"type=bind,src={Path.GetFullPath("/tmp/claim.json")},dst=/claim.json,readonly",
            invocation.Arguments);
        // Mounted before the image, named after it.
        Assert.True(
            invocation.Arguments.ToList().IndexOf("cad-ai/cad-worker:ci")
            < invocation.Arguments.ToList().IndexOf("--claim"));
        Assert.Equal("/claim.json", ValueAfter(invocation, "--claim"));
    }

    [Fact]
    public void AValidationWithNoClaimPassesNoClaimAtAll()
    {
        // A manual document did not come from a drawing and has nothing to be
        // checked against. Inventing a claim for it would be inventing a reading.
        var invocation = EngineCommandLine.Validate(
            new EngineLaunchOptions(), Path.GetFullPath("/tmp/job-5"), []);
        Assert.DoesNotContain("--claim", invocation.Arguments);
    }

    [Fact]
    public void AShapeClaimAtARelativePathIsRefused()
    {
        var refused = Assert.Throws<CadAdapterException>(() =>
            EngineCommandLine.Validate(
                new EngineLaunchOptions(), Path.GetFullPath("/tmp/job-6"), [], "claim.json"));
        Assert.Equal("OUTPUT_PATH_INVALID", refused.Code);
    }

    [Fact]
    public void ProcessModeRunsTheSameEntryPointThroughAnInterpreter()
    {
        var invocation = EngineCommandLine.Build(
            new EngineLaunchOptions { Runtime = EngineRuntime.Process, PythonCommand = "python3" },
            Path.GetFullPath("/tmp/job-2"),
            ["sketch.slot", "sketch.arc"]);

        Assert.Equal("python3", invocation.FileName);
        Assert.Equal(
            ["-m", "cad_worker", "build", "--job", Path.GetFullPath("/tmp/job-2"),
             "--disable", "sketch.arc", "--disable", "sketch.slot"],
            invocation.Arguments);
    }

    [Fact]
    public void FlagsAreOrderedSoTwoIdenticalRunsProduceIdenticalCommandLines()
    {
        var first = EngineCommandLine.Describe(
            new EngineLaunchOptions { Runtime = EngineRuntime.Process },
            ["sketch.slot", "sketch.arc"]);
        var second = EngineCommandLine.Describe(
            new EngineLaunchOptions { Runtime = EngineRuntime.Process },
            ["sketch.arc", "sketch.slot"]);
        Assert.Equal(first.Arguments, second.Arguments);
    }

    [Fact]
    public void ARelativeJobDirectoryIsRefusedRatherThanResolvedSomewhere()
    {
        // In container mode the child's working directory is not even the same
        // filesystem, so "relative to what" has no answer worth guessing at.
        var refused = Assert.Throws<CadAdapterException>(() =>
            EngineCommandLine.Build(new EngineLaunchOptions(), "jobs/job-3", []));
        Assert.Equal("OUTPUT_PATH_INVALID", refused.Code);
    }

    private static string ValueAfter(EngineInvocation invocation, string flag) =>
        invocation.Arguments[invocation.Arguments.ToList().IndexOf(flag) + 1];

    // --- describing ---------------------------------------------------------

    [Fact]
    public async Task DescribeReportsTheEngineAndEverythingItBuilds()
    {
        var report = await EngineWith(new StubRunner(Ok(Described()))).DescribeAsync([], default);

        Assert.Equal("build123d", report.Engine.EngineId);
        Assert.Equal("7.9.3.1.1", report.Engine.KernelVersion);
        Assert.Equal("1.7", report.Engine.CadIrVersion);
        Assert.Equal(["STEP", "STL"], report.Engine.Artifacts.Select(item => item.Kind));
        Assert.Equal("beta", report.Capabilities["sketch.arc"].Status);
    }

    [Fact]
    public async Task ADisabledCapabilityComesBackDisabledRatherThanAbsent()
    {
        var report = await EngineWith(new StubRunner(Ok(Described("sketch.slot"))))
            .DescribeAsync(["sketch.slot"], default);
        Assert.Equal("disabled", report.Capabilities["sketch.slot"].Status);
        Assert.Equal("beta", report.Capabilities["sketch.arc"].Status);
    }

    [Fact]
    public async Task AManifestThatIgnoredTheFlagsIsRefusedRatherThanPublished()
    {
        // The failure this whole echo exists for. Publishing a capability as
        // available and then refusing it at build time is worse than refusing
        // to publish at all, because the API would keep scheduling the job.
        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(Described()))).DescribeAsync(["sketch.slot"], default));

        Assert.Equal("ENGINE_FLAGS_NOT_APPLIED", refused.Code);
        Assert.Contains("sketch.slot", refused.SafeMessage);
    }

    // --- building -----------------------------------------------------------

    [Fact]
    public async Task ASuccessfulBuildReportsWhatIsActuallyOnDisk()
    {
        var (job, payload) = Built();
        var result = await EngineWith(new StubRunner(Ok(payload)))
            .BuildAsync(new CadDocumentBuildRequest(job, []), default);

        Assert.Equal(["STEP", "STL"], result.Artifacts.Select(item => item.Kind));
        Assert.All(result.Artifacts, artifact => Assert.True(File.Exists(artifact.Path)));
        Assert.Equal("build123d", result.Engine!.EngineId);
        // One measured record for the whole build. The engine does not report
        // per-operation timings, and inventing a split would be inventing data.
        Assert.Single(result.Operations!);
        Assert.True(result.Operations![0].Success);
    }

    [Fact]
    public async Task ADigestThatDisagreesWithTheBytesStopsTheBuild()
    {
        var (job, payload) = Built();
        File.WriteAllText(Path.Combine(job, "output", "model.step"), "something else");

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_ARTIFACT_MISMATCH", refused.Code);
    }

    [Fact]
    public async Task AnArtifactThatWasPromisedAndIsNotThereStopsTheBuild()
    {
        var (job, payload) = Built();
        File.Delete(Path.Combine(job, "output", "model.stl"));

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_ARTIFACT_MISSING", refused.Code);
    }

    [Fact]
    public async Task AnArtifactNameThatIsAPathIsRefused()
    {
        var (job, _) = Built();
        var payload = new
        {
            status = "COMPLETED",
            engine = Engine(),
            disabled_capabilities = Array.Empty<string>(),
            verified = true,
            artifacts = new[]
            {
                new { kind = "STEP", file = "../../model.step", size_bytes = 1L, sha256 = "00" }
            }
        };

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_PROTOCOL_INVALID", refused.Code);
    }

    [Fact]
    public async Task ABuildThatDroppedAFlagIsRefusedEvenThoughItSucceeded()
    {
        // The launcher's own bug, caught by the engine echoing what it applied.
        // Without this the worker would report a clean build of exactly the
        // operation an operator was trying to stop.
        var (job, payload) = Built();
        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, ["sketch.arc"]), default));

        Assert.Equal("ENGINE_FLAGS_NOT_APPLIED", refused.Code);
        Assert.Contains("sketch.arc", refused.SafeMessage);
    }

    [Fact]
    public async Task AFlagTheEngineAppliedAndNobodyAskedForIsAlsoRefused()
    {
        var (job, payload) = Built("sketch.slot");
        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_FLAGS_NOT_APPLIED", refused.Code);
    }

    [Fact]
    public async Task AnUnverifiedModelIsNotADeliveredModel()
    {
        var (job, _) = Built();
        var payload = new
        {
            status = "COMPLETED",
            engine = Engine(),
            disabled_capabilities = Array.Empty<string>(),
            verified = false,
            artifacts = Array.Empty<object>()
        };

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("GEOMETRY_VALIDATION_FAILED", refused.Code);
    }

    // --- how the far side fails ---------------------------------------------

    [Fact]
    public async Task TheEnginesOwnTypedFailureIsPassedThroughUnchanged()
    {
        // A code and a stage that describe the document. A repair loop can react
        // to these, which is the entire reason the engine prints JSON on failure.
        var runner = new StubRunner(new EngineProcessResult(
            1,
            """{"status":"FAILED","code":"REVOLVE_PROFILE_CROSSES_AXIS","stage":"feature","message":"The profile of feature.bush lies on both sides of its axis."}""",
            ""));
        var (job, _) = Built();

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(runner).BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("REVOLVE_PROFILE_CROSSES_AXIS", refused.Code);
        Assert.Equal("feature", refused.Stage);
        Assert.Contains("feature.bush", refused.SafeMessage);
        // Timings survive a failure: a build that died still consumed the time.
        Assert.Single(refused.Operations);
    }

    [Fact]
    public async Task ACrashWithNothingOnStdoutBecomesATypedFailureAndLeaksNoTraceback()
    {
        var runner = new StubRunner(new EngineProcessResult(
            139, "", "Traceback (most recent call last):\n  File \"/srv/secret/path.py\""));
        var (job, _) = Built();

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(runner).BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_PROCESS_FAILED", refused.Code);
        Assert.Contains("139", refused.SafeMessage);
        // The message can reach a customer, and a traceback names host paths.
        Assert.DoesNotContain("secret", refused.SafeMessage);
        Assert.DoesNotContain("Traceback", refused.SafeMessage);
    }

    [Fact]
    public async Task OutputThatIsNotTheJsonItPromisesIsATypedFailure()
    {
        var runner = new StubRunner(new EngineProcessResult(0, "starting up...", ""));
        var (job, _) = Built();

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(runner).BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_PROTOCOL_INVALID", refused.Code);
    }

    [Fact]
    public async Task ExitingZeroWithAStatusThatIsNotCompletedIsRefused()
    {
        var (job, _) = Built();
        var payload = new
        {
            status = "FAILED",
            engine = Engine(),
            disabled_capabilities = Array.Empty<string>(),
            verified = true,
            artifacts = Array.Empty<object>()
        };

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(new StubRunner(Ok(payload)))
                .BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_PROTOCOL_INVALID", refused.Code);
    }

    [Fact]
    public async Task AnEngineThatCannotBeStartedIsTheOperatorsProblemNotTheDocuments()
    {
        var runner = new StubRunner { Throws = new System.ComponentModel.Win32Exception("no docker") };
        var (job, _) = Built();

        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(runner).BuildAsync(new CadDocumentBuildRequest(job, []), default));

        Assert.Equal("ENGINE_UNAVAILABLE", refused.Code);
        Assert.Equal("prepare", refused.Stage);
    }

    [Fact]
    public async Task ADeadlineThatFiresIsATimeoutAndACallerGivingUpIsNot()
    {
        var (job, _) = Built();

        var timedOut = new StubRunner { Throws = new OperationCanceledException() };
        var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
            EngineWith(timedOut).BuildAsync(new CadDocumentBuildRequest(job, []), default));
        Assert.Equal("ENGINE_TIMEOUT", refused.Code);

        // The same exception, but the caller asked to stop. A lease treats the
        // two differently: a timeout is this job's fault and a cancellation is
        // the worker shutting down.
        using var cancelled = new CancellationTokenSource();
        await cancelled.CancelAsync();
        var stopping = new StubRunner { Throws = new OperationCanceledException() };
        await Assert.ThrowsAsync<OperationCanceledException>(() =>
            EngineWith(stopping).BuildAsync(new CadDocumentBuildRequest(job, []), cancelled.Token));
    }
}
