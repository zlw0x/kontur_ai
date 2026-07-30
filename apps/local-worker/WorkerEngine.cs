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
