using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CadAi.CadEngine;

/// <summary>
/// One feature to build, with every parameter already a number.
/// </summary>
/// <remarks>
/// A flat ordered list rather than a graph: CAD-IR states the dependencies and
/// the trusted validator has already checked that they are acyclic and declared
/// before use, so by the time a plan exists array order is a valid build order.
/// Re-deriving the topology here would be a second implementation of something
/// already proved correct.
/// </remarks>
public abstract record CadFeaturePlan(string Id);

public sealed record ExtrudeFeaturePlan(
    string Id,
    SketchPlan Sketch,
    double DepthMm,
    bool IsCut) : CadFeaturePlan(Id);

public sealed record DatumPlaneFeaturePlan(
    string Id,
    string ResultId,
    string? BasePlaneName,
    string? BaseResultId,
    double OffsetMm,
    bool Flip) : CadFeaturePlan(Id);

/// <summary>
/// What the document says the finished solid must be.
/// </summary>
/// <remarks>
/// Carried through from the document's `expectations` rather than derived from
/// the features. Deriving them would make the check circular: a build that
/// computed its own expectations from its own plan would satisfy them by
/// construction, and a verifier that cannot disagree is not verifying (ADR-018).
/// </remarks>
public sealed record ExpectedGeometryPlan(
    double SizeXMm,
    double SizeYMm,
    double SizeZMm,
    double ToleranceMm,
    int BodyCount,
    int ThroughHoleCount);

public sealed record CadBuildPlan(
    IReadOnlyList<CadFeaturePlan> Features,
    ExpectedGeometryPlan Expectations)
{
    public ExtrudeFeaturePlan Base =>
        Features.OfType<ExtrudeFeaturePlan>().FirstOrDefault(feature => !feature.IsCut)
        ?? throw new CadAdapterException(
            "UNSUPPORTED_FEATURE_SET", "cad-ir", "The plan contains no base extrusion.");
}

public sealed record CadBuildRequest(CadBuildPlan Plan, string OutputDirectory);

public sealed record CadArtifact(string Kind, string Path, long SizeBytes, string Sha256)
{
    /// <summary>Describe a file an engine has just written.</summary>
    /// <remarks>
    /// The checksum is taken here, from the bytes on disk, rather than accepted
    /// from whatever produced them. An engine that reported a digest of what it
    /// meant to write would agree with itself about a truncated file.
    /// </remarks>
    public static CadArtifact Read(string kind, string path)
    {
        var info = new FileInfo(path);
        using var stream = File.OpenRead(path);
        return new CadArtifact(kind, path, info.Length, Convert.ToHexString(SHA256.HashData(stream)));
    }
}

/// <summary>Where an engine is allowed to write.</summary>
/// <remarks>
/// Shared by every adapter rather than owned by one. It used to hang off the
/// fake, which meant the real engine's path safety was a member of the test
/// double — an arrangement that survives only until someone deletes the double.
/// </remarks>
public static class CadOutputDirectory
{
    public static string Safe(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new CadAdapterException(
                "OUTPUT_PATH_INVALID", "prepare", "CAD output directory is required.");
        return System.IO.Path.GetFullPath(path);
    }
}

/// <summary>
/// How long one CAD step took and whether it succeeded.
/// </summary>
/// <remarks>
/// Returned with the result rather than pushed to an observer: the build runs
/// on a dedicated STA thread, and handing it a callback into the caller's
/// mutable state would put cross-thread writes on the COM path for the sake
/// of a metric.
/// </remarks>
public sealed record CadOperationRecord(
    string OperationCode,
    string Stage,
    long WallMs,
    bool Success,
    string? FailureCode = null);

/// <summary>
/// One kind of file an engine promises to produce.
/// </summary>
/// <remarks>
/// Declared by the engine rather than listed by the pipeline. The pipeline used
/// to carry `M3D`, `STEP`, `STL` as a literal array and refuse any job that did
/// not upload an `M3D` — which is a KOMPAS-native format written into the
/// definition of a finished job. An engine that does not produce it was not
/// expressible, and ADR-023 introduces exactly that engine.
///
/// `Required` is what makes the check possible without the list: a build that
/// does not produce something the engine promised is a failed build, whatever
/// the engine is.
/// </remarks>
public sealed record CadArtifactKind(string Kind, string FileName, bool Required = true);

/// <summary>
/// What engine built this, on what kernel, against which CAD-IR.
/// </summary>
/// <remarks>
/// Recorded with every result so a delivered model can be traced to the thing
/// that made it. During an engine migration this stops being paperwork: two
/// engines produce a STEP file from the same document, and when they disagree
/// the first question is which one produced the file in front of you.
///
/// `KernelVersion` is nullable on purpose. An engine that cannot read its
/// kernel's version says so rather than reporting a number someone typed into a
/// constant — an unverified version string is worse than an absent one, because
/// it reads as measured.
/// </remarks>
public sealed record CadEngineDescription(
    string EngineId,
    string EngineVersion,
    string KernelId,
    string? KernelVersion,
    string CadIrVersion,
    IReadOnlyList<CadArtifactKind> Artifacts)
{
    public IEnumerable<CadArtifactKind> RequiredArtifacts =>
        Artifacts.Where(artifact => artifact.Required);
}

public sealed record CadBuildResult(
    IReadOnlyList<CadArtifact> Artifacts,
    IReadOnlyList<CadOperationRecord>? Operations = null,
    CadEngineDescription? Engine = null);

public interface ICadAdapter
{
    /// <summary>What this engine is and what it promises to produce.</summary>
    /// <remarks>
    /// Answerable without building anything, so the pipeline can know what to
    /// expect before it starts and a worker can publish it in its manifest.
    /// </remarks>
    CadEngineDescription Describe();

    Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken);
}

public sealed class CadAdapterException(
    string code,
    string stage,
    string safeMessage,
    Exception? inner = null,
    IReadOnlyList<CadOperationRecord>? operations = null)
    : Exception(safeMessage, inner)
{
    public string Code { get; } = code;
    public string Stage { get; } = stage;
    public string SafeMessage { get; } = safeMessage;

    /// <summary>
    /// Steps measured before the failure. A build that fails after twenty
    /// minutes still consumed twenty minutes, and the ledger only learns that
    /// if the timings travel out with the error.
    /// </summary>
    public IReadOnlyList<CadOperationRecord> Operations { get; } = operations ?? [];

    public CadAdapterException WithOperations(IReadOnlyList<CadOperationRecord> measured) =>
        new(Code, Stage, SafeMessage, InnerException, measured);
}

public sealed class FakeCadAdapter : ICadAdapter
{
    /// <remarks>
    /// The fake has a kernel version because it *is* its own kernel: there is
    /// nothing underneath it that could be a different version from itself.
    /// </remarks>
    public CadEngineDescription Describe() => new(
        EngineId: "fake",
        EngineVersion: "1",
        KernelId: "none",
        KernelVersion: "none",
        CadIrVersion: CadIrBuildPlanParser.CadIrVersion,
        Artifacts: [new CadArtifactKind("FAKE_CAD", "model.fake-cad.json")]);

    public async Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken)
    {
        var started = Stopwatch.GetTimestamp();
        var output = CadOutputDirectory.Safe(request.OutputDirectory);
        Directory.CreateDirectory(output);
        var path = Path.Combine(output, "model.fake-cad.json");
        var payload = JsonSerializer.Serialize(new
        {
            adapter = "fake",
            features = request.Plan.Features.Select(feature => feature switch
            {
                ExtrudeFeaturePlan extrude => new
                {
                    id = extrude.Id,
                    kind = extrude.IsCut ? "cut.extrude" : "solid.extrude",
                    depth_mm = extrude.DepthMm,
                    outer = extrude.Sketch.Outer.GetType().Name,
                    islands = extrude.Sketch.Inner.Count
                },
                DatumPlaneFeaturePlan plane => new
                {
                    id = plane.Id,
                    kind = "datum.plane.offset",
                    depth_mm = plane.OffsetMm,
                    outer = plane.ResultId,
                    islands = 0
                },
                _ => throw new CadAdapterException(
                    "UNSUPPORTED_FEATURE_TYPE", "prepare", "Unknown feature in the plan.")
            })
        });
        await File.WriteAllTextAsync(path, payload, Encoding.UTF8, cancellationToken);
        // The fake reports timings too, so instrumentation is exercised by CI
        // instead of only on a machine with KOMPAS installed.
        var operations = request.Plan.Features
            .Select((feature, index) => new CadOperationRecord(
                feature switch
                {
                    ExtrudeFeaturePlan { IsCut: false } => "rectangular_prism",
                    ExtrudeFeaturePlan => $"cut_{index:D3}",
                    _ => $"datum_plane_{index:D3}"
                },
                feature is DatumPlaneFeaturePlan ? "feature" : "sketch",
                index == 0 ? (long)Stopwatch.GetElapsedTime(started).TotalMilliseconds : 0,
                Success: true))
            .ToList();
        return new CadBuildResult([CadArtifact.Read("FAKE_CAD", path)], operations, Describe());
    }
}
