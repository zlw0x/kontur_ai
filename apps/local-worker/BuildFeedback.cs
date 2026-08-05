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
///
/// **It is two questions rather than one, and the split above answers the first.**
/// "Can the agent fix it?" decides whether the document goes back. "Is another
/// attempt worth making?" is a different question, and answering it with the same
/// bit made a machine failure on attempt 1 of 3 go quietly back to the queue. For a
/// container that would not start that is right; for a quota that returns on a
/// stated date it is three silent retries and an order that says "waiting" for four
/// days. <see cref="WillBeTheSameNextTime"/> is the second answer.
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
            // The trusted gate refused the document. The most repairable failure
            // there is — the agent wrote it, and rewriting it is the entire fix.
            //
            // Missing until a run needed it, and the reason it was missed is worth
            // keeping: the *rule* that fired is in the message, not in the code.
            // A document refused for `PARAMETER_DRIVES_NOTHING` arrives here as
            // `CAD_IR_INVALID`, so classifying the rule name did nothing and the
            // loop went on treating the whole class as unrepairable. Codes are
            // what this file decides about; the message is what the agent reads.
            "CAD_IR_INVALID",

            // The document is valid and is not the part the reading described.
            "SHAPE_CLAIM_CONTRADICTED",

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

            // A dimension the document states that nothing builds with
            // (CAD-IR 1.11, ADR-034). Repairable in the most literal sense: the
            // fix is to reference the parameter from the geometry that should
            // have used it, or to stop declaring it — both of which are edits to
            // the document and to nothing else.
            //
            // Classified here after a real run needed it. The rule shipped, a
            // bushing document was refused by it, and the loop did nothing:
            // an unclassified code is not repairable by design, so the job
            // neither healed nor failed, it simply waited to be tried again. The
            // safe default is right and it is not free — a new code costs
            // somebody a decision.
            "PARAMETER_DRIVES_NOTHING",
        };

    /// <summary>
    /// Failures that are about the machine and will say the same thing next time.
    /// </summary>
    /// <remarks>
    /// The third case, and it is a real one rather than a tidy-up. A run meant to
    /// close the bushing never reached the model:
    ///
    /// <code>
    /// {"type":"error","message":"You've hit your usage limit … try again at Aug 8th, 2026"}
    /// {"type":"turn.failed"}
    /// </code>
    ///
    /// The job stayed leased, `output/` was empty, and the order page said "waiting" —
    /// the exact silence `JobStatus.FAILED` was added to end. The reason is that the
    /// worker reports a failure when the code is repairable *or* the attempt was the
    /// last, and a quota failure is neither: not repairable, because no document fixes
    /// it, and not the last attempt, because it was the first of three. So it went back
    /// to the queue to be told the same thing twice more, and the reason never reached
    /// the customer.
    ///
    /// What distinguishes these from the rest of the machine failures is that a retry
    /// cannot observe a change. A container that would not start may start; a missing
    /// interpreter may be installed, and on a fleet another worker may already have
    /// one. A quota returns on a date, and this service reaches the model through one
    /// locally authenticated CLI on one trusted machine — that is a rule
    /// (`CLAUDE.md`), not a deployment detail, so there is no second account for a
    /// retry to find.
    ///
    /// Listed, for the reason `Repairable` is listed: a new code joins when somebody
    /// decides it does. Being wrong here costs an order that is reported failed when
    /// it could have succeeded on the next worker, which is worse than a retry and
    /// better than silence.
    /// </remarks>
    private static readonly IReadOnlySet<string> Unchanging =
        new HashSet<string>(StringComparer.Ordinal)
        {
            // The account's quota. **This is the code the real failure carried**, and
            // not the one it looks like: `LocalCodexRunner.MapExit` maps any error text
            // containing "rate" or "limit" here, and "You've hit your usage limit"
            // contains one. Classifying only `CODEX_BUDGET_EXHAUSTED` would have left
            // the measured failure retrying exactly as before.
            "CODEX_CAPACITY_LIMIT",

            // This worker's own per-order run budget, which is a policy number rather
            // than a date. It belongs here for a different reason: the count is
            // deterministic, so the same drawing through the same policy exhausts it in
            // the same place on every attempt.
            "CODEX_BUDGET_EXHAUSTED",
        };

    /// <summary>Can the compiling agent do anything about this?</summary>
    public static bool IsRepairable(WorkerException error) => IsRepairable(error.Code);

    /// <summary>
    /// How long to wait before a deferred job is worth trying again.
    /// </summary>
    /// <remarks>
    /// A duration rather than the date the CLI states, and that is deliberate. The
    /// reset time arrives only as prose — "try again at Aug 8th, 2026 8:44 AM" — and
    /// parsing prose is the weakness `MapExit` already has, in a place where getting
    /// it wrong means an order sleeps until a date nobody meant.
    ///
    /// An hour reaches the same place without a parser. If the quota is back, the job
    /// builds; if it is not, the worker pauses it again, and a pause hands the attempt
    /// back, so a four-day outage costs a handful of claims a day and nothing else.
    /// The customer sees "paused, retrying at …" throughout, which is the truth at
    /// every point in that window.
    /// </remarks>
    public static readonly TimeSpan PauseFor = TimeSpan.FromHours(1);

    /// <summary>Would another attempt at this job be told the same thing?</summary>
    /// <remarks>
    /// Asked only of failures that are *not* repairable — a repairable one already
    /// ends the job with a reason. False for everything unclassified, which keeps the
    /// retry the default: a job that lapses is picked up again, and that is the
    /// behaviour every failure had before this existed.
    /// </remarks>
    public static bool WillBeTheSameNextTime(string code) => Unchanging.Contains(code);

    /// <summary>Can the compiling agent do anything about this?</summary>
    /// <remarks>
    /// By code rather than by exception, because the same question is asked on
    /// two paths that raise two different types. The validate path asks the
    /// engine whether it would accept a document, and an engine that cannot be
    /// reached at all — no image under that tag, no daemon, no interpreter —
    /// answers with a failure that looks from the outside exactly like a refusal
    /// of the document. Repairing that spends two model calls rewriting a
    /// document that was never the problem, which is what a real run did before
    /// this existed.
    /// </remarks>
    public static bool IsRepairable(string code) => Repairable.Contains(code);

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

    /// <summary>
    /// How many times a *refused document* may be rewritten before compilation
    /// gives up.
    /// </summary>
    /// <remarks>
    /// Three, and separate from <see cref="MaxBuildRepairs"/> because the two
    /// cost different things. A compile repair is one model call. A build repair
    /// is a model call **plus** a container start and a kernel run, which is why
    /// that one stays at two.
    ///
    /// Three because a real order needed all three. A flanged bushing was refused
    /// for dimensions parked in construction, the first rewrite was refused for
    /// the same, the second broke the dependency graph — and the third produced a
    /// document the gate accepted, four features and six parameters with none of
    /// them idle. At two the order would have ended one rewrite short of a valid
    /// document, which is the most expensive place to stop: everything has been
    /// paid for and nothing delivered.
    ///
    /// It was also a literal `2` written into the loop rather than a name, which
    /// is the second bound today to have been kept in two places — the first cost
    /// the worker its ability to tell that an attempt was the last.
    /// </remarks>
    public const int MaxCompileRepairs = 3;
}
