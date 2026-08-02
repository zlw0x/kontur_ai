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
}
