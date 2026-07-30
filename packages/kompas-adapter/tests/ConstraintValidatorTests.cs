using CadAi.KompasAdapter;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

/// <summary>
/// A constraint is an assertion about coordinates the document already states,
/// so the tests that matter are the refusals: a constraint that does not hold is
/// a document saying two different things about the same part, which in practice
/// means a misread drawing.
/// </summary>
public sealed class ConstraintValidatorTests
{
    private static Point2 P(double x, double y) => new(x, y);

    private static ConstrainedEntity Line(string id, double x1, double y1, double x2, double y2) =>
        new(id, "line", P(x1, y1), P(x2, y2));

    private static ConstrainedEntity Circle(string id, double x, double y, double radius) =>
        new(id, "circle", P(x, y), P(x, y), P(x, y), radius);

    private static ConstrainedEntity Arc(
        string id, double x1, double y1, double x2, double y2, double cx, double cy) =>
        new(id, "arc", P(x1, y1), P(x2, y2), P(cx, cy),
            Math.Sqrt((x1 - cx) * (x1 - cx) + (y1 - cy) * (y1 - cy)));

    /// <summary>A 20 x 10 rectangle with every side named.</summary>
    private static ConstrainedEntity[] Rectangle() =>
    [
        Line("seg.top", 0, 10, 20, 10),
        Line("seg.right", 20, 10, 20, 0),
        Line("seg.bottom", 20, 0, 0, 0),
        Line("seg.left", 0, 0, 0, 10)
    ];

    private static SketchConstraintPlan C(
        string id,
        ConstraintKind kind,
        string of,
        string? to = null,
        string? axis = null,
        SketchPoint ofPoint = SketchPoint.Start,
        SketchPoint toPoint = SketchPoint.Start) =>
        new(id, kind, of, to, axis, ofPoint, toPoint);

    private static DegreesOfFreedom Validate(
        IReadOnlyList<ConstrainedEntity> entities,
        params SketchConstraintPlan[] constraints) =>
        ConstraintValidator.Validate(entities, constraints, []);

    private static string CodeOf(Action act) => Assert.Throws<CadAdapterException>(act).Code;

    // --- constraints that hold ---------------------------------------------

    [Fact]
    public void AConstraintTrueOfTheGeometryIsAccepted()
    {
        Validate(Rectangle(),
            C("c.1", ConstraintKind.Horizontal, "seg.top"),
            C("c.2", ConstraintKind.Vertical, "seg.left"),
            C("c.3", ConstraintKind.Parallel, "seg.top", "seg.bottom"),
            C("c.4", ConstraintKind.Perpendicular, "seg.top", "seg.left"),
            C("c.5", ConstraintKind.EqualLength, "seg.top", "seg.bottom"),
            C("c.6", ConstraintKind.Coincident, "seg.left", "seg.bottom",
                toPoint: SketchPoint.End));
    }

    [Fact]
    public void ACoincidenceBetweenTwoCirclesIsConcentricity()
    {
        // KOMPAS behaves this way too: a circle's defining point is its centre,
        // which is why one constraint type covers both.
        Validate([Circle("hole.a", 5, 5, 3), Circle("hole.b", 5, 5, 8)],
            C("c.concentric", ConstraintKind.Coincident, "hole.a", "hole.b"));
    }

    [Fact]
    public void TangencyHoldsBothWaysRound()
    {
        // Externally tangent: centres 10 apart, radii 4 and 6.
        Validate([Circle("a", 0, 0, 4), Circle("b", 10, 0, 6)],
            C("c.outer", ConstraintKind.Tangent, "a", "b"));
        // Internally tangent: centres 2 apart, radii 4 and 6.
        Validate([Circle("a", 0, 0, 4), Circle("b", 2, 0, 6)],
            C("c.inner", ConstraintKind.Tangent, "a", "b"));
        // A circle of radius 5 centred 5 above a horizontal line touches it.
        Validate([Circle("a", 10, 5, 5), Line("l", 0, 0, 40, 0)],
            C("c.line", ConstraintKind.Tangent, "a", "l"));
    }

    [Fact]
    public void AMidpointAndAPointOnACurveAreCheckedAgainstTheRealPositions()
    {
        Validate([Line("axis", 0, 0, 20, 0), Line("stub", 10, 0, 10, 5)],
            C("c.mid", ConstraintKind.Midpoint, "stub", "axis"),
            C("c.on", ConstraintKind.PointOnCurve, "stub", "axis"));
    }

    [Fact]
    public void SymmetryIsCheckedByMirroringAcrossTheAxis()
    {
        // The axis is x = 10; the left segment mirrors onto the right one.
        Validate(
            [
                Line("seg.left", 5, 0, 5, 8),
                Line("seg.right", 15, 0, 15, 8),
                Line("line.mid", 10, -5, 10, 15)
            ],
            C("c.mirror", ConstraintKind.Symmetric, "seg.left", "seg.right", "line.mid"));
    }

    [Fact]
    public void CollinearityNeedsBothParallelismAndAPointOnTheLine()
    {
        Validate([Line("a", 0, 0, 10, 0), Line("b", 20, 0, 30, 0)],
            C("c.collinear", ConstraintKind.Collinear, "b", "a"));
    }

    /// <summary>
    /// `fixed` says the entity may not be moved by a later edit. That is about
    /// editing, not about coordinates, so there is nothing it can fail.
    /// </summary>
    [Fact]
    public void FixedIsAlwaysSatisfiedBecauseItSaysNothingAboutCoordinates()
    {
        Validate(Rectangle(), C("c.pin", ConstraintKind.Fixed, "seg.top"));
    }

    // --- the refusals that matter ------------------------------------------

    /// <summary>
    /// The headline case. An extraction that says two edges are parallel while
    /// the coordinates it also extracted say otherwise has misread one of them,
    /// and until this check existed nothing could tell.
    /// </summary>
    [Fact]
    public void AParallelConstraintOnEdgesThatAreNotParallelIsRefused()
    {
        var error = Assert.Throws<CadAdapterException>(() => Validate(Rectangle(),
            C("c.wrong", ConstraintKind.Parallel, "seg.top", "seg.left")));

        Assert.Equal("CONSTRAINT_NOT_SATISFIED", error.Code);
        Assert.Contains("seg.top parallel seg.left", error.SafeMessage);
        Assert.Contains("not an instruction to change it", error.SafeMessage);
    }

    [Fact]
    public void AHorizontalConstraintOnASlopingSegmentIsRefused()
    {
        Assert.Equal("CONSTRAINT_NOT_SATISFIED",
            CodeOf(() => Validate([Line("slope", 0, 0, 10, 1)],
                C("c.h", ConstraintKind.Horizontal, "slope"))));
    }

    [Fact]
    public void ACoincidenceBetweenPointsThatDoNotCoincideIsRefused()
    {
        Assert.Equal("CONSTRAINT_NOT_SATISFIED",
            CodeOf(() => Validate([Line("a", 0, 0, 10, 0), Line("b", 0.5, 0, 10, 5)],
                C("c.co", ConstraintKind.Coincident, "a", "b"))));
    }

    [Fact]
    public void TangencyThatMissesByAMillimetreIsRefused()
    {
        Assert.Equal("CONSTRAINT_NOT_SATISFIED",
            CodeOf(() => Validate([Circle("a", 0, 0, 4), Circle("b", 11, 0, 6)],
                C("c.t", ConstraintKind.Tangent, "a", "b"))));
    }

    [Fact]
    public void SymmetryThatIsNotAMirrorImageIsRefused()
    {
        Assert.Equal("CONSTRAINT_NOT_SATISFIED",
            CodeOf(() => Validate(
                [
                    Line("seg.left", 5, 0, 5, 8),
                    Line("seg.right", 16, 0, 16, 8),
                    Line("line.mid", 10, -5, 10, 15)
                ],
                C("c.mirror", ConstraintKind.Symmetric, "seg.left", "seg.right", "line.mid"))));
    }

    // --- addressing --------------------------------------------------------

    [Fact]
    public void AConstraintNamingAnEntityTheSketchDoesNotHaveIsRefused()
    {
        Assert.Equal("CONSTRAINT_OPERAND_MISSING",
            CodeOf(() => Validate(Rectangle(), C("c.x", ConstraintKind.Horizontal, "seg.absent"))));
    }

    [Fact]
    public void TwoEntitiesSharingANameAreRefusedBeforeAnyConstraintIsChecked()
    {
        Assert.Equal("SKETCH_ENTITY_DUPLICATE",
            CodeOf(() => Validate([Line("same", 0, 0, 1, 0), Line("same", 0, 1, 1, 1)])));
    }

    [Fact]
    public void ADirectionConstraintOnACircleIsRefusedAsTheWrongKindOfOperand()
    {
        var error = Assert.Throws<CadAdapterException>(() => Validate(
            [Circle("hole", 0, 0, 3)], C("c.h", ConstraintKind.Horizontal, "hole")));

        Assert.Equal("CONSTRAINT_OPERAND_INVALID", error.Code);
        Assert.Contains("is a circle", error.SafeMessage);
    }

    [Fact]
    public void AnEqualRadiusConstraintBetweenTwoStraightSegmentsIsRefused()
    {
        Assert.Equal("CONSTRAINT_OPERAND_INVALID",
            CodeOf(() => Validate(Rectangle(),
                C("c.r", ConstraintKind.EqualRadius, "seg.top", "seg.bottom"))));
    }

    // --- duplicates and contradictions -------------------------------------

    /// <remarks>
    /// Stating the same relation twice does the geometry no harm and the document
    /// plenty: it usually means one of the two meant a different pair, and the
    /// duplicate hid the mistake.
    /// </remarks>
    [Fact]
    public void TheSameRelationStatedTwiceIsRefusedEvenWithTheOperandsSwapped()
    {
        Assert.Equal("CONSTRAINT_DUPLICATE",
            CodeOf(() => Validate(Rectangle(),
                C("c.1", ConstraintKind.Parallel, "seg.top", "seg.bottom"),
                C("c.2", ConstraintKind.Parallel, "seg.bottom", "seg.top"))));
    }

    [Fact]
    public void ASegmentCannotBeDeclaredBothHorizontalAndVertical()
    {
        var error = Assert.Throws<CadAdapterException>(() => Validate([Line("a", 0, 0, 0, 0)],
            C("c.h", ConstraintKind.Horizontal, "a"),
            C("c.v", ConstraintKind.Vertical, "a")));

        Assert.Equal("CONSTRAINT_CONTRADICTION", error.Code);
        Assert.Contains("cannot both hold", error.SafeMessage);
    }

    [Fact]
    public void APairCannotBeDeclaredBothParallelAndPerpendicular()
    {
        Assert.Equal("CONSTRAINT_CONTRADICTION",
            CodeOf(() => Validate(Rectangle(),
                C("c.p", ConstraintKind.Parallel, "seg.top", "seg.bottom"),
                C("c.q", ConstraintKind.Perpendicular, "seg.bottom", "seg.top"))));
    }

    // --- driving dimensions -------------------------------------------------

    [Fact]
    public void ADimensionThatMatchesTheGeometryIsAccepted()
    {
        ConstraintValidator.Validate(
            [Line("seg.top", 0, 10, 20, 10), Circle("hole", 5, 5, 2.5)],
            [],
            [
                new DrivingDimensionPlan("base_width", DimensionKind.Length, "seg.top", 20),
                new DrivingDimensionPlan("hole_radius", DimensionKind.Radius, "hole", 2.5),
                new DrivingDimensionPlan("hole_dia", DimensionKind.Diameter, "hole", 5)
            ]);
    }

    /// <summary>
    /// A dimension is what a customer reads off the drawing. One that disagrees
    /// with what it dimensions is a document contradicting itself, and shipping
    /// it would ship a part that does not match its own label.
    /// </summary>
    [Fact]
    public void ADimensionThatDisagreesWithTheGeometryIsRefused()
    {
        var error = Assert.Throws<CadAdapterException>(() => ConstraintValidator.Validate(
            [Line("seg.top", 0, 10, 20, 10)],
            [],
            [new DrivingDimensionPlan("base_width", DimensionKind.Length, "seg.top", 25)]));

        Assert.Equal("DIMENSION_DISAGREES_WITH_GEOMETRY", error.Code);
        Assert.Contains("25.0000", error.SafeMessage);
        Assert.Contains("20.0000", error.SafeMessage);
    }

    // --- angular dimensions -------------------------------------------------

    /// <summary>
    /// An angle is the one dimension that measures a relation rather than a
    /// property, and the only one that names two entities.
    /// </summary>
    [Fact]
    public void AnAngleThatMatchesTheTwoEntitiesIsAccepted()
    {
        ConstraintValidator.Validate(
            [Line("base", 0, 0, 40, 0), Line("arm", 0, 0, 20, 20)],
            [],
            [new DrivingDimensionPlan("corner", DimensionKind.Angle, "base", 45, "arm")]);
    }

    [Fact]
    public void AnAngleThatDisagreesWithTheTwoEntitiesIsRefused()
    {
        var error = Assert.Throws<CadAdapterException>(() => ConstraintValidator.Validate(
            [Line("base", 0, 0, 40, 0), Line("arm", 0, 0, 20, 20)],
            [],
            [new DrivingDimensionPlan("corner", DimensionKind.Angle, "base", 60, "arm")]));

        Assert.Equal("DIMENSION_DISAGREES_WITH_GEOMETRY", error.Code);
        Assert.Contains("degrees", error.SafeMessage);
    }

    [Fact]
    public void AnAngleNamingOnlyOneEntityIsRefused()
    {
        var error = Assert.Throws<CadAdapterException>(() => ConstraintValidator.Validate(
            [Line("base", 0, 0, 40, 0)],
            [],
            [new DrivingDimensionPlan("corner", DimensionKind.Angle, "base", 45)]));

        Assert.Equal("UNSUPPORTED_DIMENSION", error.Code);
        Assert.Contains("between two", error.SafeMessage);
    }

    /// <remarks>
    /// A length that names a second entity has not been half-written; it has been
    /// written by something that thought it was an angle. Ignoring the extra name
    /// would dimension the wrong thing quietly.
    /// </remarks>
    [Fact]
    public void ALengthThatNamesASecondEntityIsRefused()
    {
        Assert.Equal("UNSUPPORTED_DIMENSION",
            CodeOf(() => ConstraintValidator.Validate(
                [Line("a", 0, 0, 20, 0), Line("b", 0, 5, 20, 5)],
                [],
                [new DrivingDimensionPlan("w", DimensionKind.Length, "a", 20, "b")])));
    }

    [Fact]
    public void ARadiusDimensionOnAStraightSegmentIsRefused()
    {
        Assert.Equal("CONSTRAINT_OPERAND_INVALID",
            CodeOf(() => ConstraintValidator.Validate(
                [Line("seg.top", 0, 10, 20, 10)],
                [],
                [new DrivingDimensionPlan("r", DimensionKind.Radius, "seg.top", 5)])));
    }

    [Fact]
    public void ADiameterIsTwiceTheRadiusAndIsCheckedAsSuch()
    {
        Assert.Equal("DIMENSION_DISAGREES_WITH_GEOMETRY",
            CodeOf(() => ConstraintValidator.Validate(
                [Circle("hole", 0, 0, 2.5)],
                [],
                [new DrivingDimensionPlan("d", DimensionKind.Diameter, "hole", 2.5)])));
    }

    // --- degrees of freedom -------------------------------------------------

    /// <remarks>
    /// Reported, never enforced. A document with explicit coordinates is normally
    /// under-constrained and that is fine: the coordinates are the truth, and the
    /// constraints exist so the delivered model can be edited.
    /// </remarks>
    [Fact]
    public void DegreesOfFreedomAreCountedAndReportedRatherThanEnforced()
    {
        var freedom = Validate(Rectangle(),
            C("c.1", ConstraintKind.Horizontal, "seg.top"),
            C("c.2", ConstraintKind.Vertical, "seg.left"),
            C("c.3", ConstraintKind.Coincident, "seg.left", "seg.bottom",
                toPoint: SketchPoint.End));

        Assert.Equal(16, freedom.Total);
        Assert.Equal(4, freedom.Removed);
        Assert.Equal(12, freedom.Remaining);
        Assert.False(freedom.IsOverConstrained);
        Assert.Contains("12 of 16", freedom.ToString());
    }

    [Fact]
    public void AnArcCountsForMoreThanALineAndACircleForLess()
    {
        var arc = ConstraintValidator.Validate([Arc("a", 0, 5, 5, 0, 0, 0)], [], []);
        var circle = ConstraintValidator.Validate([Circle("c", 0, 0, 5)], [], []);
        var line = ConstraintValidator.Validate([Line("l", 0, 0, 5, 0)], [], []);

        Assert.Equal(5, arc.Total);
        Assert.Equal(4, line.Total);
        Assert.Equal(3, circle.Total);
    }

    [Fact]
    public void OverConstrainingIsReportedRatherThanRefused()
    {
        // Two circles pinned and made concentric removes more than they have.
        var freedom = Validate([Circle("a", 0, 0, 3), Circle("b", 0, 0, 3)],
            C("c.1", ConstraintKind.Fixed, "a"),
            C("c.2", ConstraintKind.Fixed, "b"),
            C("c.3", ConstraintKind.Coincident, "a", "b"));

        Assert.True(freedom.IsOverConstrained);
    }

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
