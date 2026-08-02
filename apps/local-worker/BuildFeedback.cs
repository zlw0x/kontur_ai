namespace CadAi.LocalWorker;

/// <summary>
/// Which build failures are worth telling the compiling agent about.
/// </summary>
/// <remarks>
/// The document is validated before a build — schema, the trusted semantic gate,
/// and the shape claim — and a repair loop already runs on those. What had no way
/// back was everything the *build* discovers: a shell with no room for its wall, a
/// bend tighter than the profile going round it, a draft past the closing point, a
/// selector that matched nothing on the body it was resolved against, a solid that
/// came out the wrong size. Those are typed, they name what the document asked
/// for, and until now they ended the job.
///
/// Nothing here widens what the agent may do. It still writes CAD-IR and nothing
/// else, it is still checked by the same gates, and the geometry is still built by
/// code written here. The only change is that a failure it could have fixed
/// reaches it.
///
/// **The split is the whole design.** A code that describes the document can be
/// repaired by rewriting the document. A code that describes the machine — no
/// engine, no image, a path that cannot be written, a container that would not
/// start — cannot, and feeding one back would spend a model call to be told the
/// same thing again. Silence about the machine is not pessimism; it is the
/// difference between a loop that converges and one that burns a budget.
/// </remarks>
internal static class BuildFeedback
{
    /// <summary>
    /// Failures that describe the document, and can therefore be repaired by
    /// writing a different one.
    /// </summary>
    /// <remarks>
    /// Listed rather than pattern-matched. A prefix rule like "anything starting
    /// with SKETCH_" would silently adopt every future code that happens to share
    /// a prefix, including ones that turn out to be about the machine — and the
    /// cost of that mistake is paid in model calls on a customer's order. A new
    /// code is repairable when someone decides it is.
    /// </remarks>
    private static readonly IReadOnlySet<string> Repairable =
        new HashSet<string>(StringComparer.Ordinal)
        {
            // The part came out, and it is not the part the document declared.
            "GEOMETRY_VALIDATION_FAILED",

            // The kernel was asked for something it cannot do with these numbers,
            // and said so rather than returning a plausible wrong answer. Each of
            // these three exists because it once did return one.
            "SHELL_NO_CAVITY",
            "SWEEP_BEND_TIGHTER_THAN_PROFILE",
            "EXTRUDE_DRAFT_TOO_STEEP",

            // The document named geometry that is not there, or named it in a way
            // that fits more than one thing. Both are answerable by naming it
            // differently.
            "SELECTOR_NO_MATCH",
            "SELECTOR_AMBIGUOUS",
            "SELECTOR_UNSUPPORTED_PREDICATE",

            // The sketch does not describe a profile that can be built.
            "SKETCH_INVALID",
            "SKETCH_NOT_CLOSED",
            "SKETCH_ENTITY_DUPLICATE",

            // The document contradicts itself about a size or a relation.
            "DIMENSION_OUT_OF_RANGE",
            "DIMENSION_DISAGREES_WITH_GEOMETRY",
            "CONSTRAINT_NOT_SATISFIED",
            "CONSTRAINT_OPERAND_MISSING",
            "CONSTRAINT_OPERAND_INVALID",
            "CONSTRAINT_DUPLICATE",
            "CONSTRAINT_CONTRADICTION",

            // A feature set this engine cannot build, or a result named before
            // anything produced it.
            "UNSUPPORTED_FEATURE",
            "UNSUPPORTED_FEATURE_SET",
            "FEATURE_RESULT_UNAVAILABLE",
            "PARAMETER_UNRESOLVED",
        };

    /// <summary>Can the compiling agent do anything about this?</summary>
    public static bool IsRepairable(WorkerException error) => Repairable.Contains(error.Code);

    /// <summary>
    /// How many times a build failure may send the document back to be rewritten.
    /// </summary>
    /// <remarks>
    /// Two, matching the loop that already runs on validation failures — and for a
    /// blunter reason than symmetry: a build costs a container start and a kernel
    /// run, so an unbounded loop is a way to spend a customer's order on the same
    /// mistake. Two attempts is what the acceptance runs showed a real repair
    /// takes; a document still wrong after two is wrong in a way the agent is not
    /// going to reason its way out of, and failing is more useful than looping.
    /// </remarks>
    public const int MaxBuildRepairs = 2;
}
