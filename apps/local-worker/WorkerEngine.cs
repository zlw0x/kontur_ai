using CadAi.Build123dLauncher;
using CadAi.CadEngine;
using CadAi.KompasAdapter;

namespace CadAi.LocalWorker;

/// <summary>
/// The one place that says which CAD engine this worker builds with.
/// </summary>
/// <remarks>
/// Everything else in the pipeline asks the engine what it is and what it
/// produces (<see cref="CadEngineDescription"/>) rather than knowing. That is the
/// whole point of ENGINE-MIG-002: when build123d replaces KOMPAS the change is
/// this file, not a search for every literal that named a format.
///
/// It is a selector rather than a setting on purpose. Which engine a build used
/// has to be recorded, not configured per job — a job whose engine depended on an
/// environment variable would produce results that cannot be compared with each
/// other.
/// </remarks>
internal static class WorkerEngine
{
    public static ICadAdapter Select(bool fake) =>
        fake ? new FakeCadAdapter() : new KompasApi7Adapter();

    /// <summary>The engine a real build uses.</summary>
    public static ICadAdapter Adapter => Select(fake: false);

    /// <summary>
    /// The build123d engine, when this deployment is configured for it.
    /// </summary>
    /// <remarks>
    /// Nothing rather than a fallback: a worker configured for an engine it
    /// cannot construct must not quietly build with a different one. The two
    /// engines produce the same geometry from the same document and different
    /// files from it, and a silent substitution would be discovered by a customer
    /// opening a model in a format nobody chose.
    ///
    /// This is the second engine and there will not be a third. ENGINE-MIG-008
    /// deletes the KOMPAS branch and this method loses its condition.
    /// </remarks>
    public static ICadDocumentEngine? SelectDocumentEngine(CadEngineConfig? config)
    {
        if (config is null || !string.Equals(config.Engine, CadEngineConfig.Build123d, StringComparison.Ordinal))
            return null;
        if (!Enum.TryParse<EngineRuntime>(config.Runtime, ignoreCase: true, out var runtime))
            throw new WorkerException(
                "CONFIG_INVALID",
                $"cad_engine.runtime must be container or process, not {config.Runtime}.",
                2);
        return new Build123dProcessEngine(new EngineLaunchOptions
        {
            Runtime = runtime,
            ContainerCommand = config.ContainerCommand,
            Image = config.Image,
            PythonCommand = config.PythonCommand,
            WorkingDirectory = config.WorkingDirectory,
            BuildTimeout = TimeSpan.FromMinutes(Math.Clamp(config.BuildTimeoutMinutes, 1, 240))
        });
    }

    /// <summary>
    /// The engine this worker is configured for, and what it says about itself.
    /// </summary>
    /// <remarks>
    /// Resolved once for a worker rather than per job. Describing a container
    /// engine means starting it, and the claim loop asks what it can build on
    /// every poll — a process per poll would be a container start every few
    /// seconds to learn something that only changes when a flag does.
    ///
    /// So the answer is cached against the flags it was asked under, which is the
    /// one thing that changes it. An operator turning an operation off gets a new
    /// manifest on the next poll, and nothing else pays for it.
    /// </remarks>
    public sealed class EngineSelection(ICadDocumentEngine? document)
    {
        private CadEngineReport? cached;
        private IReadOnlySet<string> cachedFor = new HashSet<string>();

        public static EngineSelection For(CadEngineConfig? config) =>
            new(SelectDocumentEngine(config));

        public ICadDocumentEngine? Document => document;

        /// <summary>What this worker publishes, from whichever engine it uses.</summary>
        public async Task<WorkerCapabilityManifestPayload> ManifestAsync(
            FeatureFlags flags,
            string? codexCliVersion = null,
            CancellationToken cancellationToken = default)
        {
            if (document is null) return WorkerCapabilities.Manifest(flags: flags);
            return WorkerCapabilities.ManifestFor(
                await ReportAsync(flags, cancellationToken), codexCliVersion);
        }

        /// <summary>What the engine produces, so the pipeline knows what to upload.</summary>
        public async Task<CadEngineDescription> DescribeAsync(
            FeatureFlags flags,
            CancellationToken cancellationToken = default) =>
            document is null
                ? Adapter.Describe()
                : (await ReportAsync(flags, cancellationToken)).Engine;

        private async Task<CadEngineReport> ReportAsync(
            FeatureFlags flags,
            CancellationToken cancellationToken)
        {
            var disabled = flags.Disabled;
            if (cached is not null && cachedFor.SetEquals(disabled)) return cached;
            cached = await document!.DescribeAsync([.. disabled], cancellationToken);
            cachedFor = new HashSet<string>(disabled, StringComparer.Ordinal);
            return cached;
        }
    }

    /// <summary>
    /// What the pipeline writes itself, regardless of engine.
    /// </summary>
    /// <remarks>
    /// These are not the engine's business: the analysis and the questions come
    /// from the AI stage, the CAD-IR is the document the engine was given, and the
    /// validation report is written after the build by something that deliberately
    /// is not the engine. None of them is required — a job waiting for answers has
    /// no CAD-IR and no report, and that is a normal outcome rather than a
    /// failure.
    /// </remarks>
    public static readonly (string Kind, string FileName)[] PipelineArtifacts =
    [
        ("VALIDATION_REPORT", "validation-report.json"),
        ("DRAWING_ANALYSIS", "drawing-analysis.json"),
        ("CLARIFICATION_QUESTIONS", "clarification-questions.json"),
        ("CAD_IR", "cad-ir.json")
    ];
}
