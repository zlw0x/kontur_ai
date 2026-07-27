using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CadAi.KompasAdapter;

public sealed record RectangleExtrusionPlan(
    double CenterX,
    double CenterY,
    double Width,
    double Height,
    double Depth,
    IReadOnlyList<CircularCutPlan>? CircularCuts = null);

public sealed record CircularCutPlan(double CenterX, double CenterY, double Radius);

public sealed record CadBuildRequest(RectangleExtrusionPlan Plan, string OutputDirectory);

public sealed record CadArtifact(string Kind, string Path, long SizeBytes, string Sha256);

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

public sealed record CadBuildResult(
    IReadOnlyList<CadArtifact> Artifacts,
    IReadOnlyList<CadOperationRecord>? Operations = null);

public interface ICadAdapter
{
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
    public async Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken)
    {
        var started = Stopwatch.GetTimestamp();
        var output = SafeOutputDirectory(request.OutputDirectory);
        Directory.CreateDirectory(output);
        var path = Path.Combine(output, "model.fake-cad.json");
        var payload = JsonSerializer.Serialize(new
        {
            adapter = "fake",
            geometry = "rectangle_extrusion",
            request.Plan.CenterX,
            request.Plan.CenterY,
            request.Plan.Width,
            request.Plan.Height,
            request.Plan.Depth
        });
        await File.WriteAllTextAsync(path, payload, Encoding.UTF8, cancellationToken);
        // The fake reports timings too, so instrumentation is exercised by CI
        // instead of only on a machine with KOMPAS installed.
        var operations = new List<CadOperationRecord>
        {
            new("rectangular_prism", "sketch",
                (long)Stopwatch.GetElapsedTime(started).TotalMilliseconds, Success: true)
        };
        operations.AddRange((request.Plan.CircularCuts ?? []).Select((_, index) =>
            new CadOperationRecord($"hole_{index + 1:D3}", "feature", 0, Success: true)));
        return new CadBuildResult([CreateArtifact("FAKE_CAD", path)], operations);
    }

    internal static string SafeOutputDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new CadAdapterException("OUTPUT_PATH_INVALID", "prepare", "CAD output directory is required.");
        return Path.GetFullPath(path);
    }

    internal static CadArtifact CreateArtifact(string kind, string path)
    {
        var info = new FileInfo(path);
        using var stream = File.OpenRead(path);
        return new CadArtifact(kind, path, info.Length, Convert.ToHexString(SHA256.HashData(stream)));
    }
}
