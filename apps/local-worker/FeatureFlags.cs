using CadAi.CadEngine;
using System.Text.Json;
using System.Text.Json.Serialization;
using CadAi.KompasAdapter;

namespace CadAi.LocalWorker;

/// <summary>
/// Per-operation switches, so a bad operation can be turned off without a
/// release.
/// </summary>
/// <remarks>
/// The roadmap's definition of done asks for a feature flag and a rollback per
/// operation. This is that, and the shape it takes matters: a flag is stored on
/// the worker rather than on the server, because the thing that has to stop is
/// the thing that drives KOMPAS, and it has to stop even if the server cannot be
/// reached to be told.
///
/// Two effects, and both are needed for a rollback to be real. The manifest
/// reports the operation as `disabled`, so the API stops scheduling work that
/// requires it. And the parser refuses a document that needs it, so anything
/// already queued fails with a typed error before COM rather than building
/// something known to be wrong.
///
/// The file is absent by default and every operation is on. That is deliberate:
/// a missing file must not be able to silently disable a service.
/// </remarks>
public sealed class FeatureFlags
{
    public const string FileName = "feature-flags.json";

    private readonly HashSet<string> disabled;

    private FeatureFlags(HashSet<string> disabled) => this.disabled = disabled;

    public static FeatureFlags AllEnabled => new([]);

    public IReadOnlySet<string> Disabled => disabled;

    public static string PathFor(WorkerPaths paths) => Path.Combine(paths.StateRoot, FileName);

    /// <summary>
    /// Read the flags, or fail loudly.
    /// </summary>
    /// <remarks>
    /// A malformed or unreadable flag file is not treated as "no flags". An
    /// operator who wrote a file believes it is in force, and quietly running an
    /// operation they turned off is the one outcome this must never produce.
    /// </remarks>
    public static FeatureFlags Load(WorkerPaths paths)
    {
        var path = PathFor(paths);
        if (!File.Exists(path)) return AllEnabled;
        FeatureFlagFile? parsed;
        try
        {
            parsed = JsonSerializer.Deserialize<FeatureFlagFile>(File.ReadAllText(path));
        }
        catch (Exception error) when (error is JsonException or IOException)
        {
            throw new WorkerException(
                "FEATURE_FLAGS_UNREADABLE",
                $"{FileName} exists but could not be read; refusing to run as if it were absent.");
        }
        var keys = parsed?.Disabled ?? [];
        var unknown = keys.Where(key => !CadCapabilities.All.Contains(key)).Order().ToArray();
        if (unknown.Length > 0)
            // A typo in a rollback switch is the worst possible time to fail
            // silently: the operator believes an operation is off and it is not.
            throw new WorkerException(
                "FEATURE_FLAGS_UNKNOWN_CAPABILITY",
                $"{FileName} disables capabilities this build does not have: {string.Join(", ", unknown)}.");
        return new FeatureFlags(new HashSet<string>(keys, StringComparer.Ordinal));
    }

    public void Save(WorkerPaths paths)
    {
        Directory.CreateDirectory(paths.StateRoot);
        File.WriteAllText(
            PathFor(paths),
            JsonSerializer.Serialize(
                new FeatureFlagFile(disabled.Order().ToArray()),
                new JsonSerializerOptions { WriteIndented = true }));
    }

    public bool IsEnabled(string capability) => !disabled.Contains(capability);

    /// <summary>Turn one off; returns false when it already was.</summary>
    public bool Disable(string capability)
    {
        Require(capability);
        return disabled.Add(capability);
    }

    /// <summary>Turn one back on; returns false when it already was.</summary>
    public bool Enable(string capability)
    {
        Require(capability);
        return disabled.Remove(capability);
    }

    /// <summary>The gate the adapter's parser checks a document against.</summary>
    public CapabilityGate Gate() => CapabilityGate.Disabling(disabled);

    /// <summary>
    /// The status to publish for a capability whose built-in status is `status`.
    /// </summary>
    /// <remarks>
    /// `disabled` is not a low rung on the maturity ladder — the API treats it
    /// as "no" outright — so a disabled operation stops being scheduled rather
    /// than being scheduled reluctantly.
    /// </remarks>
    public string EffectiveStatus(string capability, string status) =>
        IsEnabled(capability) ? status : "disabled";

    private static void Require(string capability)
    {
        if (!CadCapabilities.All.Contains(capability))
            throw new WorkerException(
                "FEATURE_FLAGS_UNKNOWN_CAPABILITY",
                $"No such capability: {capability}.");
    }

    private sealed record FeatureFlagFile(
        [property: JsonPropertyName("disabled")] IReadOnlyList<string> Disabled);
}
