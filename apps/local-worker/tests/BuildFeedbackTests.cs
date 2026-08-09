using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// Which build failures go back to the agent, and which stop the job.
/// </summary>
/// <remarks>
/// The judgement this class encodes is the whole of the change: a code that
/// describes the *document* can be answered by writing a different document, and
/// a code that describes the *machine* cannot. Getting that split wrong is not a
/// crash — it is a customer's order spending two model calls to be told twice
/// that a container image is missing.
///
/// So these tests are about the split rather than about the loop. That the loop
/// runs is checked where the loop is; that it runs on the right things is here.
/// </remarks>
public sealed class BuildFeedbackTests
{
    private static WorkerException Failure(string code) => new(code, $"the engine said {code}");

    [Theory]
    // The trusted gate refused the document, which the agent wrote. The rule
    // that fired travels in the message; the code is what this file decides
    // about, and missing that distinction is what left a real order looping.
    [InlineData("CAD_IR_INVALID")]
    [InlineData("SHAPE_CLAIM_CONTRADICTED")]
    // The part came out and is not the part the document declared. The document
    // is the only place that can be changed.
    [InlineData("GEOMETRY_VALIDATION_FAILED")]
    // Three failures that exist because the kernel once returned a plausible
    // wrong answer instead: a shell with no room, a bend tighter than its
    // profile, a draft past the closing point.
    [InlineData("SHELL_NO_CAVITY")]
    [InlineData("SWEEP_BEND_TIGHTER_THAN_PROFILE")]
    [InlineData("EXTRUDE_DRAFT_TOO_STEEP")]
    // Geometry named in a way that fits nothing, or fits more than one thing.
    [InlineData("SELECTOR_NO_MATCH")]
    [InlineData("SELECTOR_AMBIGUOUS")]
    // A profile that cannot be built, and a document contradicting itself.
    [InlineData("SKETCH_NOT_CLOSED")]
    [InlineData("DIMENSION_DISAGREES_WITH_GEOMETRY")]
    [InlineData("CONSTRAINT_NOT_SATISFIED")]
    // A dimension the document states and nothing builds with. Classified after a
    // real order needed it: the rule shipped, a document was refused by it, and
    // the loop did nothing at all — an unclassified code is not repairable, so
    // the job neither healed nor failed.
    [InlineData("PARAMETER_DRIVES_NOTHING")]
    public void AFailureAboutTheDocumentGoesBackToBeRewritten(string code)
    {
        Assert.True(BuildFeedback.IsRepairable(Failure(code)));
    }

    [Theory]
    // Nothing the agent writes will conjure an engine, a container image, a
    // writable path or more time. Feeding these back spends a model call to be
    // told the same thing.
    [InlineData("ENGINE_NOT_AVAILABLE")]
    [InlineData("ENGINE_IMAGE_MISSING")]
    [InlineData("OUTPUT_PATH_INVALID")]
    [InlineData("CONTAINER_START_FAILED")]
    [InlineData("JOB_PATH_REQUIRED")]
    [InlineData("ARTIFACT_UPLOAD_FAILED")]
    public void AFailureAboutTheMachineStopsTheJob(string code)
    {
        Assert.False(BuildFeedback.IsRepairable(Failure(code)));
    }

    /// <summary>
    /// An unknown code is not repairable.
    /// </summary>
    /// <remarks>
    /// The safe default in both directions. A new failure that turns out to be
    /// about the document costs one job that could have healed itself; a new
    /// failure wrongly assumed repairable costs every job that hits it two model
    /// calls, quietly, on somebody's order. The first is a bug report, the second
    /// is a bill.
    /// </remarks>
    [Fact]
    public void ACodeNobodyHasClassifiedIsNotRepaired()
    {
        Assert.False(BuildFeedback.IsRepairable(Failure("SOMETHING_NEW")));
    }

    // --- the third case: worth reporting rather than retrying -------------------

    /// <summary>
    /// A quota that returns on a date is not worth three silent retries.
    /// </summary>
    /// <remarks>
    /// The failure this case was written for, and the assertion that would have caught
    /// it: a run reported `You've hit your usage limit … try again at Aug 8th`, which
    /// is neither repairable nor the last attempt, so the job went back to the queue
    /// and the order page said "waiting" with no reason on it.
    ///
    /// `CODEX_CAPACITY_LIMIT` is the code that carries it —
    /// `LocalCodexRunner.MapExit` maps any error text mentioning a rate or a limit
    /// there, and `CODEX_BUDGET_EXHAUSTED` is this worker's own per-order counter,
    /// which the CLI never reports. Both are here; only the first was measured.
    /// </remarks>
    [Theory]
    [InlineData("CODEX_CAPACITY_LIMIT")]
    [InlineData("CODEX_BUDGET_EXHAUSTED")]
    public void AFailureThatWillNotBeDifferentIsReportedRatherThanRetried(string code)
    {
        Assert.False(BuildFeedback.IsRepairable(Failure(code)));
        Assert.True(BuildFeedback.WillBeTheSameNextTime(code));
    }

    /// <summary>
    /// A machine failure another attempt may get past is still left to lapse.
    /// </summary>
    /// <remarks>
    /// The distinction the third case rests on, and the reason it is a list rather
    /// than "everything about the machine": a container that would not start may
    /// start, an interpreter may be installed, and on a fleet the next worker may
    /// already have one. Report those and an order that would have succeeded on the
    /// next attempt is told it failed.
    /// </remarks>
    [Theory]
    [InlineData("ENGINE_NOT_AVAILABLE")]
    [InlineData("CONTAINER_START_FAILED")]
    [InlineData("CODEX_NOT_INSTALLED")]
    [InlineData("CODEX_RUN_FAILED")]
    [InlineData("CODEX_TIMEOUT")]
    [InlineData("ARTIFACT_UPLOAD_FAILED")]
    public void AMachineFailureAnotherAttemptMayGetPastIsLeftToLapse(string code)
    {
        Assert.False(BuildFeedback.WillBeTheSameNextTime(code));
    }

    /// <remarks>
    /// The safe default, in the direction that costs least: an unclassified code
    /// keeps the retry every failure had before this existed.
    /// </remarks>
    [Fact]
    public void ACodeNobodyHasClassifiedIsStillWorthRetrying()
    {
        Assert.False(BuildFeedback.WillBeTheSameNextTime("SOMETHING_NEW"));
    }

    /// <summary>
    /// The two questions are asked of disjoint sets, and that is not an accident.
    /// </summary>
    /// <remarks>
    /// A repairable failure already ends the job with a reason, so asking whether it
    /// is worth retrying would be a second answer to a settled question. If a code
    /// ever needed to be in both, one of the two classifications is wrong.
    /// </remarks>
    [Fact]
    public void NoCodeIsBothRepairableAndNotWorthRetrying()
    {
        foreach (var code in new[] { "CODEX_CAPACITY_LIMIT", "CODEX_BUDGET_EXHAUSTED" })
            Assert.False(BuildFeedback.IsRepairable(code));
    }

    /// <remarks>
    /// A build costs a container start and a kernel run, so the bound is not
    /// decoration. Pinned because raising it is a decision about money rather
    /// than a tuning knob.
    /// </remarks>
    [Fact]
    public void TheNumberOfBuildRepairsIsBounded()
    {
        Assert.Equal(2, BuildFeedback.MaxBuildRepairs);
    }

    /// <summary>
    /// Rewriting a refused document is cheaper than rebuilding, and gets one more try.
    /// </summary>
    /// <remarks>
    /// A compile repair is one model call; a build repair is a model call plus a
    /// container start and a kernel run. Three because a real order needed all
    /// three — refused, rewritten and refused, rewritten into a broken dependency
    /// graph, and valid on the third. At two it would have stopped one rewrite
    /// short of a document the gate accepts, which is the most expensive place to
    /// stop: everything paid for and nothing delivered.
    /// </remarks>
    [Fact]
    public void RewritingARefusedDocumentGetsOneMoreTryThanRebuilding()
    {
        Assert.Equal(3, BuildFeedback.MaxCompileRepairs);
        Assert.True(BuildFeedback.MaxCompileRepairs > BuildFeedback.MaxBuildRepairs);
    }

    /// <summary>
    /// A failure inside the model's answer is not the model being unreachable.
    /// </summary>
    /// <remarks>
    /// The distinction the fleet gate rests on (P0-3). A document that will not
    /// compile, a claim that disagrees, a kernel that refused — those are the CLI
    /// working. Only a failure that names the CLI itself is evidence about whether
    /// the next drawing job can be run at all.
    ///
    /// `CODEX_MODEL_MISMATCH` is the trap and is asserted by name: it starts with the
    /// same four letters and means the CLI answered, from a model nobody asked for.
    /// </remarks>
    [Fact]
    public void OnlyAFailureAboutTheCliItselfSaysTheModelCouldNotBeReached()
    {
        foreach (var code in new[]
                 {
                     "CODEX_CAPACITY_LIMIT", "CODEX_BUDGET_EXHAUSTED",
                     "CODEX_CLI_MISSING", "CODEX_NOT_INSTALLED", "CODEX_AUTH_REQUIRED",
                 })
            Assert.True(BuildFeedback.ModelCouldNotBeReached(code), code);

        foreach (var code in new[]
                 {
                     "CODEX_MODEL_MISMATCH", "CODEX_OUTPUT_INVALID", "CAD_IR_INVALID",
                     "SHAPE_CLAIM_CONTRADICTED", "SELECTOR_AMBIGUOUS",
                     // A slow run is a slow run. Calling it an unreachable CLI would
                     // stop the fleet taking drawing work after one long drawing, and
                     // the only thing that clears the state is a run that succeeds --
                     // which the gate would then be preventing.
                     "CODEX_TIMEOUT",
                 })
            Assert.False(BuildFeedback.ModelCouldNotBeReached(code), code);
    }

    /// <summary>
    /// A quota comes back on a date; a CLI that is not installed comes back when
    /// somebody installs it.
    /// </summary>
    /// <remarks>
    /// The split decides whether the worker sends a horizon. A date on "not signed
    /// in" would be a promise nobody made, and the API blocks indefinitely on those
    /// and says why -- which is what sends an operator to the machine rather than to
    /// a queue.
    /// </remarks>
    [Fact]
    public void WaitingFixesAQuotaAndDoesNotFixAMissingCli()
    {
        Assert.False(BuildFeedback.ModelNeedsAPerson("CODEX_CAPACITY_LIMIT"));
        Assert.False(BuildFeedback.ModelNeedsAPerson("CODEX_BUDGET_EXHAUSTED"));

        Assert.True(BuildFeedback.ModelNeedsAPerson("CODEX_CLI_MISSING"));
        Assert.True(BuildFeedback.ModelNeedsAPerson("CODEX_NOT_INSTALLED"));
        Assert.True(BuildFeedback.ModelNeedsAPerson("CODEX_AUTH_REQUIRED"));
    }

    /// <summary>
    /// What the worker sends, for each of the two shapes of "cannot".
    /// </summary>
    /// <remarks>
    /// The starting value is *available* rather than unknown, and that is a deadlock
    /// fix rather than optimism: the API withholds drawing work from a worker that
    /// says it cannot do it, and only a successful run clears such a state. A worker
    /// that started silent would leave a stored `unavailable` behind with nothing
    /// able to contradict it -- a machine somebody has just fixed, still refused.
    /// </remarks>
    [Fact]
    public void AQuotaIsReportedWithAHorizonAndAMissingCliWithout()
    {
        Assert.Equal("available", CodexHealth.Available.State);
        Assert.Null(CodexHealth.Available.RetryAfter);

        var quota = CodexHealth.From("CODEX_CAPACITY_LIMIT", "the account's quota is exhausted");
        Assert.Equal("paused", quota.State);
        Assert.NotNull(quota.RetryAfter);
        Assert.Contains("CODEX_CAPACITY_LIMIT", quota.Detail);

        var missing = CodexHealth.From("CODEX_AUTH_REQUIRED", "not signed in");
        Assert.Equal("unavailable", missing.State);
        Assert.Null(missing.RetryAfter);
    }

    /// <summary>
    /// The detail a status page may show carries no newline and is bounded.
    /// </summary>
    /// <remarks>
    /// Everything sent here can reach a browser, which is the rule a failure message
    /// already follows.
    /// </remarks>
    [Fact]
    public void TheDetailIsSafeToShow()
    {
        var health = CodexHealth.From(
            "CODEX_CAPACITY_LIMIT",
            "line one" + Environment.NewLine + "line two " + new string('x', 500));

        Assert.NotNull(health.Detail);
        Assert.DoesNotContain(Environment.NewLine, health.Detail);
        Assert.True(health.Detail!.Length <= 300);
    }
}
