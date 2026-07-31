using CadAi.Build123dLauncher;
using CadAi.CadEngine;

namespace CadAi.LocalWorker;

/// <summary>
/// The one place that says which CAD engine this worker builds with.
/// </summary>
/// <remarks>
/// There is one engine now: build123d on OpenCascade, in a container
/// (ADR-023, ENGINE-MIG-008). What used to be a choice between two is a choice
/// between the real engine and a fake that builds nothing, which is a different
/// kind of choice — the fake exists so CI and the smoke test can exercise the
/// lease, the ledger and the upload path without an engine at all.
///
/// Everything else in the pipeline asks the engine what it is and what it
/// produces (<see cref="CadEngineDescription"/>) rather than knowing. That is what
/// ENGINE-MIG-002 set up, and it is the reason this file was the whole change when
/// the engine was replaced.
/// </remarks>
internal static class WorkerEngine
{
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

    /// <summary>The engine a job is built with.</summary>
    /// <remarks>
    /// A configuration that cannot be turned into an engine is a refusal, never a
    /// fallback. A worker that quietly built with something other than what it was
    /// configured for would produce results nobody could compare.
    /// </remarks>
    public static ICadDocumentEngine Select(CadEngineConfig? config, bool fake = false)
    {
        if (fake) return new FakeDocumentEngine(WorkerCapabilities.CadIrVersion);
        var settings = config ?? new CadEngineConfig();
        if (!Enum.TryParse<EngineRuntime>(settings.Runtime, ignoreCase: true, out var runtime))
            throw new WorkerException(
                "CONFIG_INVALID",
                $"cad_engine.runtime must be container or process, not {settings.Runtime}.",
                2);
        return new Build123dProcessEngine(new EngineLaunchOptions
        {
            Runtime = runtime,
            ContainerCommand = settings.ContainerCommand,
            Image = settings.Image,
            PythonCommand = settings.PythonCommand,
            WorkingDirectory = settings.WorkingDirectory,
            BuildTimeout = TimeSpan.FromMinutes(Math.Clamp(settings.BuildTimeoutMinutes, 1, 240))
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
    public sealed class EngineSelection(ICadDocumentEngine engine)
    {
        private CadEngineReport? cached;
        private IReadOnlySet<string> cachedFor = new HashSet<string>();

        public static EngineSelection For(CadEngineConfig? config, bool fake = false) =>
            new(Select(config, fake));

        public ICadDocumentEngine Engine => engine;

        /// <summary>What this worker publishes to the API.</summary>
        public async Task<WorkerCapabilityManifestPayload> ManifestAsync(
            FeatureFlags flags,
            string? codexCliVersion = null,
            CancellationToken cancellationToken = default) =>
            WorkerCapabilities.ManifestFor(
                await ReportAsync(flags, cancellationToken), codexCliVersion);

        /// <summary>What the engine produces, so the pipeline knows what to upload.</summary>
        public async Task<CadEngineDescription> DescribeAsync(
            FeatureFlags flags,
            CancellationToken cancellationToken = default) =>
            (await ReportAsync(flags, cancellationToken)).Engine;

        private async Task<CadEngineReport> ReportAsync(
            FeatureFlags flags,
            CancellationToken cancellationToken)
        {
            var disabled = flags.Disabled;
            if (cached is not null && cachedFor.SetEquals(disabled)) return cached;
            cached = await engine.DescribeAsync([.. disabled], cancellationToken);
            cachedFor = new HashSet<string>(disabled, StringComparer.Ordinal);
            return cached;
        }
    }
}
