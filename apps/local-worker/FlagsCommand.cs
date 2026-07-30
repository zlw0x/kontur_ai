using System.Text.Json;
using CadAi.KompasAdapter;

namespace CadAi.LocalWorker;

/// <summary>
/// Read and flip the per-operation switches.
/// </summary>
/// <remarks>
/// A rollback happens when something is already going wrong, so it has to be
/// one command and it has to say what it did. Editing the JSON by hand works
/// too, and this exists because a typo in a filename at that moment is a
/// rollback that silently did not happen.
/// </remarks>
public static class FlagsCommand
{
    public static Task<int> RunAsync(string[] arguments, WorkerPaths paths)
    {
        var flags = FeatureFlags.Load(paths);
        var changes = new List<string>();

        for (var index = 0; index < arguments.Length; index++)
        {
            var flag = arguments[index];
            if (flag is not ("--disable" or "--enable")) continue;
            if (index + 1 >= arguments.Length)
                throw new WorkerException("FEATURE_FLAGS_ARGUMENT_MISSING", $"{flag} needs a capability.", 2);
            var capability = arguments[++index];
            var changed = flag == "--disable" ? flags.Disable(capability) : flags.Enable(capability);
            changes.Add($"{capability} {(flag == "--disable" ? "disabled" : "enabled")}" +
                        (changed ? "" : " (already)"));
        }

        if (changes.Count > 0) flags.Save(paths);

        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = "FLAGS",
                file = FeatureFlags.PathFor(paths),
                changes,
                capabilities = WorkerCapabilities.Keys.Order(StringComparer.Ordinal).Select(key => new
                {
                    capability = key,
                    built_in = WorkerCapabilities.BuiltInStatus(key),
                    effective = flags.EffectiveStatus(key, WorkerCapabilities.BuiltInStatus(key))
                }),
                // Named so an operator can see what there is to turn off
                // without reading the source.
                unknown_to_this_build = Array.Empty<string>(),
                all_capabilities = CadCapabilities.All.Order(StringComparer.Ordinal)
            },
            new JsonSerializerOptions { WriteIndented = true }));
        return Task.FromResult(0);
    }
}
