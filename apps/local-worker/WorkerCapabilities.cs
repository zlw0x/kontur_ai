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
    public const string CadIrVersion = "0.1.0";

    private const string Stable = "stable";

    public static WorkerCapabilityManifestPayload Manifest(
        string? kompasVersion = null,
        string? codexCliVersion = null) =>
        new(
            "1.0",
            WorkerVersion,
            kompasVersion,
            codexCliVersion,
            [CadIrVersion],
            new Dictionary<string, string>
            {
                ["solid.rectangular_prism"] = Stable,
                ["feature.hole.simple_through"] = Stable,
                ["export.m3d"] = Stable,
                ["export.step"] = Stable,
                ["export.stl"] = Stable,
                ["validate.manifold"] = Stable,
                ["validate.bounding_box"] = Stable,
                ["validate.hole_count"] = Stable,
            });
}

public sealed record WorkerCapabilityManifestPayload(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("worker_version")] string WorkerVersion,
    [property: JsonPropertyName("kompas_version")] string? KompasVersion,
    [property: JsonPropertyName("codex_cli_version")] string? CodexCliVersion,
    [property: JsonPropertyName("cad_ir_versions")] IReadOnlyList<string> CadIrVersions,
    [property: JsonPropertyName("capabilities")] IReadOnlyDictionary<string, string> Capabilities);
