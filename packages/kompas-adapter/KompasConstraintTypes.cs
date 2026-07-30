using CadAi.CadEngine;

namespace CadAi.KompasAdapter;

/// <summary>
/// The KOMPAS integers behind the neutral constraint vocabulary.
/// </summary>
/// <remarks>
/// Split out of the vocabulary itself when the engine became replaceable
/// (ADR-023). A document states that two edges are parallel; that KOMPAS spells
/// parallel as 5, that an arc numbers its centre 0 while a segment numbers its
/// start 0, and that an angle dimension is type 10 and not type 39, are all facts
/// about one engine and belong next to the COM call that uses them.
///
/// None of these were read. The KOMPAS type libraries export no enumerations at
/// all, so every number here was identified by building geometry and measuring
/// what moved - see `scripts/probe_kompas_constraints.py`,
/// `scripts/probe_kompas_points.py`, `scripts/probe_kompas_driving.py` and
/// docs/TASK-POSTMVP-007-sketch-constraints.md.
/// </remarks>

public static class KompasConstraintTypes
{
    /// <summary>Measured on KOMPAS v22; every one confirmed by what it moved.</summary>
    public static int Of(ConstraintKind kind) => kind switch
    {
        ConstraintKind.Fixed => 1,
        ConstraintKind.PointOnCurve => 2,
        ConstraintKind.Horizontal => 3,
        ConstraintKind.Vertical => 4,
        ConstraintKind.Parallel => 5,
        ConstraintKind.Perpendicular => 6,
        ConstraintKind.EqualLength => 7,
        ConstraintKind.EqualRadius => 8,
        ConstraintKind.AlignedHorizontally => 9,
        ConstraintKind.AlignedVertically => 10,
        ConstraintKind.Coincident => 11,
        ConstraintKind.Tangent => 15,
        ConstraintKind.Symmetric => 16,
        ConstraintKind.Collinear => 17,
        ConstraintKind.Midpoint => 20,
        _ => throw new CadAdapterException(
            "UNSUPPORTED_CONSTRAINT", "sketch", $"No KOMPAS constraint type is known for {kind}.")
    };

    /// <summary>
    /// The one constraint type that binds a dimension to a named variable.
    /// </summary>
    /// <remarks>
    /// Measured: on an associated linear, radial or diametral dimension, type 13
    /// creates a variable whose `Value` reads back as the measurement KOMPAS
    /// took. Type 14 creates but yields no variable, and every other type fails
    /// on a dimension outright.
    /// </remarks>
    public const int DrivingDimension = 13;

    /// <summary>
    /// The one that makes a named dimension actually drive its geometry.
    /// </summary>
    /// <remarks>
    /// Measured by `scripts/probe_kompas_driving.py`. Type 13 alone names a
    /// variable that *reports* the measurement: setting it changes nothing, and a
    /// rebuild puts the old number back, because the model computes it from the
    /// geometry. Adding **14** on the same dimension turns it round — a 16 mm
    /// segment whose variable is set to 50 comes back 50 mm long.
    ///
    /// Both constraints go on the same associated dimension object. That is the
    /// link POSTMVP-007 could not find, and why it shipped dimensions that
    /// annotate rather than drive.
    /// </remarks>
    public const int FixedDimension = 14;
}

/// <summary>
/// Which KOMPAS angle-dimension type to draw.
/// </summary>
/// <remarks>
/// `IAngleDimensions.Add` takes a type and answers nothing for almost every
/// value. Swept from -2 to 64: only **10** and **39** create.
///
/// 10 is the one to use. Its variable is the angle between the two objects it
/// names, so driving it to 55 leaves the two segments 55 degrees apart.
///
/// **39 measures something else.** Driven to 55 it leaves the segments 27.5
/// degrees apart — exactly half — so it is an angle taken against a bisector
/// rather than between the two arms. Using it would put a dimension in the
/// delivered file whose number is twice what the drawing said.
/// </remarks>
internal static class KompasAngleDimensionTypes
{
    public const int BetweenTwoObjects = 10;
}

/// <summary>
/// Which number selects which point of an entity on a KOMPAS constraint.
/// </summary>
/// <remarks>
/// Measured by `scripts/probe_kompas_points.py` on KOMPAS v22: a coincidence was
/// applied between two entities whose every named point is far from every other,
/// and the pair that met named the index.
///
/// | entity  | 0      | 1     | 2        |
/// |---------|--------|-------|----------|
/// | segment | start  | end   | midpoint |
/// | arc     | centre | start | end      |
/// | circle  | centre | —     | —        |
///
/// Values 3, 4 and -1 create nothing at all, on every entity.
///
/// **The arc is the trap.** Its table is not the segment's: index 0 is the
/// centre, not the start. A single table for everything would have applied
/// `concentric` between two arcs as a coincidence of their *start points* — a
/// constraint the document never stated, in a file a customer opens, with the
/// geometry still looking right because the solver had nothing to correct.
/// </remarks>
public static class KompasPointIndex
{
    public static int Of(string kind, SketchPoint point) => kind switch
    {
        // A circle offers exactly one point, so every name of it is the centre.
        // That is also why `coincident` between two circles reads as concentric.
        "circle" => 0,
        "arc" => point switch
        {
            SketchPoint.Center => 0,
            SketchPoint.Start => 1,
            SketchPoint.End => 2,
            _ => 0
        },
        _ => point switch
        {
            SketchPoint.Start => 0,
            SketchPoint.End => 1,
            SketchPoint.Center => throw new CadAdapterException(
                "CONSTRAINT_OPERAND_INVALID", "sketch",
                $"A {kind} has no centre for a point constraint to name."),
            _ => 0
        }
    };
}

/// <summary>
/// Which of a constraint's two index properties KOMPAS actually reads.
/// </summary>
/// <remarks>
/// Measured with the same probe, by sweeping both indices for each type and
/// watching which sweeps changed the answer:
///
/// * **11 coincident**, **9 aligned horizontally**, **10 aligned vertically** —
///   both indices are read. 9 and 10 equate one coordinate of the two named
///   points rather than the points themselves.
/// * **20 midpoint**, **2 point on curve** — only the subject's index is read.
///   The partner contributes a whole entity by definition: its midpoint in one
///   case, its curve in the other.
/// * **17 collinear** — neither is read. It is a relation between two entities,
///   and every index pair produced the identical result, including -1.
///
/// Setting an index a type ignores is harmless, but naming which are real is
/// what keeps the next reader from inventing a meaning for a number that has
/// none.
/// </remarks>
public static class KompasConstraintOperands
{
    public static bool UsesSubjectPoint(ConstraintKind kind) => kind is
        ConstraintKind.Coincident or
        ConstraintKind.Midpoint or
        ConstraintKind.PointOnCurve or
        ConstraintKind.AlignedHorizontally or
        ConstraintKind.AlignedVertically;

    public static bool UsesPartnerPoint(ConstraintKind kind) => kind is
        ConstraintKind.Coincident or
        ConstraintKind.AlignedHorizontally or
        ConstraintKind.AlignedVertically;
}
