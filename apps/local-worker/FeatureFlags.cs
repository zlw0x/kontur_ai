using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace CadAi.LocalWorker;

/// <summary>
/// Per-operation switches, so a bad operation can be turned off without a
/// release.
/// </summary>
/// <remarks>
/// The roadmap's definition of done asks for a feature flag and a rollback per
/// operation. This is that, and the shape it takes matters: a flag is stored on
/// the worker rather than on the server, because the thing that has to stop is
/// the thing that drives the kernel, and it has to stop even if the server cannot be
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
///
/// What this no longer does is decide whether a key names something real. It used
/// to check against a list compiled into the worker; the engine now declares its
/// own capabilities and refuses an unknown `--disable` before it does anything
/// else, so a list here would be a second vocabulary to keep in step
/// (ENGINE-MIG-008). A key that is not even shaped like one is still refused
/// here, because that is a property of the file rather than of an engine.
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
        foreach (var key in keys) Require(key);
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

    /// <summary>
    /// The shape of a capability key, shared with the API's own pattern.
    /// </summary>
    /// <remarks>
    /// A typo in a rollback switch is the worst possible time to fail silently.
    /// This catches the half a file can be judged on — `Sketch Arc` is not a key
    /// in any engine — and the engine catches the other half by refusing a
    /// well-formed key it does not declare.
    /// </remarks>
    private static readonly Regex KeyPattern =
        new(@"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", RegexOptions.Compiled);

    private static void Require(string capability)
    {
        if (!KeyPattern.IsMatch(capability))
            throw new WorkerException(
                "FEATURE_FLAGS_UNKNOWN_CAPABILITY",
                $"Not a capability key: {capability}.");
    }

    private sealed record FeatureFlagFile(
        [property: JsonPropertyName("disabled")] IReadOnlyList<string> Disabled);
}
