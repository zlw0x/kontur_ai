using CadAi.KompasAdapter;
using Xunit;

namespace CadAi.KompasAdapter.Tests;

/// <summary>
/// The tests that matter here are the refusals. A sketch that builds into the
/// wrong solid is the failure this gate exists to prevent, and every check
/// below corresponds to a way a generated document can be wrong while still
/// satisfying the schema.
/// </summary>
public sealed class SketchValidatorTests
{
    private static Point2 P(double x, double y) => new(x, y);

    private static SketchPlan Sketch(ContourPlan outer, params ContourPlan[] inner) =>
        new("sketch.test", new BasePlanePlan("XY"), outer, inner, []);

    private static ContourPlan Square(double half = 10) =>
        SketchGeometry.Rectangle(P(0, 0), half * 2, half * 2, 0);

    private static string CodeOf(Action act)
    {
        var error = Assert.Throws<CadAdapterException>(act);
        return error.Code;
    }

    // --- the shapes expand into contours that close ------------------------

    [Fact]
    public void ARectangleExpandsIntoFourClosedSides()
    {
        var contour = Assert.IsType<PathContourPlan>(SketchGeometry.Rectangle(P(5, 5), 40, 20, 0));

        Assert.Equal(4, contour.Segments.Count);
        Assert.All(contour.Segments, segment => Assert.IsType<LineSegmentPlan>(segment));
        SketchValidator.Validate(Sketch(contour));
        Assert.Equal(800, Math.Abs(contour.SignedArea(0.01)), 6);
    }

    [Fact]
    public void ARotatedRectangleKeepsItsAreaAndStillCloses()
    {
        var contour = SketchGeometry.Rectangle(P(0, 0), 40, 20, 30);

        SketchValidator.Validate(Sketch(contour));
        Assert.Equal(800, Math.Abs(contour.SignedArea(0.01)), 6);
    }

    [Fact]
    public void ASlotIsTwoFlanksAndTwoCaps()
    {
        var contour = Assert.IsType<PathContourPlan>(SketchGeometry.Slot(P(-10, 0), P(10, 0), 3));

        Assert.Equal(4, contour.Segments.Count);
        Assert.Equal(2, contour.Segments.OfType<ArcSegmentPlan>().Count());
        SketchValidator.Validate(Sketch(contour));
        // 20 x 6 rectangle plus a circle of radius 3.
        Assert.Equal(20 * 6 + Math.PI * 9, Math.Abs(contour.SignedArea(0.001)), 1);
    }

    /// <summary>
    /// A slot whose ends coincide is a circle. Saying so is better than
    /// emitting two zero-length flanks for the validator to reject, because the
    /// document said something perfectly clear.
    /// </summary>
    [Fact]
    public void ASlotOfZeroLengthIsACircle()
    {
        var contour = Assert.IsType<CircleContourPlan>(SketchGeometry.Slot(P(4, 4), P(4, 4), 3));

        Assert.Equal(3, contour.Radius);
        SketchValidator.Validate(Sketch(contour));
    }

    [Fact]
    public void ADiagonalSlotIsHandledWithoutASpecialCase()
    {
        var contour = SketchGeometry.Slot(P(-10, -10), P(10, 10), 2);

        SketchValidator.Validate(Sketch(contour));
        var length = Math.Sqrt(800);
        Assert.Equal(length * 4 + Math.PI * 4, Math.Abs(contour.SignedArea(0.001)), 1);
    }

    [Fact]
    public void AHexagonHasSixSidesAndTheAreaOfOne()
    {
        var contour = Assert.IsType<PathContourPlan>(
            SketchGeometry.RegularPolygon(P(0, 0), 6, 10, 0));

        Assert.Equal(6, contour.Segments.Count);
        SketchValidator.Validate(Sketch(contour));
        Assert.Equal(1.5 * Math.Sqrt(3) * 100, Math.Abs(contour.SignedArea(0.01)), 6);
    }

    [Fact]
    public void AnArcReportsTheSweepTheDirectionAsksFor()
    {
        var clockwise = new ArcSegmentPlan(P(0, 3), P(0, -3), P(0, 0), CounterClockwise: false);
        var anticlockwise = new ArcSegmentPlan(P(0, 3), P(0, -3), P(0, 0), CounterClockwise: true);

        Assert.Equal(180, clockwise.SweepDegrees, 6);
        Assert.Equal(180, anticlockwise.SweepDegrees, 6);
        Assert.Equal(3, clockwise.StartRadius, 6);
    }

    /// <summary>
    /// The same endpoints and centre, opposite directions: one arc bulges left
    /// of the chord and the other right, so the enclosed area differs. This is
    /// why the sweep direction is in the contract rather than inferred.
    /// </summary>
    [Fact]
    public void TheSweepDirectionChangesWhichRegionAnArcBounds()
    {
        var right = new PathContourPlan([
            new LineSegmentPlan(P(0, -3), P(0, 3)),
            new ArcSegmentPlan(P(0, 3), P(0, -3), P(0, 0), CounterClockwise: false)
        ]);
        var left = new PathContourPlan([
            new LineSegmentPlan(P(0, -3), P(0, 3)),
            new ArcSegmentPlan(P(0, 3), P(0, -3), P(0, 0), CounterClockwise: true)
        ]);

        var half = Math.PI * 9 / 2;
        Assert.Equal(half, Math.Abs(right.SignedArea(0.001)), 1);
        Assert.Equal(half, Math.Abs(left.SignedArea(0.001)), 1);
        // Opposite signs: the two halves wind opposite ways round.
        Assert.NotEqual(Math.Sign(right.SignedArea(0.001)), Math.Sign(left.SignedArea(0.001)));
    }

    // --- refusals ----------------------------------------------------------

    [Fact]
    public void AnUnclosedContourIsRefusedAndSaysHowBigTheGapIs()
    {
        var open = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(10, 10)),
            new LineSegmentPlan(P(10, 10), P(0.5, 10))
        ]);

        var error = Assert.Throws<CadAdapterException>(() => SketchValidator.Validate(Sketch(open)));
        Assert.Equal("SKETCH_CONTOUR_OPEN", error.Code);
        Assert.Contains("does not close", error.SafeMessage);
    }

    /// <summary>
    /// A gap smaller than the tolerance is not closed for the document. Healing
    /// it would be a guess about intent, and this milestone does not guess.
    /// </summary>
    [Fact]
    public void AGapBetweenConsecutiveSegmentsIsNotQuietlyHealed()
    {
        var broken = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0.001), P(10, 10)),
            new LineSegmentPlan(P(10, 10), P(0, 10)),
            new LineSegmentPlan(P(0, 10), P(0, 0))
        ]);

        Assert.Equal("SKETCH_CONTOUR_OPEN", CodeOf(() => SketchValidator.Validate(Sketch(broken))));
    }

    [Fact]
    public void AZeroLengthSegmentIsRefused()
    {
        var degenerate = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(10, 10)),
            new LineSegmentPlan(P(10, 10), P(0, 0))
        ]);

        Assert.Equal("SKETCH_SEGMENT_DEGENERATE",
            CodeOf(() => SketchValidator.Validate(Sketch(degenerate))));
    }

    /// <summary>
    /// An arc whose endpoints sit at different distances from its centre is not
    /// the arc anybody meant, and KOMPAS would build whichever one its own
    /// arithmetic settled on.
    /// </summary>
    [Fact]
    public void AnArcWhoseEndpointsDisagreeAboutItsRadiusIsRefused()
    {
        var wrong = new PathContourPlan([
            new LineSegmentPlan(P(-10, 3), P(10, 3)),
            new ArcSegmentPlan(P(10, 3), P(10, -5), P(10, 0), CounterClockwise: false),
            new LineSegmentPlan(P(10, -5), P(-10, 3))
        ]);

        var error = Assert.Throws<CadAdapterException>(() => SketchValidator.Validate(Sketch(wrong)));
        Assert.Equal("SKETCH_ARC_INCONSISTENT", error.Code);
        Assert.Contains("different distances", error.SafeMessage);
    }

    [Fact]
    public void TheSameSegmentDrawnTwiceIsRefused()
    {
        var duplicated = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(0, 0)),
            new LineSegmentPlan(P(0, 0), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(0, 0))
        ]);

        Assert.Equal("SKETCH_SEGMENT_DUPLICATE",
            CodeOf(() => SketchValidator.Validate(Sketch(duplicated))));
    }

    /// <summary>
    /// A bow-tie: four segments that close perfectly and enclose nothing
    /// coherent. KOMPAS would either fail obscurely or build one lobe.
    /// </summary>
    [Fact]
    public void AContourThatCrossesItselfIsRefused()
    {
        var bowTie = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(10, 10)),
            new LineSegmentPlan(P(10, 10), P(10, 0)),
            new LineSegmentPlan(P(10, 0), P(0, 10)),
            new LineSegmentPlan(P(0, 10), P(0, 0))
        ]);

        Assert.Equal("SKETCH_SELF_INTERSECTION",
            CodeOf(() => SketchValidator.Validate(Sketch(bowTie))));
    }

    [Fact]
    public void ACircleOfNoRadiusIsRefused()
    {
        Assert.Equal("SKETCH_SEGMENT_DEGENERATE",
            CodeOf(() => SketchValidator.Validate(Sketch(new CircleContourPlan(P(0, 0), 0)))));
    }

    // --- islands -----------------------------------------------------------

    [Fact]
    public void IslandsInsideTheProfileAreAccepted()
    {
        SketchValidator.Validate(Sketch(
            Square(20),
            new CircleContourPlan(P(-10, 0), 2.5),
            new CircleContourPlan(P(10, 0), 2.5)));
    }

    [Fact]
    public void AnIslandOutsideTheProfileIsRefused()
    {
        Assert.Equal("SKETCH_ISLAND_OUTSIDE_PROFILE",
            CodeOf(() => SketchValidator.Validate(Sketch(Square(10), new CircleContourPlan(P(40, 0), 2)))));
    }

    [Fact]
    public void AnIslandStraddlingTheProfileEdgeIsRefused()
    {
        Assert.Equal("SKETCH_CONTOURS_INTERSECT",
            CodeOf(() => SketchValidator.Validate(Sketch(Square(10), new CircleContourPlan(P(10, 0), 3)))));
    }

    [Fact]
    public void TwoIslandsThatOverlapAreRefused()
    {
        Assert.Equal("SKETCH_CONTOURS_INTERSECT",
            CodeOf(() => SketchValidator.Validate(Sketch(
                Square(20),
                new CircleContourPlan(P(0, 0), 5),
                new CircleContourPlan(P(4, 0), 5)))));
    }

    /// <summary>
    /// Nesting two levels deep cannot be written down in CAD-IR 1.2, but two
    /// islands that happen to contain one another say the same thing, so the
    /// geometry is checked as well as the shape of the document.
    /// </summary>
    [Fact]
    public void AnIslandInsideAnotherIslandIsRefused()
    {
        Assert.Equal("SKETCH_ISLAND_NESTED",
            CodeOf(() => SketchValidator.Validate(Sketch(
                Square(20),
                new CircleContourPlan(P(0, 0), 8),
                new CircleContourPlan(P(0, 0), 3)))));
    }

    [Fact]
    public void AnIslandIsCheckedForItsOwnClosureToo()
    {
        var open = new PathContourPlan([
            new LineSegmentPlan(P(0, 0), P(2, 0)),
            new LineSegmentPlan(P(2, 0), P(2, 2)),
            new LineSegmentPlan(P(2, 2), P(0.5, 2))
        ]);

        var error = Assert.Throws<CadAdapterException>(
            () => SketchValidator.Validate(Sketch(Square(20), open)));
        Assert.Equal("SKETCH_CONTOUR_OPEN", error.Code);
        Assert.Contains("island 1", error.SafeMessage);
    }

    // --- tessellation ------------------------------------------------------

    /// <summary>
    /// The tessellation is what the containment and crossing tests see, so it
    /// has to be fine enough at every size to agree with the document about
    /// what is inside what, and coarse enough that a large arc is not thousands
    /// of points.
    /// </summary>
    /// <remarks>
    /// The polygon is inscribed, so it is always slightly smaller than the true
    /// circle and the containment test errs towards refusing rather than
    /// accepting. Two parts in a thousand is three orders of magnitude below any
    /// tolerance a drawing states.
    /// </remarks>
    [Fact]
    public void ACircleIsTessellatedFinelyEnoughAtEverySize()
    {
        foreach (var radius in new[] { 0.5, 2.5, 25.0, 250.0 })
        {
            var circle = new CircleContourPlan(P(0, 0), radius);
            var points = circle.Tessellate(SketchGeometry.TessellationToleranceMm);
            var ratio = Math.Abs(circle.SignedArea(SketchGeometry.TessellationToleranceMm))
                        / (Math.PI * radius * radius);

            Assert.InRange(ratio, 0.998, 1.0);
            Assert.InRange(points.Count, 16, 256);
        }
    }

    /// <summary>
    /// A Ø1 hole and a Ø500 boss both matter, and an absolute sagitta alone
    /// serves only one of them: a hundredth of a millimetre on a 0.5 mm radius
    /// is a sixteen-sided polygon.
    /// </summary>
    [Fact]
    public void ASmallCircleGetsMoreSegmentsThanAnAbsoluteToleranceWouldGive()
    {
        var small = new CircleContourPlan(P(0, 0), 0.5)
            .Tessellate(SketchGeometry.TessellationToleranceMm).Count;

        Assert.True(small > 16, $"a Ø1 hole was tessellated into only {small} points");
    }
}
