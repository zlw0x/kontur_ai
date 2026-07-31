namespace CadAi.Build123dLauncher;

using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using CadAi.CadEngine;

/// <summary>
/// The build123d engine, driven as a child process (ADR-023, ENGINE-MIG-007).
/// </summary>
/// <remarks>
/// This is the seam the migration turns on. The engine is a Python program in a
/// container; this is the .NET side that starts it, hands it one job directory
/// and the flags of the run, and turns what it prints back into the typed results
/// the rest of the worker already understands.
///
/// **Running a fixed program is not running generated code.** ADR-023 forbids
/// executing anything an AI produced, and says so including "no shelling out".
/// The rule is about the *document*: nothing from `cad-ir.json` reaches an
/// argument, an environment variable or a file name. The command line is built
/// here from a fixed vocabulary, the one variable value is a job directory this
/// worker chose, and it is checked to be an absolute path before it is passed.
/// The engine reads the document — as data, through a schema and a validator —
/// exactly as the KOMPAS adapter did.
///
/// **Nothing the child says about itself is taken on trust.** The digests it
/// reports are compared against the bytes on disk, the flags it echoes are
/// compared against the flags it was given, and the artifacts it promised in its
/// own description are checked to exist. A child process is a boundary, and a
/// boundary that believes what crosses it is not one.
/// </remarks>
public sealed class Build123dProcessEngine(
    EngineLaunchOptions? options = null,
    IEngineProcessRunner? runner = null) : ICadDocumentEngine
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = false
    };

    private readonly EngineLaunchOptions options = options ?? new EngineLaunchOptions();
    private readonly IEngineProcessRunner runner = runner ?? new EngineProcessRunner();

    public async Task<CadEngineReport> DescribeAsync(
        IReadOnlyCollection<string> disabledCapabilities,
        CancellationToken cancellationToken)
    {
        var invocation = EngineCommandLine.Describe(options, disabledCapabilities);
        var result = await RunAsync(invocation, options.DescribeTimeout, cancellationToken);
        if (result.ExitCode != 0) throw Failure(result, "describe");

        var described = Parse<DescribePayload>(result.StandardOutput, "describe");
        var report = new CadEngineReport(
            new CadEngineDescription(
                described.engine_id,
                described.engine_version,
                described.kernel_id,
                described.kernel_version,
                described.cad_ir_version,
                [.. described.artifacts.Select(item =>
                    new CadArtifactKind(item.kind, item.file, item.required))]),
            described.capabilities.ToDictionary(
                entry => entry.Key,
                entry => new CadCapabilityDeclaration(entry.Value.status, entry.Value.version),
                StringComparer.Ordinal));

        RequireFlagsWereApplied(
            disabledCapabilities,
            [.. report.Capabilities.Where(entry => entry.Value.Status == "disabled").Select(entry => entry.Key)],
            "the manifest it published");
        return report;
    }

    public async Task<CadBuildResult> BuildAsync(
        CadDocumentBuildRequest request,
        CancellationToken cancellationToken)
    {
        var invocation = EngineCommandLine.Build(
            options, request.JobDirectory, request.DisabledCapabilities);

        var started = Stopwatch.GetTimestamp();
        var result = await RunAsync(invocation, options.BuildTimeout, cancellationToken);
        var elapsed = (long)Stopwatch.GetElapsedTime(started).TotalMilliseconds;

        if (result.ExitCode != 0)
            throw Failure(result, "build").WithOperations(Measured(elapsed, null));

        var built = Parse<BuildPayload>(result.StandardOutput, "build");
        if (built.status != "COMPLETED")
            // Exit zero and a status that is not COMPLETED is the engine
            // contradicting itself. Believing either half would be a guess.
            throw new CadAdapterException(
                "ENGINE_PROTOCOL_INVALID",
                "engine",
                $"The CAD engine exited successfully and reported status {built.status}.");
        if (!built.verified)
            throw new CadAdapterException(
                "GEOMETRY_VALIDATION_FAILED",
                "validation",
                "The CAD engine completed without verifying the model it produced.");

        RequireFlagsWereApplied(
            request.DisabledCapabilities, built.disabled_capabilities, "the build it ran");

        var engine = new CadEngineDescription(
            built.engine.engine_id,
            built.engine.engine_version,
            built.engine.kernel_id,
            built.engine.kernel_version,
            built.engine.cad_ir_version,
            [.. built.engine.artifacts.Select(item =>
                new CadArtifactKind(item.kind, item.file, item.required))]);

        var artifacts = ReadArtifacts(request.JobDirectory, built, engine);
        return new CadBuildResult(artifacts, Measured(elapsed, artifacts.Count), engine);
    }

    // -----------------------------------------------------------------------
    // Trusting nothing
    // -----------------------------------------------------------------------

    private static IReadOnlyList<CadArtifact> ReadArtifacts(
        string jobDirectory,
        BuildPayload built,
        CadEngineDescription engine)
    {
        var output = Path.Combine(Path.GetFullPath(jobDirectory), "output");
        var artifacts = new List<CadArtifact>(built.artifacts.Count);
        foreach (var reported in built.artifacts)
        {
            // A base name, joined here. The engine reports what it wrote, not
            // where: in container mode its idea of "where" is a path that does
            // not exist on this machine.
            var name = Path.GetFileName(reported.file);
            if (string.IsNullOrEmpty(name) || name != reported.file)
                throw new CadAdapterException(
                    "ENGINE_PROTOCOL_INVALID",
                    "engine",
                    "The CAD engine reported an artifact whose name is a path.");
            var path = Path.Combine(output, name);
            if (!File.Exists(path))
                throw new CadAdapterException(
                    "ENGINE_ARTIFACT_MISSING",
                    "engine",
                    $"The CAD engine reported writing {name}, and it is not there.");

            var artifact = CadArtifact.Read(reported.kind, path);
            if (!string.Equals(artifact.Sha256, reported.sha256, StringComparison.OrdinalIgnoreCase))
                // Read from the bytes on this side and compared with what the
                // child said it wrote. A mismatch is a file that changed under
                // the worker or a child reporting a digest of its intent, and
                // neither is something to deliver to a customer.
                throw new CadAdapterException(
                    "ENGINE_ARTIFACT_MISMATCH",
                    "engine",
                    $"{name} on disk does not match the checksum the CAD engine reported.");
            artifacts.Add(artifact);
        }

        foreach (var required in engine.RequiredArtifacts)
            if (artifacts.All(artifact => artifact.Kind != required.Kind))
                throw new CadAdapterException(
                    "ENGINE_ARTIFACT_MISSING",
                    "engine",
                    $"The CAD engine declares {required.Kind} and did not produce one.");
        return artifacts;
    }

    /// <summary>
    /// The flags the engine acted on are the flags it was given.
    /// </summary>
    /// <remarks>
    /// The reason the engine echoes them at all. A launcher that built the
    /// command line wrongly — a dropped key, a mode that forgot to forward them —
    /// would otherwise produce a completely successful build of exactly the
    /// operation an operator was trying to stop, and nothing anywhere would say
    /// so.
    /// </remarks>
    private static void RequireFlagsWereApplied(
        IReadOnlyCollection<string> asked,
        IReadOnlyCollection<string> applied,
        string what)
    {
        var expected = asked.ToHashSet(StringComparer.Ordinal);
        if (expected.SetEquals(applied)) return;
        var missing = expected.Except(applied, StringComparer.Ordinal).Order(StringComparer.Ordinal);
        var extra = applied.Except(expected, StringComparer.Ordinal).Order(StringComparer.Ordinal);
        throw new CadAdapterException(
            "ENGINE_FLAGS_NOT_APPLIED",
            "engine",
            $"The CAD engine was asked to disable [{string.Join(", ", expected.Order(StringComparer.Ordinal))}] "
            + $"and {what} disabled [{string.Join(", ", applied.Order(StringComparer.Ordinal))}]"
            + $"; missing [{string.Join(", ", missing)}], unexpected [{string.Join(", ", extra)}].");
    }

    // -----------------------------------------------------------------------
    // Running it
    // -----------------------------------------------------------------------

    private async Task<EngineProcessResult> RunAsync(
        EngineInvocation invocation,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        try
        {
            return await runner.RunAsync(invocation, options, timeout, cancellationToken);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            // The deadline fired rather than the caller giving up. Distinguished
            // because they mean different things to a lease: a timeout is this
            // job's fault, a cancellation is not.
            throw new CadAdapterException(
                "ENGINE_TIMEOUT",
                "engine",
                $"The CAD engine did not finish within {timeout.TotalSeconds:F0} seconds.");
        }
        catch (Exception error) when (error is not CadAdapterException and not OperationCanceledException)
        {
            // A missing binary, a container runtime that is not installed, a
            // permission refusal. The operator's problem, not the document's, and
            // the message says which.
            throw new CadAdapterException(
                "ENGINE_UNAVAILABLE",
                "prepare",
                $"The CAD engine could not be started with {invocation.FileName}.",
                error);
        }
    }

    /// <summary>
    /// A non-zero exit, as the most specific typed failure the output supports.
    /// </summary>
    /// <remarks>
    /// The engine's own JSON is preferred, because it describes the document and
    /// is safe to show. When there is none — a crash, a killed process, an image
    /// that does not exist — the fallback carries the exit code and nothing else.
    /// `stderr` deliberately does not reach <see cref="CadAdapterException.SafeMessage"/>:
    /// a Python traceback names host paths, and this message can reach a customer.
    /// </remarks>
    private static CadAdapterException Failure(EngineProcessResult result, string what)
    {
        var reported = TryParse<FailurePayload>(result.StandardOutput);
        if (reported is { status: "FAILED", code.Length: > 0 })
            return new CadAdapterException(reported.code, reported.stage, reported.message);
        return new CadAdapterException(
            "ENGINE_PROCESS_FAILED",
            "engine",
            $"The CAD engine failed to {what} and exited with code {result.ExitCode}.");
    }

    private static IReadOnlyList<CadOperationRecord> Measured(long wallMs, int? artifacts) =>
    [
        new CadOperationRecord(
            "document_build",
            "feature",
            wallMs,
            Success: artifacts is not null,
            FailureCode: artifacts is null ? "ENGINE_PROCESS_FAILED" : null)
    ];

    private static T Parse<T>(string payload, string what)
    {
        var parsed = TryParse<T>(payload);
        if (parsed is null)
            throw new CadAdapterException(
                "ENGINE_PROTOCOL_INVALID",
                "engine",
                $"The CAD engine answered {what} with something that is not the JSON it promises.");
        return parsed;
    }

    private static T? TryParse<T>(string payload)
    {
        if (string.IsNullOrWhiteSpace(payload)) return default;
        try
        {
            return JsonSerializer.Deserialize<T>(payload, Json);
        }
        catch (JsonException)
        {
            return default;
        }
    }

    // The engine's own wire shapes, in its own snake_case. Named to match the
    // JSON rather than renamed to match C# convention: a property attribute per
    // field is a place to make a typo that compiles.
#pragma warning disable IDE1006 // Naming rule violation: wire shapes, not API.
    private sealed record ArtifactPayload(string kind, string file, bool required);

    private sealed record DeclarationPayload(string status, string version);

    private sealed record DescribePayload(
        string engine_id,
        string engine_version,
        string kernel_id,
        string? kernel_version,
        string cad_ir_version,
        IReadOnlyList<ArtifactPayload> artifacts,
        IReadOnlyDictionary<string, DeclarationPayload> capabilities);

    private sealed record BuiltArtifactPayload(string kind, string file, long size_bytes, string sha256);

    private sealed record BuildPayload(
        string status,
        DescribePayload engine,
        [property: JsonPropertyName("disabled_capabilities")]
        IReadOnlyList<string> disabled_capabilities,
        bool verified,
        IReadOnlyList<BuiltArtifactPayload> artifacts);

    private sealed record FailurePayload(string status, string code, string stage, string message);
#pragma warning restore IDE1006
}
