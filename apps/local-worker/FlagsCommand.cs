using System.Text.Json;

namespace CadAi.LocalWorker;

/// <summary>
/// Read and flip the per-operation switches.
/// </summary>
/// <remarks>
/// A rollback happens when something is already going wrong, so it has to be
/// one command and it has to say what it did. Editing the JSON by hand works
/// too, and this exists because a typo in a filename at that moment is a
/// rollback that silently did not happen.
///
/// The list of what there is to turn off comes from the engine (ENGINE-MIG-008),
/// so an operator reading this output is reading what the worker will actually
/// publish rather than a list compiled into it. A key in the file that the engine
/// does not declare is named as unknown here instead of being discovered on the
/// next job — which is the loud-typo property the old hard-coded list had, kept
/// by asking the authority instead of duplicating it.
/// </remarks>
public static class FlagsCommand
{
    public static async Task<int> RunAsync(
        string[] arguments,
        WorkerPaths paths,
        WorkerConfigStore configs)
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

        // Asked with nothing disabled, so the built-in status of each operation
        // is visible beside the effective one. An operator deciding whether to
        // turn something back on needs to see what it would go back to.
        var declared = await Declared(configs);
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = "FLAGS",
                file = FeatureFlags.PathFor(paths),
                changes,
                capabilities = declared.Keys.Order(StringComparer.Ordinal).Select(key => new
                {
                    capability = key,
                    built_in = declared[key],
                    effective = flags.EffectiveStatus(key, declared[key])
                }),
                // Named so an operator sees a typo now rather than on the next
                // job. The engine is the authority on what exists.
                unknown_to_this_engine = flags.Disabled
                    .Where(key => !declared.ContainsKey(key))
                    .Order(StringComparer.Ordinal)
            },
            new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }

    /// <summary>
    /// What the engine declares, or nothing when it cannot be reached.
    /// </summary>
    /// <remarks>
    /// A rollback must work on a machine where the engine is broken — that is
    /// often exactly why someone is running this. So an engine that will not
    /// start costs the listing, not the command: the flag is still written and
    /// still reported.
    /// </remarks>
    private static async Task<IReadOnlyDictionary<string, string>> Declared(WorkerConfigStore configs)
    {
        try
        {
            var report = await WorkerEngine
                .Select(configs.Load()?.CadEngine)
                .DescribeAsync([], CancellationToken.None);
            return report.Capabilities.ToDictionary(
                entry => entry.Key, entry => entry.Value.Status, StringComparer.Ordinal);
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }
    }
}
