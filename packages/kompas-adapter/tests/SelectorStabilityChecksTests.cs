using CadAi.KompasAdapter;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

/// <summary>
/// The verdict on a stability run is graded here rather than inside the run,
/// so a run cannot mark its own homework and the grading can be tested for the
/// failures it is supposed to catch — which a passing real run never exercises.
/// </summary>
public sealed class SelectorStabilityChecksTests
{
    private const double Thickness = 8;

    private static SelectorMatch TopFace(int index, double halfWidth = 20) =>
        new(index, "planar", [-halfWidth, -15, Thickness], [halfWidth, 15, Thickness], [0, 0, 1]);

    private static SelectorOutcome Outcome(
        string id,
        string? expectedError,
        string? actualError,
        params SelectorMatch[] matches) =>
        new(id, "test", expectedError,
            new SelectorResolution(id, "face", 8, [], matches.Length, actualError is null, actualError,
                matches.Select(match => match.Index).ToArray()),
            matches);

    private static SelectorPhase Phase(string name, params SelectorOutcome[] outcomes) =>
        new(name, 8, 24, 3, 1, outcomes);

    private static SelectorPhase HealthyPhase(string name, int topIndex, double halfWidth) =>
        Phase(name,
            Outcome("top_face", null, null, TopFace(topIndex, halfWidth)),
            Outcome("side_face_ambiguous", "SELECTOR_AMBIGUOUS", "SELECTOR_AMBIGUOUS"));

    private static IReadOnlyList<SelectorPhase> HealthyRun() =>
    [
        HealthyPhase("initial", 0, 20),
        HealthyPhase("widened", 3, 30),
        HealthyPhase("reopened", 1, 30)
    ];

    private static StabilityCheck Named(IReadOnlyList<StabilityCheck> checks, string name) =>
        Assert.Single(checks, check => check.Name == name);

    [Fact]
    public void ARunThatHeldUpPassesEveryCheck()
    {
        var checks = SelectorStabilityChecks.Evaluate(HealthyRun(), Thickness);

        Assert.All(checks, check => Assert.True(check.Passed, check.Name + ": " + check.Detail));
    }

    [Fact]
    public void AMissingPhaseIsNotAPass()
    {
        var checks = SelectorStabilityChecks.Evaluate(HealthyRun().Take(2).ToList(), Thickness);

        Assert.False(Named(checks, "phases_recorded").Passed);
    }

    /// <summary>
    /// The failure this milestone exists to prevent: after the rebuild the
    /// selector lands on the bottom face, which still validates and still
    /// builds, and produces a quietly wrong part.
    /// </summary>
    [Fact]
    public void ATopFaceThatBecameTheBottomOneFailsTheRun()
    {
        var phases = new List<SelectorPhase>
        {
            HealthyPhase("initial", 0, 20),
            Phase("widened",
                Outcome("top_face", null, null,
                    new SelectorMatch(1, "planar", [-30, -15, 0], [30, 15, 0], [0, 0, -1])),
                Outcome("side_face_ambiguous", "SELECTOR_AMBIGUOUS", "SELECTOR_AMBIGUOUS")),
            HealthyPhase("reopened", 1, 30)
        };

        var checks = SelectorStabilityChecks.Evaluate(phases, Thickness);

        Assert.False(Named(checks, "top_face_is_the_same_face").Passed);
    }

    [Fact]
    public void AnAmbiguousSelectorThatQuietlyPickedOneFailsTheRun()
    {
        var phases = HealthyRun().ToList();
        phases[2] = Phase("reopened",
            Outcome("top_face", null, null, TopFace(1, 30)),
            Outcome("side_face_ambiguous", "SELECTOR_AMBIGUOUS", null, TopFace(2, 30)));

        var checks = SelectorStabilityChecks.Evaluate(phases, Thickness);

        Assert.False(Named(checks, "selectors_as_declared[reopened]").Passed);
    }

    [Fact]
    public void AnUnresolvedSelectorFailsTheRunToo()
    {
        var phases = HealthyRun().ToList();
        phases[1] = Phase("widened",
            Outcome("top_face", null, "SELECTOR_NO_MATCH"),
            Outcome("side_face_ambiguous", "SELECTOR_AMBIGUOUS", "SELECTOR_AMBIGUOUS"));

        var checks = SelectorStabilityChecks.Evaluate(phases, Thickness);

        Assert.False(Named(checks, "selectors_as_declared[widened]").Passed);
        Assert.False(Named(checks, "top_face_identified").Passed);
    }

    /// <summary>
    /// A run where the plate never actually got wider proves nothing about
    /// rebuild stability, however green the rest of it looks.
    /// </summary>
    [Fact]
    public void ARebuildThatChangedNothingIsReportedAsProvingNothing()
    {
        var phases = new List<SelectorPhase>
        {
            HealthyPhase("initial", 0, 20),
            HealthyPhase("widened", 0, 20),
            HealthyPhase("reopened", 0, 20)
        };

        var checks = SelectorStabilityChecks.Evaluate(phases, Thickness);

        Assert.False(Named(checks, "rebuild_actually_changed_the_model").Passed);
    }

    [Fact]
    public void AStableRawIndexIsRecordedButNotRequired()
    {
        var phases = new List<SelectorPhase>
        {
            HealthyPhase("initial", 0, 20),
            HealthyPhase("widened", 0, 30),
            HealthyPhase("reopened", 0, 30)
        };

        var check = Named(SelectorStabilityChecks.Evaluate(phases, Thickness), "top_face_index_observed");

        Assert.True(check.Passed);
        Assert.Contains("stay 0", check.Detail);
    }

    // --- the catalogue -----------------------------------------------------

    [Fact]
    public void TheCatalogueNamesOneSelectorThatMustFail()
    {
        var catalogue = SelectorCatalogue.AcceptancePlate(2.5, Thickness);

        var mustFail = catalogue.Where(item => item.ExpectedErrorCode is not null).ToList();
        Assert.Equal("SELECTOR_AMBIGUOUS", Assert.Single(mustFail).ExpectedErrorCode);
    }

    /// <summary>
    /// The pair that proves determinism: identical predicates, one extra
    /// position predicate, opposite outcomes.
    /// </summary>
    [Fact]
    public void TheAmbiguousSelectorAndItsRepairDifferOnlyByAPosition()
    {
        var catalogue = SelectorCatalogue.AcceptancePlate(2.5, Thickness);
        var ambiguous = catalogue.Single(item => item.Selector.Id == "side_face_ambiguous").Selector;
        var repaired = catalogue.Single(item => item.Selector.Id == "side_face_max_x").Selector;

        Assert.Equal(ambiguous.Face! with { Position = repaired.Face!.Position }, repaired.Face);
        Assert.Null(ambiguous.Face!.Position);
        Assert.NotNull(repaired.Face!.Position);
    }

    [Fact]
    public void EverySelectorInTheCatalogueCarriesAtLeastOnePredicate()
    {
        foreach (var expectation in SelectorCatalogue.AcceptancePlate(2.5, Thickness))
        {
            var selector = expectation.Selector;
            var predicates = selector.Face is { } face
                ? new object?[] { face.SurfaceType, face.Normal, face.Position, face.AreaMm2, face.RadiusMm, face.Adjacent }
                : [selector.Edge!.CurveType, selector.Edge.LengthMm, selector.Edge.RadiusMm,
                   selector.Edge.DirectionParallelTo, selector.Edge.Position, selector.Edge.Adjacent];
            Assert.Contains(predicates, value => value is not null);
            Assert.NotEmpty(expectation.Purpose);
        }
    }
}
