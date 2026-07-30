using CadAi.CadEngine;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

/// <summary>
/// The KOMPAS integers, pinned to what was measured for them.
/// </summary>
/// <remarks>
/// These used to sit with the constraint-validator tests, because the constants
/// used to sit with the vocabulary. Both moved when the engine became replaceable
/// (ADR-023): what a document means is neutral, and which number this engine uses
/// for it is not.
///
/// They are worth pinning because none of them was read. The type libraries
/// export no enumerations, so every value here came from building geometry and
/// measuring what moved - and a wrong edit would otherwise show up as a
/// constraint that silently does something else rather than as a failing test.
/// </remarks>
public sealed class KompasConstraintTypeTests
{
    // --- the KOMPAS integers ------------------------------------------------

    /// <summary>
    /// The constants were identified by measurement, not read: the type libraries
    /// export no enumerations at all. Pinning them here means a wrong edit shows
    /// up as a failing test rather than as a constraint that silently does
    /// something else.
    /// </summary>
    [Fact]
    public void EveryConstraintKindMapsToTheKompasTypeThatWasMeasuredForIt()
    {
        Assert.Equal(1, KompasConstraintTypes.Of(ConstraintKind.Fixed));
        Assert.Equal(2, KompasConstraintTypes.Of(ConstraintKind.PointOnCurve));
        Assert.Equal(3, KompasConstraintTypes.Of(ConstraintKind.Horizontal));
        Assert.Equal(4, KompasConstraintTypes.Of(ConstraintKind.Vertical));
        Assert.Equal(5, KompasConstraintTypes.Of(ConstraintKind.Parallel));
        Assert.Equal(6, KompasConstraintTypes.Of(ConstraintKind.Perpendicular));
        Assert.Equal(7, KompasConstraintTypes.Of(ConstraintKind.EqualLength));
        Assert.Equal(8, KompasConstraintTypes.Of(ConstraintKind.EqualRadius));
        Assert.Equal(9, KompasConstraintTypes.Of(ConstraintKind.AlignedHorizontally));
        Assert.Equal(10, KompasConstraintTypes.Of(ConstraintKind.AlignedVertically));
        Assert.Equal(11, KompasConstraintTypes.Of(ConstraintKind.Coincident));
        Assert.Equal(15, KompasConstraintTypes.Of(ConstraintKind.Tangent));
        Assert.Equal(16, KompasConstraintTypes.Of(ConstraintKind.Symmetric));
        Assert.Equal(17, KompasConstraintTypes.Of(ConstraintKind.Collinear));
        Assert.Equal(20, KompasConstraintTypes.Of(ConstraintKind.Midpoint));
        Assert.Equal(13, KompasConstraintTypes.DrivingDimension);
        Assert.Equal(14, KompasConstraintTypes.FixedDimension);
    }

    /// <summary>
    /// A dimension carries both, and only both make it drive. With 13 alone the
    /// variable reports what KOMPAS measured: setting it changes nothing and a
    /// rebuild puts the old number back. Measured on a 16 mm segment driven to
    /// 50 mm.
    /// </summary>
    [Fact]
    public void ADrivingDimensionNeedsTheNamingTypeAndTheFixingTypeBoth()
    {
        Assert.NotEqual(KompasConstraintTypes.DrivingDimension,
            KompasConstraintTypes.FixedDimension);
    }

    [Fact]
    public void EveryKindInTheVocabularyHasAKompasTypeSoNoneCanBeAddedWithoutOne()
    {
        foreach (var kind in Enum.GetValues<ConstraintKind>())
            Assert.True(KompasConstraintTypes.Of(kind) > 0, $"{kind} has no KOMPAS type");
    }

    // --- which point an index selects ---------------------------------------

    /// <summary>
    /// Measured the same way, and pinned here for the same reason. These numbers
    /// decide *which point* a constraint is about, so a wrong one produces a model
    /// that builds, exports and measures correctly while carrying a constraint the
    /// document never stated.
    /// </summary>
    [Fact]
    public void ASegmentNumbersItsPointsStartEndMidpoint()
    {
        Assert.Equal(0, KompasPointIndex.Of("line", SketchPoint.Start));
        Assert.Equal(1, KompasPointIndex.Of("line", SketchPoint.End));
    }

    /// <summary>
    /// The trap this milestone was held up by. An arc's numbering is not a
    /// segment's: 0 is its centre, and the ends come after. One table for both
    /// would have turned every `concentric` between arcs into a coincidence of
    /// their start points.
    /// </summary>
    [Fact]
    public void AnArcNumbersItsCentreFirstAndItsEndsAfter()
    {
        Assert.Equal(0, KompasPointIndex.Of("arc", SketchPoint.Center));
        Assert.Equal(1, KompasPointIndex.Of("arc", SketchPoint.Start));
        Assert.Equal(2, KompasPointIndex.Of("arc", SketchPoint.End));
    }

    [Fact]
    public void ACircleHasOnlyItsCentreWhicheverPointIsNamed()
    {
        Assert.Equal(0, KompasPointIndex.Of("circle", SketchPoint.Center));
        Assert.Equal(0, KompasPointIndex.Of("circle", SketchPoint.Start));
        Assert.Equal(0, KompasPointIndex.Of("circle", SketchPoint.End));
    }

    [Fact]
    public void AskingASegmentForACentreIsRefusedRatherThanDefaulted()
    {
        var error = Assert.Throws<CadAdapterException>(
            () => KompasPointIndex.Of("line", SketchPoint.Center));

        Assert.Equal("CONSTRAINT_OPERAND_INVALID", error.Code);
        Assert.Contains("no centre", error.SafeMessage);
    }

    /// <summary>
    /// Which types read which index, measured by sweeping both and watching what
    /// changed the answer. Setting one a type ignores is harmless; recording which
    /// are real is what stops a later reader inventing a meaning for a number that
    /// has none.
    /// </summary>
    [Fact]
    public void OnlyTheTypesThatWereMeasuredToReadAnIndexAreGivenOne()
    {
        foreach (var kind in new[]
                 {
                     ConstraintKind.Coincident, ConstraintKind.AlignedHorizontally,
                     ConstraintKind.AlignedVertically
                 })
        {
            Assert.True(KompasConstraintOperands.UsesSubjectPoint(kind));
            Assert.True(KompasConstraintOperands.UsesPartnerPoint(kind));
        }

        // The partner contributes a whole entity by definition: its midpoint in
        // one case, its curve in the other.
        foreach (var kind in new[] { ConstraintKind.Midpoint, ConstraintKind.PointOnCurve })
        {
            Assert.True(KompasConstraintOperands.UsesSubjectPoint(kind));
            Assert.False(KompasConstraintOperands.UsesPartnerPoint(kind));
        }

        // Collinear is a relation between two entities. Every index pair produced
        // the identical result, including -1.
        Assert.False(KompasConstraintOperands.UsesSubjectPoint(ConstraintKind.Collinear));
        Assert.False(KompasConstraintOperands.UsesPartnerPoint(ConstraintKind.Collinear));
    }
}
