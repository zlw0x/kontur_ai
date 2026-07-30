namespace CadAi.CadEngine;

/// <summary>
/// The constraint vocabulary, and the KOMPAS integer each one is.
/// </summary>
/// <remarks>
/// The integers were identified by measurement, not read: the KOMPAS type
/// libraries export no enumerations at all, so each candidate was applied to
/// deliberately wrong geometry and the resulting coordinates said which
/// constraint it was. See `scripts/probe_kompas_constraints.py` and
/// docs/TASK-POSTMVP-007-sketch-constraints.md.
///
/// They live here, next to the COM call that uses them, rather than in the
/// document contracts — a document says what it means, not which integer KOMPAS
/// happens to use for it.
/// </remarks>
public enum ConstraintKind
{
    Fixed,
    PointOnCurve,
    Horizontal,
    Vertical,
    Parallel,
    Perpendicular,
    EqualLength,
    EqualRadius,
    AlignedHorizontally,
    AlignedVertically,
    Coincident,
    Tangent,
    Symmetric,
    Collinear,
    Midpoint
}

public enum DimensionKind { Length, Radius, Diameter, Angle }

/// <summary>
/// Which point of an entity a point constraint is about.
/// </summary>
/// <remarks>
/// Naming it is not optional. In a closed contour consecutive segments meet
/// end-to-start, so a coincidence that always meant "start to start" would be
/// false for every corner of every rectangle — and a check that is false for the
/// commonest case would be turned off rather than fixed.
/// </remarks>
public enum SketchPoint { Start, End, Center }

/// <summary>One assertion about the sketch, with its operands already resolved.</summary>
public sealed record SketchConstraintPlan(
    string Id,
    ConstraintKind Kind,
    string Of,
    string? To = null,
    string? Axis = null,
    SketchPoint OfPoint = SketchPoint.Start,
    SketchPoint ToPoint = SketchPoint.Start);

/// <summary>A named measurement the document states and the build verifies.</summary>
/// <remarks>
/// `To` is named only by an angle, which is the one kind that measures a relation
/// between two entities rather than a property of one. Every other kind leaves it
/// null, and the validator refuses the mismatch rather than ignoring it.
/// </remarks>
public sealed record DrivingDimensionPlan(
    string Id,
    DimensionKind Kind,
    string Of,
    double Value,
    string? To = null);

/// <summary>
/// A sketch entity that can be constrained, reduced to what a check needs.
/// </summary>
/// <remarks>
/// A line, an arc and a circle are all "a curve with a direction, a couple of
/// defining points and possibly a radius". Flattening them here keeps the
/// constraint checks from branching on shape sixteen times over.
/// </remarks>
public sealed record ConstrainedEntity(
    string Id,
    string Kind,
    Point2 Start,
    Point2 End,
    Point2? Center = null,
    double? Radius = null)
{
    public bool IsCurve => Kind is "line" or "arc";
    public bool IsRound => Kind is "circle" or "arc";

    /// <summary>The named point of this entity.</summary>
    /// <remarks>
    /// A circle has only a centre, so every point of it is that centre — which is
    /// why `coincident` between two circles reads as concentricity, exactly as
    /// KOMPAS behaves.
    /// </remarks>
    public Point2 PointAt(SketchPoint which)
    {
        if (Kind == "circle") return Center ?? Start;
        return which switch
        {
            SketchPoint.Start => Start,
            SketchPoint.End => End,
            SketchPoint.Center => Center
                ?? throw new CadAdapterException(
                    "CONSTRAINT_OPERAND_INVALID", "sketch",
                    $"{Id} is a {Kind} and has no centre to constrain."),
            _ => Start
        };
    }

    public double Length => Start.DistanceTo(End);

    public (double X, double Y) Direction => (End.X - Start.X, End.Y - Start.Y);

    public Point2 Midpoint => new((Start.X + End.X) / 2, (Start.Y + End.Y) / 2);
}

/// <summary>
/// How much a sketch is still free to move.
/// </summary>
/// <remarks>
/// Reported, never enforced. A document with explicit coordinates is normally
/// under-constrained and that is fine — the coordinates are the truth, and
/// constraints exist so a customer can edit the delivered model. Over-constrained
/// is the interesting direction, and it is reported the same way rather than
/// guessed at: KOMPAS is the authority on whether its own solver is happy.
/// </remarks>
public sealed record DegreesOfFreedom(int Total, int Removed)
{
    public int Remaining => Total - Removed;
    public bool IsOverConstrained => Removed > Total;

    public override string ToString() =>
        $"{Remaining} of {Total} degrees of freedom remain ({Removed} removed)";
}
