using CadAi.GeometryValidation;
using Xunit;

namespace CadAi.GeometryValidation.Tests;

/// <summary>
/// The bounding box is measured from the STL, and an STL of a curved surface is
/// an inscribed approximation. That makes the comparison asymmetric, which only
/// surfaced when arcs arrived: a flat-sided prism tessellates exactly.
/// </summary>
public sealed class BoundingBoxToleranceTests
{
    private static ExpectedGeometry Expected(double tolerance = 0.05) =>
        new(80, 30, 15, SolidBodyCount: 1, ThroughHoleCount: 2, Tolerance: tolerance);

    private static bool Accepts(double measuredWidth, double tolerance = 0.05) =>
        GeometryValidator.BoundsMatch([measuredWidth, 30, 15], Expected(tolerance));

    [Fact]
    public void AnExactMeshPasses()
    {
        Assert.True(Accepts(80));
    }

    /// <summary>
    /// The real case: an 80 mm part with Ø30 end caps measured 79.898 at a
    /// 0.05 mm export sag, and 79.980 once the sag was tightened.
    /// </summary>
    [Fact]
    public void AMeshShortByTheChordToleranceStillPasses()
    {
        Assert.True(Accepts(80 - 0.05 - ExpectedGeometry.MeshChordToleranceMm + 1e-9));
    }

    [Fact]
    public void AMeshShorterThanTheTessellationCanExplainFails()
    {
        Assert.False(Accepts(80 - 0.05 - ExpectedGeometry.MeshChordToleranceMm - 0.001));
    }

    /// <summary>
    /// An inscribed mesh cannot exceed the solid, so any excess is a real
    /// dimensional error and gets no chord allowance at all.
    /// </summary>
    [Fact]
    public void AMeshWiderThanExpectedIsHeldToTheStatedToleranceAlone()
    {
        Assert.True(Accepts(80.05));
        Assert.False(Accepts(80.05 + 0.001));
    }

    [Fact]
    public void AZeroToleranceStillAllowsTheTessellationButNothingElse()
    {
        Assert.True(Accepts(80 - ExpectedGeometry.MeshChordToleranceMm, tolerance: 0));
        Assert.False(Accepts(80.001, tolerance: 0));
    }
}
