using System.Globalization;

namespace CadAi.KompasAdapter;

/// <summary>
/// Checks that every constraint a sketch declares is already true of it.
/// </summary>
/// <remarks>
/// This is the whole point of the milestone's design. A constraint is an
/// assertion about the coordinates the document states, not an instruction that
/// produces them, so a constraint that does not hold is a document saying two
/// different things about the same part.
///
/// In practice that means a misread drawing. An extraction that says "these two
/// edges are parallel" while the coordinates it also extracted say otherwise has
/// misread one of the two, and until now nothing could tell.
///
/// Nothing is repaired. The geometry is not nudged to satisfy the constraint and
/// the constraint is not dropped to satisfy the geometry — either would be a
/// guess about which half of the document was right.
/// </remarks>
public static class ConstraintValidator
{
    /// <summary>
    /// How exactly a declared relation must hold.
    /// </summary>
    /// <remarks>
    /// Looser than the point tolerance, because a coordinate is written to a few
    /// decimals and a derived relation accumulates the rounding of both operands.
    /// A hundredth of a degree of parallelism, or a micron of coincidence, is
    /// well inside any drawing's intent and well outside a genuine mistake.
    /// </remarks>
    private const double Tolerance = 1e-6;

    /// <summary>Relative tolerance for angles, applied to unit-normalised vectors.</summary>
    private const double AngleTolerance = 1e-9;

    public static DegreesOfFreedom Validate(
        IReadOnlyList<ConstrainedEntity> entities,
        IReadOnlyList<SketchConstraintPlan> constraints,
        IReadOnlyList<DrivingDimensionPlan> dimensions)
    {
        var byId = Index(entities);
        RejectDuplicates(constraints);
        RejectContradictions(constraints);

        foreach (var constraint in constraints)
            Check(constraint, byId);
        foreach (var dimension in dimensions)
            CheckDimension(dimension, byId);

        return Count(entities, constraints);
    }

    private static Dictionary<string, ConstrainedEntity> Index(IReadOnlyList<ConstrainedEntity> entities)
    {
        var byId = new Dictionary<string, ConstrainedEntity>(StringComparer.Ordinal);
        foreach (var entity in entities)
            if (!byId.TryAdd(entity.Id, entity))
                throw Invalid("SKETCH_ENTITY_DUPLICATE",
                    $"Two sketch entities are named {entity.Id}, so a constraint on it means two things.");
        return byId;
    }

    private static ConstrainedEntity Resolve(
        string id,
        Dictionary<string, ConstrainedEntity> byId,
        string what) =>
        byId.TryGetValue(id, out var entity)
            ? entity
            : throw Invalid("CONSTRAINT_OPERAND_MISSING", $"{what} names {id}, which the sketch has no entity for.");

    /// <remarks>
    /// The same relation stated twice is not harmful to the geometry, but it is
    /// harmful to the document: it usually means one of the two meant a different
    /// pair, and the duplicate hid the mistake.
    /// </remarks>
    private static void RejectDuplicates(IReadOnlyList<SketchConstraintPlan> constraints)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var constraint in constraints)
        {
            // Unordered for the symmetric relations: parallel(a, b) and
            // parallel(b, a) are one statement.
            var operands = constraint.To is null
                ? $"{constraint.Of}.{constraint.OfPoint}"
                : string.Join("|", new[]
                    {
                        $"{constraint.Of}.{constraint.OfPoint}",
                        $"{constraint.To}.{constraint.ToPoint}"
                    }.Order(StringComparer.Ordinal));
            var key = $"{constraint.Kind}:{operands}:{constraint.Axis}";
            if (!seen.Add(key))
                throw Invalid("CONSTRAINT_DUPLICATE",
                    $"Constraint {constraint.Id} states {Describe(constraint)} a second time.");
        }
    }

    /// <remarks>
    /// Only the contradictions that are contradictions whatever the geometry is.
    /// A pair cannot be both parallel and perpendicular, and a segment cannot be
    /// both horizontal and vertical. Everything subtler than that shows up as a
    /// constraint that simply does not hold, which is checked next and reports
    /// better.
    /// </remarks>
    private static void RejectContradictions(IReadOnlyList<SketchConstraintPlan> constraints)
    {
        foreach (var (left, right) in new[]
                 {
                     (ConstraintKind.Horizontal, ConstraintKind.Vertical),
                     (ConstraintKind.Parallel, ConstraintKind.Perpendicular),
                     (ConstraintKind.AlignedHorizontally, ConstraintKind.AlignedVertically)
                 })
        {
            foreach (var first in constraints.Where(item => item.Kind == left))
            foreach (var second in constraints.Where(item => item.Kind == right))
            {
                if (!SameOperands(first, second)) continue;
                throw Invalid("CONSTRAINT_CONTRADICTION",
                    $"Constraints {first.Id} and {second.Id} cannot both hold: " +
                    $"{Describe(first)} and {Describe(second)}.");
            }
        }
    }

    private static bool SameOperands(SketchConstraintPlan left, SketchConstraintPlan right) =>
        left.To is null && right.To is null
            ? left.Of == right.Of
            : left.To is not null && right.To is not null &&
              new[] { left.Of, left.To }.Order(StringComparer.Ordinal)
                  .SequenceEqual(new[] { right.Of, right.To }.Order(StringComparer.Ordinal));

    // --- one constraint ----------------------------------------------------

    private static void Check(SketchConstraintPlan constraint, Dictionary<string, ConstrainedEntity> byId)
    {
        var what = $"Constraint {constraint.Id}";
        var subject = Resolve(constraint.Of, byId, what);
        var partner = constraint.To is null ? null : Resolve(constraint.To, byId, what);
        var axis = constraint.Axis is null ? null : Resolve(constraint.Axis, byId, what);

        var holds = constraint.Kind switch
        {
            // `fixed` says the entity may not be moved by a later edit. That is
            // a statement about editing, not about the coordinates, so there is
            // nothing here it could fail to satisfy.
            ConstraintKind.Fixed => true,
            ConstraintKind.Horizontal => RequireCurve(subject, what).Direction is var (_, dy) &&
                                         Math.Abs(dy) <= Tolerance,
            ConstraintKind.Vertical => RequireCurve(subject, what).Direction is var (dx, _) &&
                                       Math.Abs(dx) <= Tolerance,
            ConstraintKind.Parallel => IsParallel(RequireCurve(subject, what), RequireCurve(partner!, what)),
            ConstraintKind.Perpendicular => IsPerpendicular(
                RequireCurve(subject, what), RequireCurve(partner!, what)),
            ConstraintKind.EqualLength => Math.Abs(subject.Length - partner!.Length) <= Tolerance,
            ConstraintKind.EqualRadius => Math.Abs(
                RequireRadius(subject, what) - RequireRadius(partner!, what)) <= Tolerance,
            ConstraintKind.AlignedHorizontally => Math.Abs(
                subject.PointAt(constraint.OfPoint).Y
                - partner!.PointAt(constraint.ToPoint).Y) <= Tolerance,
            ConstraintKind.AlignedVertically => Math.Abs(
                subject.PointAt(constraint.OfPoint).X
                - partner!.PointAt(constraint.ToPoint).X) <= Tolerance,
            ConstraintKind.Coincident => subject.PointAt(constraint.OfPoint)
                .DistanceTo(partner!.PointAt(constraint.ToPoint)) <= Tolerance,
            ConstraintKind.Midpoint =>
                subject.PointAt(constraint.OfPoint).DistanceTo(partner!.Midpoint) <= Tolerance,
            ConstraintKind.PointOnCurve => IsOn(subject.PointAt(constraint.OfPoint), partner!),
            ConstraintKind.Collinear => IsParallel(RequireCurve(subject, what), RequireCurve(partner!, what)) &&
                                        IsOn(subject.PointAt(constraint.OfPoint), partner!),
            ConstraintKind.Tangent => IsTangent(subject, partner!, what),
            ConstraintKind.Symmetric => IsSymmetric(subject, partner!, RequireCurve(axis!, what)),
            _ => throw Invalid("UNSUPPORTED_CONSTRAINT",
                $"{what} is a {constraint.Kind} constraint, which this build cannot check.")
        };

        if (!holds)
            throw Invalid("CONSTRAINT_NOT_SATISFIED",
                $"{what} states {Describe(constraint)}, and the coordinates the document gives do not. " +
                "A constraint is a statement about the geometry, not an instruction to change it.");
    }

    private static void CheckDimension(
        DrivingDimensionPlan dimension,
        Dictionary<string, ConstrainedEntity> byId)
    {
        var what = $"Dimension {dimension.Id}";
        var subject = Resolve(dimension.Of, byId, what);
        var measured = dimension.Kind switch
        {
            DimensionKind.Length => subject.Length,
            DimensionKind.Radius => RequireRadius(subject, what),
            DimensionKind.Diameter => RequireRadius(subject, what) * 2,
            _ => throw Invalid("UNSUPPORTED_DIMENSION", $"{what} is of a kind this build cannot measure.")
        };
        if (Math.Abs(measured - dimension.Value) > Tolerance)
            throw Invalid("DIMENSION_DISAGREES_WITH_GEOMETRY",
                $"{what} says {Number(dimension.Value)} mm and the geometry measures " +
                $"{Number(measured)} mm. A dimension that disagrees with what it dimensions is a " +
                "document contradicting itself.");
    }

    // --- predicates --------------------------------------------------------

    private static ConstrainedEntity RequireCurve(ConstrainedEntity entity, string what) =>
        entity.IsCurve
            ? entity
            : throw Invalid("CONSTRAINT_OPERAND_INVALID",
                $"{what} needs a line or an arc; {entity.Id} is a {entity.Kind}.");

    private static double RequireRadius(ConstrainedEntity entity, string what) =>
        entity.Radius
        ?? throw Invalid("CONSTRAINT_OPERAND_INVALID",
            $"{what} needs something with a radius; {entity.Id} is a {entity.Kind}.");

    private static bool IsParallel(ConstrainedEntity left, ConstrainedEntity right)
    {
        var (ax, ay) = Unit(left.Direction);
        var (bx, by) = Unit(right.Direction);
        return Math.Abs(ax * by - ay * bx) <= AngleTolerance;
    }

    private static bool IsPerpendicular(ConstrainedEntity left, ConstrainedEntity right)
    {
        var (ax, ay) = Unit(left.Direction);
        var (bx, by) = Unit(right.Direction);
        return Math.Abs(ax * bx + ay * by) <= AngleTolerance;
    }

    private static (double X, double Y) Unit((double X, double Y) vector)
    {
        var length = Math.Sqrt(vector.X * vector.X + vector.Y * vector.Y);
        return length <= Tolerance ? (0, 0) : (vector.X / length, vector.Y / length);
    }

    /// <summary>Is the point on the partner — its line, or its circle?</summary>
    private static bool IsOn(Point2 point, ConstrainedEntity partner)
    {
        if (partner.Kind == "circle" && partner.Center is { } centre && partner.Radius is { } radius)
            return Math.Abs(point.DistanceTo(centre) - radius) <= Tolerance;
        var (dx, dy) = Unit(partner.Direction);
        // Distance from the point to the infinite line through the partner.
        return Math.Abs(dx * (point.Y - partner.Start.Y) - dy * (point.X - partner.Start.X)) <= Tolerance;
    }

    private static bool IsTangent(ConstrainedEntity subject, ConstrainedEntity partner, string what)
    {
        var round = subject.IsRound ? subject : partner;
        var other = subject.IsRound ? partner : subject;
        if (round.Center is not { } centre || round.Radius is not { } radius)
            throw Invalid("CONSTRAINT_OPERAND_INVALID",
                $"{what} needs at least one arc or circle; {subject.Id} and {partner.Id} are both straight.");

        if (other.IsRound && other.Center is { } otherCentre && other.Radius is { } otherRadius)
        {
            var distance = centre.DistanceTo(otherCentre);
            return Math.Abs(distance - (radius + otherRadius)) <= Tolerance ||
                   Math.Abs(distance - Math.Abs(radius - otherRadius)) <= Tolerance;
        }

        var (dx, dy) = Unit(other.Direction);
        var gap = Math.Abs(dx * (centre.Y - other.Start.Y) - dy * (centre.X - other.Start.X));
        return Math.Abs(gap - radius) <= Tolerance;
    }

    /// <summary>Is each operand the other's mirror image across the axis?</summary>
    private static bool IsSymmetric(
        ConstrainedEntity subject,
        ConstrainedEntity partner,
        ConstrainedEntity axis) =>
        Mirror(subject.Start, axis).DistanceTo(partner.Start) <= Tolerance &&
        Mirror(subject.End, axis).DistanceTo(partner.End) <= Tolerance;

    private static Point2 Mirror(Point2 point, ConstrainedEntity axis)
    {
        var (dx, dy) = Unit(axis.Direction);
        var offsetX = point.X - axis.Start.X;
        var offsetY = point.Y - axis.Start.Y;
        // Reflect the offset about the axis direction, then put it back.
        var along = offsetX * dx + offsetY * dy;
        var acrossX = offsetX - 2 * along * dx;
        var acrossY = offsetY - 2 * along * dy;
        return new Point2(axis.Start.X - acrossX, axis.Start.Y - acrossY);
    }

    // --- degrees of freedom ------------------------------------------------

    /// <remarks>
    /// A plain count, not a solver. A line has four degrees of freedom, a circle
    /// three, an arc five; each constraint removes a known number. It is exact
    /// for independent constraints and optimistic for redundant ones, which is
    /// why it is reported rather than enforced — KOMPAS is the authority on
    /// whether its own solver is satisfied.
    /// </remarks>
    private static DegreesOfFreedom Count(
        IReadOnlyList<ConstrainedEntity> entities,
        IReadOnlyList<SketchConstraintPlan> constraints)
    {
        var total = entities.Sum(entity => entity.Kind switch
        {
            "line" => 4,
            "circle" => 3,
            "arc" => 5,
            "point" => 2,
            _ => 0
        });
        var removed = constraints.Sum(constraint => constraint.Kind switch
        {
            ConstraintKind.Fixed => 4,
            ConstraintKind.Horizontal or ConstraintKind.Vertical => 1,
            ConstraintKind.Parallel or ConstraintKind.Perpendicular => 1,
            ConstraintKind.EqualLength or ConstraintKind.EqualRadius => 1,
            ConstraintKind.AlignedHorizontally or ConstraintKind.AlignedVertically => 1,
            ConstraintKind.PointOnCurve => 1,
            ConstraintKind.Tangent => 1,
            ConstraintKind.Coincident or ConstraintKind.Midpoint => 2,
            ConstraintKind.Collinear => 2,
            ConstraintKind.Symmetric => 2,
            _ => 0
        });
        return new DegreesOfFreedom(total, removed);
    }

    /// <summary>
    /// A number for a message, in the invariant culture.
    /// </summary>
    /// <remarks>
    /// A failure message with a locale-formatted number reads differently on
    /// different machines, which makes it useless for matching in a test and
    /// confusing in a log an operator compares with someone else's.
    /// </remarks>
    private static string Number(double value) => value.ToString("F4", CultureInfo.InvariantCulture);

    private static string Describe(SketchConstraintPlan constraint) =>
        constraint.Kind switch
        {
            ConstraintKind.Symmetric =>
                $"{constraint.Of} symmetric to {constraint.To} about {constraint.Axis}",
            _ when constraint.To is null => $"{constraint.Of} {Lower(constraint.Kind)}",
            _ => $"{Point(constraint.Of, constraint.OfPoint, constraint.Kind)} " +
                 $"{Lower(constraint.Kind)} {Point(constraint.To, constraint.ToPoint, constraint.Kind)}"
        };

    /// <summary>Name the point only where a point is what the constraint is about.</summary>
    private static string Point(string? id, SketchPoint which, ConstraintKind kind) =>
        kind is ConstraintKind.Coincident or ConstraintKind.Midpoint
            or ConstraintKind.PointOnCurve or ConstraintKind.AlignedHorizontally
            or ConstraintKind.AlignedVertically
            ? $"{id}.{which.ToString().ToLowerInvariant()}"
            : id ?? "";

    private static string Lower(ConstraintKind kind) =>
        string.Concat(kind.ToString().Select((character, index) =>
            char.IsUpper(character) && index > 0 ? $" {char.ToLowerInvariant(character)}" : $"{char.ToLowerInvariant(character)}"));

    private static CadAdapterException Invalid(string code, string message) =>
        new(code, "sketch", message);
}
