using CadAi.CadEngine;
using System.Text.Json.Serialization;
using CadAi.KompasAdapter;

namespace CadAi.LocalWorker;

/// <summary>
/// What this worker build can actually construct.
/// </summary>
/// <remarks>
/// This list is the honest boundary of what the adapter builds, not an
/// aspiration. Adding a key here tells the API to start scheduling that
/// operation, so a key belongs here only once the adapter builds it and a
/// verifier checks it.
///
/// The published status is the built-in one unless a feature flag overrides it.
/// A flag is how an operation found to be producing bad parts stops being
/// scheduled without a new release; see <see cref="FeatureFlags"/>.
/// </remarks>
public static class WorkerCapabilities
{
    public const string WorkerVersion = "0.4.0";
    public const string CadIrVersion = "1.3";

    /// <summary>
    /// Behaviour version of a capability, independent of the worker build.
    /// It is bumped when an operation's observable behaviour changes, so the
    /// API can demand the newer behaviour without demanding a whole new
    /// worker release.
    /// </summary>
    private static (string Status, string Version) Stable(string version = "1.0") =>
        ("stable", version);

    /// <summary>
    /// Everything added by POSTMVP-006 is beta rather than stable.
    /// </summary>
    /// <remarks>
    /// One real acceptance part is not a hundred, and the roadmap's definition
    /// of done asks for ten positive and ten negative fixtures before an
    /// operation is stable. Declaring these beta is what makes that honest
    /// instead of aspirational.
    /// </remarks>
    private static (string Status, string Version) Beta(string version = "1.0") =>
        ("beta", version);

    /// <summary>Built-in status per capability, before any flag is applied.</summary>
    private static readonly IReadOnlyDictionary<string, (string Status, string Version)> Declared =
        new Dictionary<string, (string, string)>(StringComparer.Ordinal)
        {
            [CadCapabilities.SolidRectangularPrism] = Stable(),
            [CadCapabilities.FeatureHoleSimpleThrough] = Stable(),
            [CadCapabilities.ExportM3d] = Stable(),
            [CadCapabilities.ExportStep] = Stable(),
            [CadCapabilities.ExportStl] = Stable(),
            [CadCapabilities.ValidateManifold] = Stable(),
            [CadCapabilities.ValidateBoundingBox] = Stable(),
            [CadCapabilities.ValidateHoleCount] = Stable(),
            [CadCapabilities.SketchPlaneBase] = Stable(),
            [CadCapabilities.SolidContourProfile] = Beta(),
            [CadCapabilities.SketchArc] = Beta(),
            [CadCapabilities.SketchSlot] = Beta(),
            [CadCapabilities.SketchRegularPolygon] = Beta(),
            [CadCapabilities.SketchIslands] = Beta(),
            [CadCapabilities.SketchConstruction] = Beta(),
            [CadCapabilities.SketchPlaneDatum] = Beta(),
            [CadCapabilities.SketchPlaneFaceSelector] = Beta(),
            [CadCapabilities.FeatureBossAdditive] = Beta(),
            [CadCapabilities.SketchConstraints] = Beta(),
            [CadCapabilities.SketchDimensions] = Beta(),
        };

    public static WorkerCapabilityManifestPayload Manifest(
        string? kompasVersion = null,
        string? codexCliVersion = null,
        FeatureFlags? flags = null)
    {
        var effective = flags ?? FeatureFlags.AllEnabled;
        return new WorkerCapabilityManifestPayload(
            "1.0",
            WorkerVersion,
            kompasVersion,
            codexCliVersion,
            [CadIrVersion],
            Declared.ToDictionary(
                entry => entry.Key,
                entry => new CapabilityDeclarationPayload(
                    effective.EffectiveStatus(entry.Key, entry.Value.Status),
                    entry.Value.Version),
                StringComparer.Ordinal));
    }

    /// <summary>Every capability this build declares, whatever its status.</summary>
    public static IReadOnlyCollection<string> Keys => (IReadOnlyCollection<string>)Declared.Keys;

    public static string BuiltInStatus(string capability) =>
        Declared.TryGetValue(capability, out var declared) ? declared.Status : "unsupported";
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
