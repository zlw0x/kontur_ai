using System.Security.Cryptography;

namespace CadAi.CadEngine;

/// <summary>
/// What an engine produced, and what produced it.
/// </summary>
/// <remarks>
/// What is left of this package after ENGINE-MIG-008. It used to hold a build
/// plan, a CAD-IR parser, a sketch validator, a constraint validator and a
/// selector resolver, because the .NET side read the document and handed KOMPAS
/// something already resolved. The engine now reads the document itself, with the
/// same validator the API uses, so all of that moved into `packages/cad-ir` and
/// `packages/build123d-adapter` and was deleted here rather than kept as a second
/// opinion nobody consults.
///
/// These types stay because they describe a *result*, which is still this side's
/// business: it holds the lease, writes the ledger, and uploads the files.
/// </remarks>
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
/// Returned with the result rather than pushed to an observer. The ledger only
/// learns what a build consumed if the timings travel out with it, including out
/// of a failure: a build that died after twenty minutes still consumed them.
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
/// not upload an `M3D` — a KOMPAS-native format written into the definition of a
/// finished job. `Required` is what makes the check possible without the list: a
/// build that does not produce something the engine promised is a failed build,
/// whatever the engine is.
/// </remarks>
public sealed record CadArtifactKind(string Kind, string FileName, bool Required = true);

/// <summary>
/// What engine built this, on what kernel, against which CAD-IR.
/// </summary>
/// <remarks>
/// Recorded with every result so a delivered model can be traced to the thing
/// that made it.
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

    public IReadOnlyList<CadOperationRecord> Operations { get; } = operations ?? [];

    public CadAdapterException WithOperations(IReadOnlyList<CadOperationRecord> measured) =>
        new(Code, Stage, SafeMessage, InnerException, measured);
}
