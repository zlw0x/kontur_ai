using CadAi.CadEngine;
using CadAi.CodexRunner;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// Whether a failed claimed job says so, and which failures end it.
/// </summary>
/// <remarks>
/// `JobStatus.FAILED` exists so an order that will not finish stops looking like one
/// that has not started. Two things have to hold for that to reach a customer: the
/// failure must be recognised as one, and the worker must decide it is the end.
///
/// The first was missing entirely for a whole class of failure.
/// `CodexRunnerException` and `WorkerException` both carry a code and a safe message
/// and neither derives from the other, and only the second was caught — so an
/// exhausted quota, a timed-out run and a missing CLI all went past the reporting
/// branch into the claim loop's blanket backoff. Never reported, on any attempt.
///
/// These assert the decision rather than the HTTP call. That the report is sent is
/// where the report is sent; that the worker decides to send one is here.
/// </remarks>
public sealed class ClaimedJobFailureTests
{
    /// <summary>
    /// A Codex failure is a failure this side can name.
    /// </summary>
    /// <remarks>
    /// The assertion that would have caught the run that ended with an empty
    /// `output/`, a job still leased and a page saying "waiting". Before this,
    /// `Typed` did not exist and the `catch` matched one of the two types.
    /// </remarks>
    [Fact]
    public void ACodexFailureCarriesItsCodeAndMessage()
    {
        var typed = ClaimLoop.Typed(new CodexRunnerException(
            "CODEX_CAPACITY_LIMIT", "You've hit your usage limit; try again at Aug 8th."));

        Assert.NotNull(typed);
        Assert.Equal("CODEX_CAPACITY_LIMIT", typed!.Value.Code);
        Assert.Contains("usage limit", typed.Value.Message);
    }

    [Fact]
    public void AWorkerFailureStillCarriesItsCodeAndMessage()
    {
        var typed = ClaimLoop.Typed(new WorkerException("SHELL_NO_CAVITY", "no room for the wall"));

        Assert.Equal("SHELL_NO_CAVITY", typed!.Value.Code);
    }

    /// <summary>
    /// Anything without a code falls through to the backoff, and should.
    /// </summary>
    /// <remarks>
    /// An exception this worker did not name is a bug in this worker, not a verdict
    /// about the drawing. Reporting one as the job's failure would tell a customer
    /// their drawing was wrong because a `NullReferenceException` escaped.
    /// </remarks>
    [Theory]
    [InlineData(typeof(InvalidOperationException))]
    [InlineData(typeof(IOException))]
    public void AnUntypedExceptionIsNotTheJobsVerdict(Type type)
    {
        var error = (Exception)Activator.CreateInstance(type)!;

        Assert.Null(ClaimLoop.Typed(error));
    }

    /// <summary>
    /// A quota that returns on a date ends the job on the first attempt.
    /// </summary>
    /// <remarks>
    /// Three of three would have ended it anyway; the point is the first. Every retry
    /// before the date is a lease cycle spent to be told the same thing, and until the
    /// last one the customer is shown nothing at all.
    /// </remarks>
    [Fact]
    public void AnExhaustedQuotaEndsTheJobOnTheFirstAttempt()
    {
        Assert.True(ClaimLoop.EndsTheJob("CODEX_CAPACITY_LIMIT", attempt: 1, maxAttempts: 3));
    }

    /// <summary>
    /// A machine failure another worker might get past keeps its retries.
    /// </summary>
    /// <remarks>
    /// The behaviour that was right all along and is deliberately unchanged: a
    /// container that would not start may start next time.
    /// </remarks>
    [Fact]
    public void AContainerThatWouldNotStartIsTriedAgain()
    {
        Assert.False(ClaimLoop.EndsTheJob("CONTAINER_START_FAILED", attempt: 1, maxAttempts: 3));
        Assert.True(ClaimLoop.EndsTheJob("CONTAINER_START_FAILED", attempt: 3, maxAttempts: 3));
    }

    /// <remarks>
    /// A repairable failure has already been through the repair loop by the time it
    /// arrives here, so a fresh attempt runs the same model calls on the same drawing
    /// and reaches the same place.
    /// </remarks>
    [Fact]
    public void ADocumentTheAgentCouldNotFixEndsTheJob()
    {
        Assert.True(ClaimLoop.EndsTheJob("SHAPE_CLAIM_CONTRADICTED", attempt: 1, maxAttempts: 3));
    }

    [Fact]
    public void TheLastPermittedAttemptEndsTheJobWhateverTheCode()
    {
        Assert.True(ClaimLoop.EndsTheJob("SOMETHING_NEW", attempt: 3, maxAttempts: 3));
        Assert.False(ClaimLoop.EndsTheJob("SOMETHING_NEW", attempt: 2, maxAttempts: 3));
    }

    /// <summary>
    /// Every exception type in this tree that carries a code is named by `Typed`.
    /// </summary>
    /// <remarks>
    /// Twice now the same defect: a failure type the reporting filter did not match
    /// went past it into the claim loop's blanket backoff, so the job was retried to
    /// exhaustion and **never reported on any attempt**. First
    /// `CodexRunnerException`; then, found by a real run through the web path,
    /// `CadAdapterException` -- the type the CAD-IR gate and the engine raise, which
    /// is what a refused document arrives as after the repairs are spent.
    ///
    /// The customer's page ended on `LEASE_LOST`: the reaper's code for "the worker
    /// said nothing", which is true and says nothing about the drawing.
    ///
    /// Enumerated rather than exampled, because the failure mode is a type nobody
    /// added -- and one example per type is exactly what let the second one through.
    /// </remarks>
    [Fact]
    public void TheThreeTypedFailuresAreAllNamed()
    {
        Assert.Equal(
            ("WORKER_CODE", "worker message"),
            ClaimLoop.Typed(new WorkerException("WORKER_CODE", "worker message")));

        Assert.Equal(
            ("CODEX_CAPACITY_LIMIT", "the quota is exhausted"),
            ClaimLoop.Typed(new CadAi.CodexRunner.CodexRunnerException(
                "CODEX_CAPACITY_LIMIT", "the quota is exhausted")));

        Assert.Equal(
            ("CAD_IR_INVALID", "the document was refused"),
            ClaimLoop.Typed(new CadAdapterException(
                "CAD_IR_INVALID", "validation", "the document was refused")));

        // Anything this worker did not name is a bug in the worker rather than a
        // verdict about the drawing, and still falls through to a retry.
        Assert.Null(ClaimLoop.Typed(new InvalidOperationException("something else")));
    }
}
