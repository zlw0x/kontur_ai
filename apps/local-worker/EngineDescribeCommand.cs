using System.Text.Json;

namespace CadAi.LocalWorker;

/// <summary>
/// Ask the engine what it is, and say so.
/// </summary>
/// <remarks>
/// What `probe-kompas` was for. That command existed because driving a desktop
/// application headlessly fails in ways only a probe could tell apart — a missing
/// licence, a second process, a COM registration that was never made. None of
/// those exist any more, and what replaces the question is simpler: start the
/// engine and print what it says.
///
/// It is still worth a command. The engine is a container on the other side of a
/// runtime that may not be installed, an image that may not be pulled and a
/// mount that may not be permitted, and "the worker cannot start its engine" is
/// exactly what an operator needs to find out before a customer does.
/// </remarks>
public static class EngineDescribeCommand
{
    public static async Task<int> RunAsync(WorkerPaths paths, WorkerConfigStore configs)
    {
        var flags = FeatureFlags.Load(paths);
        var selection = WorkerEngine.EngineSelection.For(configs.Load()?.CadEngine);
        var manifest = await selection.ManifestAsync(flags);
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = "ENGINE",
                engine = manifest.Engine,
                cad_ir_versions = manifest.CadIrVersions,
                // The flags of this worker, already applied — so what is printed
                // is what the API would be told, not what the engine would say
                // if nothing were switched off.
                disabled = flags.Disabled.Order(StringComparer.Ordinal),
                capabilities = manifest.Capabilities
                    .OrderBy(entry => entry.Key, StringComparer.Ordinal)
                    .ToDictionary(entry => entry.Key, entry => entry.Value)
            },
            new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }
}
