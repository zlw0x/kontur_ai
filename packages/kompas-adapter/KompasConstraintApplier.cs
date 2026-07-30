using System.Globalization;

namespace CadAi.KompasAdapter;

/// <summary>
/// Applies a sketch's declared constraints and dimensions in KOMPAS, then checks
/// that the solver left the geometry alone.
/// </summary>
/// <remarks>
/// The constraints have already been verified true of the coordinates by
/// <see cref="ConstraintValidator"/>, so a correct solver has nothing to do. The
/// check afterwards is not redundant: it is the only thing that would catch a
/// disagreement between our arithmetic and the kernel's, and if the solver *did*
/// move something then one of the two is wrong about the part.
///
/// So the geometry stays authoritative and the constraints ride along, which is
/// what makes the delivered model editable without making the delivered model
/// unpredictable.
/// </remarks>
internal static class KompasConstraintApplier
{
    /// <summary>
    /// How far the solver may move a coordinate before the build stops.
    /// </summary>
    /// <remarks>
    /// A micron. The kernel does its own arithmetic in doubles and will not
    /// reproduce a coordinate bit for bit, but a constraint that was already
    /// satisfied cannot need a real correction.
    /// </remarks>
    private const double SolverDriftMm = 1e-6;

    /// <summary>
    /// Constraints whose KOMPAS form needs an endpoint index we have not probed.
    /// </summary>
    /// <remarks>
    /// `IParametriticConstraint` carries `Index` and `PartnerIndex`, and what
    /// values select which endpoint is unmeasured. Applying one with the defaults
    /// would pin whichever points KOMPAS chose — for a corner of a contour, the
    /// wrong pair — and the delivered model would carry a constraint the document
    /// did not state.
    ///
    /// So these are verified and not applied. That is a smaller lie than applying
    /// the wrong one, and it is recorded in the build's operation log rather than
    /// passed over in silence.
    /// </remarks>
    private static readonly IReadOnlySet<ConstraintKind> NeedsEndpointIndex =
        new HashSet<ConstraintKind>
        {
            ConstraintKind.Coincident,
            ConstraintKind.Midpoint,
            ConstraintKind.PointOnCurve,
            ConstraintKind.AlignedHorizontally,
            ConstraintKind.AlignedVertically,
            ConstraintKind.Collinear
        };

    public sealed record Outcome(int Applied, int VerifiedOnly, int Dimensions);

    /// <summary>Apply what can be applied; returns what was done.</summary>
    public static Outcome Apply(
        IView view,
        SketchPlan plan,
        IReadOnlyDictionary<string, object> drawn)
    {
        var applied = 0;
        var verifiedOnly = 0;
        foreach (var constraint in plan.Declared)
        {
            if (NeedsEndpointIndex.Contains(constraint.Kind))
            {
                verifiedOnly++;
                continue;
            }
            if (!drawn.TryGetValue(constraint.Of, out var subject)) { verifiedOnly++; continue; }
            object? partner = null;
            if (constraint.To is { } to && !drawn.TryGetValue(to, out partner)) { verifiedOnly++; continue; }
            object? axis = null;
            if (constraint.Axis is { } axisId && !drawn.TryGetValue(axisId, out axis)) { verifiedOnly++; continue; }
            ApplyOne(constraint, subject, partner, axis);
            applied++;
        }

        var dimensions = 0;
        foreach (var dimension in plan.Measured)
        {
            if (!drawn.TryGetValue(dimension.Of, out var subject)) continue;
            ApplyDimension(view, dimension, subject, plan);
            dimensions++;
        }
        return new Outcome(applied, verifiedOnly, dimensions);
    }

    private static void ApplyOne(
        SketchConstraintPlan constraint,
        object subject,
        object? partner,
        object? axis)
    {
        var handle = ((IDrawingObject1)subject).NewConstraint()
            ?? throw Failure("CONSTRAINT_NOT_APPLIED",
                $"KOMPAS refused to create a constraint on {constraint.Of}.");
        var item = (IParametriticConstraint)handle;
        item.ConstraintType = KompasConstraintTypes.Of(constraint.Kind);
        if (partner is not null) item.Partner = partner;
        if (axis is not null) item.Axis = axis;
        // `Valid` is deliberately not consulted: it reports false for types that
        // plainly work and true for some that do nothing.
        if (!item.Create())
            throw Failure("CONSTRAINT_NOT_APPLIED",
                $"KOMPAS rejected constraint {constraint.Id} ({constraint.Kind}) on {constraint.Of}.");
    }

    /// <remarks>
    /// A dimension has to be drawn, then bound to its geometry with
    /// `Associate()`, and only then will the driving constraint create on it.
    /// Its variable takes the document's own name, so the same word appears in
    /// the document, in the delivered file and in any later diff.
    /// </remarks>
    private static void ApplyDimension(
        IView view,
        DrivingDimensionPlan dimension,
        object subject,
        SketchPlan plan)
    {
        var entity = plan.NamedEntities().First(item => item.Id == dimension.Of);
        var handle = dimension.Kind switch
        {
            DimensionKind.Length => DrawLinear(view, entity),
            DimensionKind.Radius => DrawRadial(view, entity),
            DimensionKind.Diameter => DrawDiametral(view, entity),
            _ => throw Failure("UNSUPPORTED_DIMENSION",
                $"Dimension {dimension.Id} is of a kind this adapter cannot draw.")
        };

        // The dimension has to be finished before it can be bound: without this
        // Associate() returns false, which reads like a refusal rather than an
        // unfinished object.
        if (!((IDrawingObject)handle).Update())
            throw Failure("DIMENSION_NOT_DRAWN",
                $"KOMPAS rejected the dimension drawn for {dimension.Id}.");
        if (!((IDrawingObject1)handle).Associate())
            throw Failure("DIMENSION_NOT_ASSOCIATED",
                $"KOMPAS would not bind dimension {dimension.Id} to {dimension.Of}.");
        var constraint = ((IDrawingObject1)handle).NewConstraint()
            ?? throw Failure("DIMENSION_NOT_APPLIED",
                $"KOMPAS refused to make dimension {dimension.Id} a driving one.");
        var item = (IParametriticConstraint)constraint;
        item.ConstraintType = KompasConstraintTypes.DrivingDimension;
        item.Variable = dimension.Id;
        if (!item.Create())
            throw Failure("DIMENSION_NOT_APPLIED",
                $"KOMPAS rejected the driving constraint for dimension {dimension.Id}.");

        // The variable now reads back as what KOMPAS measured. Comparing it with
        // the document is the whole reason a dimension is worth applying: it is
        // the kernel's own opinion of the number the drawing stated.
        //
        // Looked up by the document's own name. Reading the whole set instead
        // works for one dimension and then stops, because it answers with a
        // single object when there is one variable and something else when there
        // are several.
        if (view.Variable(dimension.Id) is not { } variable) return;
        var measured = ((IVariable7)variable).Value;
        if (Math.Abs(measured - dimension.Value) > 1e-4)
            throw Failure("DIMENSION_DISAGREES_WITH_KOMPAS",
                $"Dimension {dimension.Id} states {Number(dimension.Value)} mm; KOMPAS measures " +
                $"{Number(measured)} mm on the geometry it was bound to.");
    }

    private static object DrawLinear(IView view, ConstrainedEntity entity)
    {
        var handle = ((ILineDimensions)view.LineDimensions).Add();
        var dimension = (ILineDimension)handle;
        dimension.X1 = entity.Start.X;
        dimension.Y1 = entity.Start.Y;
        dimension.X2 = entity.End.X;
        dimension.Y2 = entity.End.Y;
        // The witness line sits clear of the geometry; it is annotation, and
        // where it sits changes nothing about the part.
        dimension.X3 = entity.Start.X;
        dimension.Y3 = entity.Start.Y + 8;
        return handle;
    }

    private static object DrawRadial(IView view, ConstrainedEntity entity)
    {
        var handle = ((IRadialDimensions)view.RadialDimensions).Add();
        var dimension = (IRadialDimension)handle;
        var centre = entity.Center ?? entity.Start;
        dimension.Xc = centre.X;
        dimension.Yc = centre.Y;
        dimension.Radius = entity.Radius ?? 0;
        return handle;
    }

    private static object DrawDiametral(IView view, ConstrainedEntity entity)
    {
        var handle = ((IDiametralDimensions)view.DiametralDimensions).Add();
        var dimension = (IDiametralDimension)handle;
        var centre = entity.Center ?? entity.Start;
        dimension.Xc = centre.X;
        dimension.Yc = centre.Y;
        dimension.Radius = entity.Radius ?? 0;
        return handle;
    }

    /// <summary>
    /// Did the solver move anything? It should not have had to.
    /// </summary>
    /// <remarks>
    /// The one check that would catch our arithmetic and the kernel's disagreeing
    /// about the same relation. If a constraint that was already satisfied still
    /// caused a correction, one of the two is wrong about the part, and building
    /// on either would be building on a guess.
    /// </remarks>
    public static void RequireGeometryUnmoved(
        SketchPlan plan,
        IReadOnlyDictionary<string, object> drawn)
    {
        foreach (var entity in plan.NamedEntities())
        {
            if (!drawn.TryGetValue(entity.Id, out var handle)) continue;
            if (entity.Kind != "line") continue;
            var segment = (ILineSegment)handle;
            var movedBy = Math.Max(
                new Point2(segment.X1, segment.Y1).DistanceTo(entity.Start),
                new Point2(segment.X2, segment.Y2).DistanceTo(entity.End));
            if (movedBy > SolverDriftMm)
                throw Failure("SOLVER_MOVED_THE_GEOMETRY",
                    $"Applying the constraints moved {entity.Id} by {Number(movedBy)} mm. " +
                    "Every constraint was checked true of the stated coordinates first, so the " +
                    "document and the kernel disagree about this part.");
        }
    }

    private static string Number(double value) => value.ToString("F4", CultureInfo.InvariantCulture);

    private static CadAdapterException Failure(string code, string message) =>
        KompasApi7Adapter.Failure(code, "sketch", message);
}
