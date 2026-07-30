namespace CadAi.CadEngine;

/// <summary>
/// The operations this adapter can build, named one key at a time.
/// </summary>
/// <remarks>
/// One key per thing that can be turned off independently. That is the whole
/// point: when an operation turns out to produce bad parts, the fix has to be
/// smaller than "stop building anything", and it has to be available without a
/// new worker release.
///
/// Granularity follows the failure, not the code. An arc and a slot share every
/// line of the drawing path, but a slot is expanded arithmetic that could be
/// wrong on its own, so it gets its own key.
/// </remarks>
public static class CadCapabilities
{
    public const string SolidRectangularPrism = "solid.rectangular_prism";
    public const string SolidContourProfile = "solid.contour_profile";
    public const string SketchArc = "sketch.arc";
    public const string SketchSlot = "sketch.slot";
    public const string SketchRegularPolygon = "sketch.regular_polygon";
    public const string SketchIslands = "sketch.islands";
    public const string SketchConstruction = "sketch.construction_geometry";
    public const string SketchPlaneBase = "sketch.plane.base";
    public const string SketchPlaneDatum = "sketch.plane.datum_offset";
    public const string SketchPlaneFaceSelector = "sketch.plane.face_selector";
    public const string SketchConstraints = "sketch.constraints";
    public const string SketchDimensions = "sketch.driving_dimensions";
    public const string FeatureHoleSimpleThrough = "feature.hole.simple_through";
    public const string FeatureBossAdditive = "feature.boss.additive";
    public const string ExportM3d = "export.m3d";
    public const string ExportStep = "export.step";
    public const string ExportStl = "export.stl";
    public const string ValidateManifold = "validate.manifold";
    public const string ValidateBoundingBox = "validate.bounding_box";
    public const string ValidateHoleCount = "validate.hole_count";

    /// <summary>
    /// Every key this build knows about, so a flag naming something else can be
    /// rejected rather than silently doing nothing.
    /// </summary>
    /// <remarks>
    /// A typo in a rollback switch is the worst possible time to fail silently:
    /// the operator believes an operation is off and it is still running.
    /// </remarks>
    public static readonly IReadOnlySet<string> All = new HashSet<string>(StringComparer.Ordinal)
    {
        SolidRectangularPrism, SolidContourProfile,
        SketchArc, SketchSlot, SketchRegularPolygon, SketchIslands, SketchConstruction,
        SketchConstraints, SketchDimensions,
        SketchPlaneBase, SketchPlaneDatum, SketchPlaneFaceSelector,
        FeatureHoleSimpleThrough, FeatureBossAdditive,
        ExportM3d, ExportStep, ExportStl,
        ValidateManifold, ValidateBoundingBox, ValidateHoleCount
    };
}

/// <summary>
/// Which operations may be built on this run.
/// </summary>
/// <remarks>
/// Checked in the parser, before any COM object exists, for the same reason
/// everything else is: a disabled operation must cost a typed error rather than
/// a half-built model. And it is checked on the document rather than on the
/// KOMPAS calls, so a plan that would need a disabled operation is refused whole
/// instead of failing partway through.
/// </remarks>
public sealed class CapabilityGate
{
    private readonly IReadOnlySet<string> disabled;

    private CapabilityGate(IReadOnlySet<string> disabled) => this.disabled = disabled;

    /// <summary>The default: nothing is turned off.</summary>
    public static CapabilityGate AllEnabled { get; } =
        new(new HashSet<string>(StringComparer.Ordinal));

    public static CapabilityGate Disabling(IEnumerable<string> capabilities)
    {
        var set = new HashSet<string>(capabilities, StringComparer.Ordinal);
        var unknown = set.Where(key => !CadCapabilities.All.Contains(key)).ToArray();
        if (unknown.Length > 0)
            throw new CadAdapterException(
                "CAPABILITY_UNKNOWN",
                "prepare",
                $"No such capability to disable: {string.Join(", ", unknown.Order())}.");
        return new CapabilityGate(set);
    }

    public bool IsEnabled(string capability) => !disabled.Contains(capability);

    /// <summary>Refuse the document if it needs something that is turned off.</summary>
    public void Require(string capability, string whatNeedsIt)
    {
        if (IsEnabled(capability)) return;
        throw new CadAdapterException(
            "CAPABILITY_DISABLED",
            "cad-ir",
            $"{whatNeedsIt} needs {capability}, which is turned off on this worker.");
    }
}
