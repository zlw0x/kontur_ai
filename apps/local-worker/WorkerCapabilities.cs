using System.Text.Json.Serialization;
using CadAi.CadEngine;

namespace CadAi.LocalWorker;

/// <summary>
/// What this worker tells the API about itself.
/// </summary>
/// <remarks>
/// It used to hold a hand-written list of what the KOMPAS adapter could build,
/// with a maturity per key. That list is gone (ENGINE-MIG-008): the engine
/// declares its own capabilities and applies the operator's flags to them, and
/// this asks it. A list here would be a second place for the truth to live, and
/// the failure it produces is the worst kind available — the API schedules an
/// operation the worker then refuses, repeatedly, with nothing saying why.
///
/// What is left is what the engine cannot know: which worker build this is, and
/// which Codex CLI it found.
/// </remarks>
public static class WorkerCapabilities
{
    public const string WorkerVersion = "0.5.0";

    /// <summary>
    /// The CAD-IR version the AI is asked to write.
    /// </summary>
    /// <remarks>
    /// Still declared here rather than read from the engine, because the prompt
    /// needs it before any engine has been started, and a job that asked a model
    /// for the wrong version would fail after paying for the run. The engine
    /// reports its own, and a mismatch between the two is caught the first time a
    /// document reaches it.
    /// </remarks>
    public const string CadIrVersion = "1.8";

    /// <summary>The manifest of a worker, from the engine it builds with.</summary>
    public static WorkerCapabilityManifestPayload ManifestFor(
        CadEngineReport report,
        string? codexCliVersion = null) =>
        new(
            "1.0",
            WorkerVersion,
            new WorkerEnginePayload(
                report.Engine.EngineId,
                report.Engine.EngineVersion,
                report.Engine.KernelId,
                report.Engine.KernelVersion),
            codexCliVersion,
            [report.Engine.CadIrVersion],
            report.Capabilities.ToDictionary(
                entry => entry.Key,
                entry => new CapabilityDeclarationPayload(entry.Value.Status, entry.Value.Version),
                StringComparer.Ordinal));
}

public sealed record CapabilityDeclarationPayload(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("version")] string Version);

/// <summary>Which CAD engine this worker builds with.</summary>
public sealed record WorkerEnginePayload(
    [property: JsonPropertyName("engine_id")] string EngineId,
    [property: JsonPropertyName("engine_version")] string EngineVersion,
    [property: JsonPropertyName("kernel_id")] string KernelId,
    [property: JsonPropertyName("kernel_version")] string? KernelVersion);

public sealed record WorkerCapabilityManifestPayload(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("worker_version")] string WorkerVersion,
    [property: JsonPropertyName("engine")] WorkerEnginePayload? Engine,
    [property: JsonPropertyName("codex_cli_version")] string? CodexCliVersion,
    [property: JsonPropertyName("cad_ir_versions")] IReadOnlyList<string> CadIrVersions,
    [property: JsonPropertyName("capabilities")] IReadOnlyDictionary<string, CapabilityDeclarationPayload> Capabilities);
