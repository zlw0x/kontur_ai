using System.Text.Json.Serialization;

namespace CadAi.LocalWorker;

/// <summary>
/// What this worker build can actually construct.
/// </summary>
/// <remarks>
/// This list is the honest boundary of the confirmed MVP, not an aspiration.
/// Adding a key here tells the API to start scheduling that operation, so a
/// key belongs here only once the adapter builds it and a verifier checks it.
/// </remarks>
public static class WorkerCapabilities
{
    public const string WorkerVersion = "0.4.0";
    public const string CadIrVersion = "1.2";

    /// <summary>
    /// Behaviour version of a capability, independent of the worker build.
    /// It is bumped when an operation's observable behaviour changes, so the
    /// API can demand the newer behaviour without demanding a whole new
    /// worker release.
    /// </summary>
    private static CapabilityDeclarationPayload Stable(string version = "1.0") =>
        new("stable", version);

    public static WorkerCapabilityManifestPayload Manifest(
        string? kompasVersion = null,
        string? codexCliVersion = null) =>
        new(
            "1.0",
            WorkerVersion,
            kompasVersion,
            codexCliVersion,
            [CadIrVersion],
            new Dictionary<string, CapabilityDeclarationPayload>
            {
                ["solid.rectangular_prism"] = Stable(),
                ["feature.hole.simple_through"] = Stable(),
                ["export.m3d"] = Stable(),
                ["export.step"] = Stable(),
                ["export.stl"] = Stable(),
                ["validate.manifold"] = Stable(),
                ["validate.bounding_box"] = Stable(),
                ["validate.hole_count"] = Stable(),
            });
}

public sealed record CapabilityDeclarationPayload(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("version")] string Version);

public sealed record WorkerCapabilityManifestPayload(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("worker_version")] string WorkerVersion,
    [property: JsonPropertyName("kompas_version")] string? KompasVersion,
    [property: JsonPropertyName("codex_cli_version")] string? CodexCliVersion,
    [property: JsonPropertyName("cad_ir_versions")] IReadOnlyList<string> CadIrVersions,
    [property: JsonPropertyName("capabilities")] IReadOnlyDictionary<string, CapabilityDeclarationPayload> Capabilities);
