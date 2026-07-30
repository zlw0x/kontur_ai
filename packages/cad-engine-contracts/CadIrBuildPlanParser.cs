using System.Text.Json;

// A resolved parameter table: a value and whether it may be used at all.
using Parameters = System.Collections.Generic.IReadOnlyDictionary<string, (double Value, string Status)>;

namespace CadAi.CadEngine;

/// <summary>
/// The last gate before COM: canonical CAD-IR in, a build plan out.
/// </summary>
/// <remarks>
/// Deliberately narrower than the CAD-IR schema. The schema says what the
/// version can express; this says what this adapter can actually build. Everything
/// else is refused here, while the cost is a typed error rather than a
/// half-built model.
///
/// Two jobs beyond reading JSON. Parameters are resolved, so nothing after this
/// point carries a parameter table. And shapes are expanded into contours, so
/// the builder draws lines, arcs and circles and never learns what a slot is.
///
/// There is no expression evaluator. CAD-IR has no expression language, so a
/// value is a number or a named parameter — and a parser for untrusted
/// arithmetic that nothing calls is attack surface with no purpose.
/// </remarks>
public static class CadIrBuildPlanParser
{
    private const int MaxCadIrBytes = 1_048_576;
    private const string CadIrSchema = "cad-ai/cad-ir";
    /// <summary>
    /// The one CAD-IR version this build accepts.
    /// </summary>
    /// <remarks>
    /// Public because an engine has to declare which contract it consumes: a STEP
    /// file is traceable to the document that produced it only if the version of
    /// that document travels with the result.
    /// </remarks>
    public const string CadIrVersion = "1.3";
    private const double MaxCoordinateMm = 1_000_000;

    public static async Task<CadBuildPlan> ParseFileAsync(
        string path,
        CancellationToken cancellationToken = default,
        CapabilityGate? gate = null)
    {
        var info = new FileInfo(path);
        if (!info.Exists)
            throw Invalid("CAD_IR_NOT_FOUND", "CAD-IR file was not found.");
        if (info.Length > MaxCadIrBytes)
            throw Invalid("CAD_IR_TOO_LARGE", "CAD-IR exceeds the local safety limit.");
        await using var stream = File.OpenRead(info.FullName);
        try
        {
            using var document = await JsonDocument.ParseAsync(
                stream,
                new JsonDocumentOptions { MaxDepth = 64, CommentHandling = JsonCommentHandling.Disallow },
                cancellationToken);
            return Parse(document.RootElement, gate);
        }
        catch (JsonException error)
        {
            throw new CadAdapterException("CAD_IR_INVALID", "parse", "CAD-IR is not valid JSON.", error);
        }
    }

    public static CadBuildPlan Parse(JsonElement root, CapabilityGate? gate = null)
    {
        // Defaulting to all-enabled keeps every test and every caller that does
        // not care about flags reading exactly as it did.
        gate ??= CapabilityGate.AllEnabled;
        RequireObject(root, "$");
        RequireSupportedVersion(root);

        var parameters = ReadParameters(Required(root, "parameters", "$"));
        var features = Required(root, "features", "$");
        if (features.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", "$.features must be an array.");

        var enabled = features.EnumerateArray()
            .Where(feature => !feature.TryGetProperty("enabled", out var flag) ||
                              flag.ValueKind != JsonValueKind.False)
            .ToArray();
        if (enabled.Length is < 1 or > 40)
            throw Invalid("UNSUPPORTED_FEATURE_SET", "This adapter builds one to forty enabled features.");

        var planes = new HashSet<string>(StringComparer.Ordinal);
        var plans = new List<CadFeaturePlan>(enabled.Length);
        for (var index = 0; index < enabled.Length; index++)
        {
            var path = $"$.features[{index}]";
            var feature = enabled[index];
            var type = RequiredString(feature, "type", path);
            CadFeaturePlan plan = type switch
            {
                "solid.extrude" => ParseExtrude(feature, path, parameters, planes, gate, isCut: false),
                "cut.extrude" => ParseExtrude(feature, path, parameters, planes, gate, isCut: true),
                "datum.plane.offset" => Gated(gate, CadCapabilities.SketchPlaneDatum,
                    $"the auxiliary plane in {path}",
                    () => ParseDatumPlane(feature, path, parameters, planes)),
                _ => throw Invalid("UNSUPPORTED_FEATURE_TYPE", $"This adapter cannot build {type}.")
            };
            if (plan is DatumPlaneFeaturePlan datum) planes.Add(datum.ResultId);
            plans.Add(plan);
        }

        if (plans.OfType<ExtrudeFeaturePlan>().FirstOrDefault() is not { IsCut: false } profile)
            throw Invalid("UNSUPPORTED_FEATURE_SET", "The first geometric feature must be a base extrusion.");
        if (profile.Sketch.Plane is BasePlanePlan basis)
        {
            var cuts = plans.OfType<ExtrudeFeaturePlan>()
                .Where(feature => feature.IsCut &&
                                  feature.Sketch.Plane is BasePlanePlan other && other.Name == basis.Name);
            foreach (var cut in cuts)
                SketchValidator.RequireCutTouchesProfile(profile.Sketch.Outer, cut.Sketch.Outer, cut.Id);
        }
        return new CadBuildPlan(plans, ReadExpectations(Required(root, "expectations", "$")));
    }

    /// <summary>
    /// Carry the document's expectations through untouched.
    /// </summary>
    /// <remarks>
    /// Not derived from the features on purpose. A build that computed its own
    /// expectations from its own plan would satisfy them by construction, and a
    /// verifier that cannot disagree with the builder is not verifying
    /// anything — the argument in ADR-018.
    /// </remarks>
    private static ExpectedGeometryPlan ReadExpectations(JsonElement expectations)
    {
        if (expectations.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", "$.expectations must be an array.");
        double? x = null, y = null, z = null;
        var tolerance = 0.05;
        int? bodies = null;
        var holes = 0;
        foreach (var expectation in expectations.EnumerateArray())
        {
            var path = "$.expectations[]";
            switch (RequiredString(expectation, "type", path))
            {
                case "bounding_box":
                {
                    var size = Required(expectation, "size_mm", path);
                    x = Number(size, "x", $"{path}.size_mm");
                    y = Number(size, "y", $"{path}.size_mm");
                    z = Number(size, "z", $"{path}.size_mm");
                    tolerance = Number(expectation, "tolerance_mm", path);
                    break;
                }
                case "body_count":
                    bodies = (int)Number(expectation, "value", path);
                    break;
                case "through_hole_count":
                    holes = (int)Number(expectation, "value", path);
                    break;
            }
        }
        if (x is null || y is null || z is null || bodies is null)
            throw Invalid("REQUIRED_EXPECTATION_MISSING",
                "A build needs a bounding_box and a body_count expectation to be checked against.");
        return new ExpectedGeometryPlan(x.Value, y.Value, z.Value, tolerance, bodies.Value, holes);
    }

    private static double Number(JsonElement owner, string property, string path)
    {
        var value = Required(owner, property, path);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var number) ||
            !double.IsFinite(number))
            throw Invalid("CAD_IR_INVALID", $"{path}.{property} must be a finite number.");
        return number;
    }

    /// <summary>Run a parse step only if its capability is enabled.</summary>
    private static T Gated<T>(CapabilityGate gate, string capability, string what, Func<T> parse)
    {
        gate.Require(capability, what);
        return parse();
    }

    private static ExtrudeFeaturePlan ParseExtrude(
        JsonElement feature,
        string path,
        Parameters parameters,
        IReadOnlySet<string> planes,
        CapabilityGate gate,
        bool isCut)
    {
        var id = RequiredString(feature, "id", path);
        var inputs = Required(feature, "inputs", path);
        RequireObject(inputs, $"{path}.inputs");
        if (RequiredString(inputs, "direction", $"{path}.inputs") != "+Z")
            throw Invalid("UNSUPPORTED_DIRECTION", "This adapter extrudes along +Z only.");

        var sketch = ParseSketch(Required(inputs, "sketch", $"{path}.inputs"), $"{path}.inputs.sketch",
            parameters, planes, gate);
        gate.Require(
            isCut ? CadCapabilities.FeatureHoleSimpleThrough : CadCapabilities.SolidRectangularPrism,
            $"the {(isCut ? "cut" : "solid extrusion")} {id}");
        // A cut states through_all or a distance; the depth of a through cut is
        // decided by the adapter from the body it passes through, so a
        // placeholder here would be a number nothing reads.
        var depth = isCut && inputs.TryGetProperty("through_all", out var through) &&
                    through.ValueKind == JsonValueKind.True
            ? 0
            : ResolveScalar(Required(inputs, "distance", $"{path}.inputs"), parameters);
        if (!isCut && !(depth > 0))
            throw Invalid("DIMENSION_OUT_OF_RANGE", "A base extrusion needs a positive distance.");
        RequireInRange(depth, $"{path}.inputs.distance");

        SketchValidator.Validate(sketch);
        return new ExtrudeFeaturePlan(id, sketch, depth, isCut);
    }

    private static DatumPlaneFeaturePlan ParseDatumPlane(
        JsonElement feature,
        string path,
        Parameters parameters,
        IReadOnlySet<string> planes)
    {
        var id = RequiredString(feature, "id", path);
        var produces = Required(feature, "produces", path);
        if (produces.ValueKind != JsonValueKind.Array || produces.GetArrayLength() != 1)
            throw Invalid("CAD_IR_INVALID", $"{path}.produces must name exactly one plane.");
        var resultId = RequiredString(produces[0], "id", $"{path}.produces[0]");

        var inputs = Required(feature, "inputs", path);
        var basis = Required(inputs, "base", $"{path}.inputs");
        string? basePlaneName = null;
        string? baseResultId = null;
        if (basis.ValueKind == JsonValueKind.String)
        {
            basePlaneName = RequireBasePlane(basis.GetString()!);
        }
        else
        {
            baseResultId = RequiredString(basis, "result", $"{path}.inputs.base");
            if (!planes.Contains(baseResultId))
                throw Invalid("FEATURE_RESULT_UNAVAILABLE",
                    $"{path}.inputs.base names {baseResultId}, which no earlier feature produced.");
        }

        var offset = ResolveScalar(Required(inputs, "offset_mm", $"{path}.inputs"), parameters);
        RequireInRange(offset, $"{path}.inputs.offset_mm");
        if (Math.Abs(offset) <= SketchGeometry.PointToleranceMm)
            // A plane offset by nothing is the plane it was offset from, and a
            // sketch on it means something different from what was written.
            throw Invalid("DIMENSION_OUT_OF_RANGE", "An offset plane needs a non-zero offset.");
        var flip = inputs.TryGetProperty("flip", out var flag) && flag.ValueKind == JsonValueKind.True;
        return new DatumPlaneFeaturePlan(id, resultId, basePlaneName, baseResultId, offset, flip);
    }

    // --- sketches ----------------------------------------------------------

    private static SketchPlan ParseSketch(
        JsonElement sketch,
        string path,
        Parameters parameters,
        IReadOnlySet<string> planes,
        CapabilityGate gate)
    {
        RequireObject(sketch, path);
        var id = RequiredString(sketch, "id", path);
        var plane = ParsePlane(Required(sketch, "plane", path), $"{path}.plane", planes, gate);
        var outer = ParseContour(Required(sketch, "outer", path), $"{path}.outer", parameters, gate);
        var inner = ReadArray(sketch, "inner")
            .Select((item, index) => ParseContour(item, $"{path}.inner[{index}]", parameters, gate))
            .ToArray();
        if (inner.Length > 0) gate.Require(CadCapabilities.SketchIslands, $"the islands in {path}");
        var construction = ReadArray(sketch, "construction")
            .Select((item, index) => ParseConstruction(item, $"{path}.construction[{index}]", parameters))
            .ToArray();
        if (construction.Length > 0)
            gate.Require(CadCapabilities.SketchConstruction, $"the construction geometry in {path}");

        var constraints = ReadArray(sketch, "constraints")
            .Select((item, index) => ParseConstraint(item, $"{path}.constraints[{index}]"))
            .ToArray();
        var dimensions = ReadArray(sketch, "dimensions")
            .Select((item, index) => ParseDimension(item, $"{path}.dimensions[{index}]", parameters))
            .ToArray();
        if (constraints.Length > 0)
            gate.Require(CadCapabilities.SketchConstraints, $"the constraints in {path}");
        if (dimensions.Length > 0)
            gate.Require(CadCapabilities.SketchDimensions, $"the driving dimensions in {path}");

        var plan = new SketchPlan(id, plane, outer, inner, construction, constraints, dimensions);
        // Checked here, with the geometry, because a constraint is an assertion
        // about coordinates and this is where the coordinates are numbers.
        ConstraintValidator.Validate(plan.NamedEntities(), constraints, dimensions);
        return plan;
    }

    private static SketchConstraintPlan ParseConstraint(JsonElement constraint, string path)
    {
        RequireObject(constraint, path);
        var kind = RequiredString(constraint, "kind", path) switch
        {
            "horizontal" => ConstraintKind.Horizontal,
            "vertical" => ConstraintKind.Vertical,
            "parallel" => ConstraintKind.Parallel,
            "perpendicular" => ConstraintKind.Perpendicular,
            "tangent" => ConstraintKind.Tangent,
            // One KOMPAS type covers both: a circle's defining point is its
            // centre, so a coincidence between two circles *is* concentricity.
            "concentric" or "coincident" => ConstraintKind.Coincident,
            "midpoint" => ConstraintKind.Midpoint,
            "equal_length" => ConstraintKind.EqualLength,
            "equal_radius" => ConstraintKind.EqualRadius,
            "collinear" => ConstraintKind.Collinear,
            "symmetric" => ConstraintKind.Symmetric,
            "fixed" => ConstraintKind.Fixed,
            "point_on_curve" => ConstraintKind.PointOnCurve,
            "aligned_horizontally" => ConstraintKind.AlignedHorizontally,
            "aligned_vertically" => ConstraintKind.AlignedVertically,
            var other => throw Invalid("UNSUPPORTED_CONSTRAINT",
                $"{path} is a {other} constraint, which this adapter cannot apply.")
        };
        return new SketchConstraintPlan(
            RequiredString(constraint, "id", path),
            kind,
            RequiredString(constraint, "of", path),
            OptionalString(constraint, "to"),
            OptionalString(constraint, "axis"),
            ParsePoint(constraint, "of_point", path),
            ParsePoint(constraint, "to_point", path));
    }

    private static SketchPoint ParsePoint(JsonElement owner, string property, string path) =>
        OptionalString(owner, property) switch
        {
            null or "start" => SketchPoint.Start,
            "end" => SketchPoint.End,
            "center" => SketchPoint.Center,
            var other => throw Invalid("CAD_IR_INVALID", $"{path}.{property} cannot be {other}.")
        };

    private static DrivingDimensionPlan ParseDimension(
        JsonElement dimension,
        string path,
        Parameters parameters)
    {
        RequireObject(dimension, path);
        var kind = RequiredString(dimension, "kind", path) switch
        {
            "length" => DimensionKind.Length,
            "radius" => DimensionKind.Radius,
            "diameter" => DimensionKind.Diameter,
            "angle" => DimensionKind.Angle,
            var other => throw Invalid("UNSUPPORTED_DIMENSION",
                $"{path} is a {other} dimension, which this adapter cannot apply.")
        };
        // An angle's value is in degrees, so it is not passed through the length
        // reader: that one would be free to treat it as a millimetre measurement
        // and no later check would notice the unit was never considered.
        var value = kind == DimensionKind.Angle
            ? Degrees(dimension, "value", path, parameters)
            : Length(dimension, "value", path, parameters);
        return new DrivingDimensionPlan(
            RequiredString(dimension, "id", path),
            kind,
            RequiredString(dimension, "of", path),
            value,
            OptionalString(dimension, "to"));
    }

    private static string? OptionalString(JsonElement owner, string property) =>
        owner.ValueKind == JsonValueKind.Object &&
        owner.TryGetProperty(property, out var value) &&
        value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static SketchPlanePlan ParsePlane(
        JsonElement plane,
        string path,
        IReadOnlySet<string> planes,
        CapabilityGate gate)
    {
        RequireObject(plane, path);
        var on = RequiredString(plane, "on", path);
        switch (on)
        {
            case "base":
                gate.Require(CadCapabilities.SketchPlaneBase, $"the sketch at {path}");
                return new BasePlanePlan(RequireBasePlane(RequiredString(plane, "plane", path)));
            case "datum":
            {
                gate.Require(CadCapabilities.SketchPlaneDatum, $"the sketch at {path}");
                var result = RequiredString(Required(plane, "plane", path), "result", $"{path}.plane");
                if (!planes.Contains(result))
                    throw Invalid("FEATURE_RESULT_UNAVAILABLE",
                        $"{path} sits on {result}, which no earlier feature produced.");
                return new DatumPlanePlan(result);
            }
            case "face":
                gate.Require(CadCapabilities.SketchPlaneFaceSelector, $"the sketch at {path}");
                return new FacePlanePlan(
                    GeometrySelectorParser.Parse(Required(plane, "face", path), $"{path}.face"));
            default:
                throw Invalid("UNSUPPORTED_SKETCH_PLANE", $"A sketch plane cannot sit on a {on}.");
        }
    }

    private static ContourPlan ParseContour(
        JsonElement contour,
        string path,
        Parameters parameters,
        CapabilityGate gate)
    {
        RequireObject(contour, path);
        var type = RequiredString(contour, "type", path);
        var id = OptionalString(contour, "id");
        switch (type)
        {
            case "circle":
                return new CircleContourPlan(
                    Point(Required(contour, "center", path), $"{path}.center", parameters),
                    Length(contour, "radius", path, parameters)) { Id = id };
            case "rectangle":
                return SketchGeometry.Rectangle(
                    Point(Required(contour, "center", path), $"{path}.center", parameters),
                    Length(contour, "width", path, parameters),
                    Length(contour, "height", path, parameters),
                    Optional(contour, "rotation_deg", path, parameters)) with { Id = id };
            case "slot":
                gate.Require(CadCapabilities.SketchSlot, $"the slot at {path}");
                return SketchGeometry.Slot(
                    Point(Required(contour, "start", path), $"{path}.start", parameters),
                    Point(Required(contour, "end", path), $"{path}.end", parameters),
                    Length(contour, "radius", path, parameters)) with { Id = id };
            case "regular_polygon":
            {
                gate.Require(CadCapabilities.SketchRegularPolygon, $"the polygon at {path}");
                var sides = Required(contour, "sides", path);
                if (sides.ValueKind != JsonValueKind.Number || !sides.TryGetInt32(out var count) ||
                    count is < 3 or > 64)
                    throw Invalid("CAD_IR_INVALID", $"{path}.sides must be a whole number from 3 to 64.");
                return SketchGeometry.RegularPolygon(
                    Point(Required(contour, "center", path), $"{path}.center", parameters),
                    count,
                    Length(contour, "circumradius", path, parameters),
                    Optional(contour, "rotation_deg", path, parameters)) with { Id = id };
            }
            case "path":
            {
                gate.Require(CadCapabilities.SolidContourProfile, $"the spelled-out contour at {path}");
                var segments = Required(contour, "segments", path);
                if (segments.ValueKind != JsonValueKind.Array || segments.GetArrayLength() < 2)
                    throw Invalid("CAD_IR_INVALID", $"{path}.segments needs at least two entries.");
                return new PathContourPlan(segments.EnumerateArray()
                    .Select((segment, index) =>
                        ParseSegment(segment, $"{path}.segments[{index}]", parameters, gate))
                    .ToArray()) { Id = id };
            }
            default:
                throw Invalid("UNSUPPORTED_CONTOUR", $"This adapter cannot draw a {type} contour.");
        }
    }

    private static SketchSegment ParseSegment(
        JsonElement segment,
        string path,
        Parameters parameters,
        CapabilityGate? gate = null)
    {
        RequireObject(segment, path);
        var type = RequiredString(segment, "type", path);
        var id = OptionalString(segment, "id");
        var start = Point(Required(segment, "start", path), $"{path}.start", parameters);
        var end = Point(Required(segment, "end", path), $"{path}.end", parameters);
        if (type == "arc")
            (gate ?? CapabilityGate.AllEnabled).Require(CadCapabilities.SketchArc, $"the arc at {path}");
        return type switch
        {
            "line" => new LineSegmentPlan(start, end) { Id = id },
            "arc" => new ArcSegmentPlan(
                start,
                end,
                Point(Required(segment, "center", path), $"{path}.center", parameters),
                RequiredString(segment, "sweep", path) switch
                {
                    "ccw" => true,
                    "cw" => false,
                    var other => throw Invalid("CAD_IR_INVALID", $"{path}.sweep cannot be {other}.")
                }) { Id = id },
            _ => throw Invalid("UNSUPPORTED_SEGMENT", $"This adapter cannot draw a {type} segment.")
        };
    }

    private static ConstructionEntityPlan ParseConstruction(
        JsonElement entity,
        string path,
        Parameters parameters)
    {
        RequireObject(entity, path);
        var id = RequiredString(entity, "id", path);
        var type = RequiredString(entity, "type", path);
        return type switch
        {
            "point" => new ConstructionEntityPlan(
                id, "point", null, Point(Required(entity, "at", path), $"{path}.at", parameters)),
            "line" => new ConstructionEntityPlan(id, "line",
                new PathContourPlan([
                    new LineSegmentPlan(
                        Point(Required(entity, "start", path), $"{path}.start", parameters),
                        Point(Required(entity, "end", path), $"{path}.end", parameters))
                ]), null),
            "circle" => new ConstructionEntityPlan(id, "circle",
                new CircleContourPlan(
                    Point(Required(entity, "center", path), $"{path}.center", parameters),
                    Length(entity, "radius", path, parameters)), null),
            "arc" => new ConstructionEntityPlan(id, "arc",
                new PathContourPlan([ParseSegment(entity, path, parameters)]), null),
            _ => throw Invalid("UNSUPPORTED_CONSTRUCTION",
                $"This adapter cannot draw {type} construction geometry.")
        };
    }

    private static string RequireBasePlane(string name) => name switch
    {
        "XY" or "XZ" or "YZ" => name,
        _ => throw Invalid("UNSUPPORTED_PLANE", $"{name} is not a base plane.")
    };

    // --- scalars -----------------------------------------------------------

    private static Point2 Point(JsonElement value, string path, Parameters parameters)
    {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 2)
            throw Invalid("CAD_IR_INVALID", $"{path} must contain two coordinates.");
        var x = ResolveScalar(value[0], parameters);
        var y = ResolveScalar(value[1], parameters);
        RequireInRange(x, $"{path}[0]");
        RequireInRange(y, $"{path}[1]");
        return new Point2(x, y);
    }

    private static double Length(JsonElement owner, string property, string path, Parameters parameters)
    {
        var value = ResolveScalar(Required(owner, property, path), parameters);
        RequireInRange(value, $"{path}.{property}");
        if (!(value > 0))
            throw Invalid("DIMENSION_OUT_OF_RANGE", $"{path}.{property} must be positive.");
        return value;
    }

    /// <summary>An angle in degrees, which is bounded by geometry rather than by
    /// the coordinate limit a length is checked against.</summary>
    /// <remarks>
    /// Strictly between 0 and 180. Zero is two entities in the same direction,
    /// which is parallelism and has its own constraint; 180 is the same fact with
    /// one of them written backwards. Anything outside is the reflex angle, which
    /// is a different angle from the one the document names.
    /// </remarks>
    private static double Degrees(JsonElement owner, string property, string path, Parameters parameters)
    {
        var value = ResolveScalar(Required(owner, property, path), parameters);
        if (!double.IsFinite(value) || !(value > 0) || !(value < 180))
            throw Invalid("DIMENSION_OUT_OF_RANGE",
                $"{path}.{property} must be an angle above 0 and below 180 degrees.");
        return value;
    }

    private static double Optional(JsonElement owner, string property, string path, Parameters parameters)
    {
        if (!owner.TryGetProperty(property, out var value)) return 0;
        var resolved = ResolveScalar(value, parameters);
        RequireInRange(resolved, $"{path}.{property}");
        return resolved;
    }

    private static void RequireInRange(double value, string path)
    {
        if (!double.IsFinite(value) || Math.Abs(value) > MaxCoordinateMm)
            throw Invalid("DIMENSION_OUT_OF_RANGE", $"{path} is outside safe bounds.");
    }

    private static IEnumerable<JsonElement> ReadArray(JsonElement owner, string property)
    {
        if (!owner.TryGetProperty(property, out var value)) return [];
        if (value.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", $"{property} must be an array.");
        return value.EnumerateArray();
    }

    /// <summary>
    /// Check the version before reading anything else.
    /// </summary>
    /// <remarks>
    /// A document from a future build may use a field this one would silently
    /// ignore, so "too new" is a distinct answer from "invalid": it tells an
    /// operator to upgrade the worker rather than to go hunting for a
    /// malformed document.
    /// </remarks>
    private static void RequireSupportedVersion(JsonElement root)
    {
        if (!root.TryGetProperty("schema_version", out var version) ||
            version.ValueKind != JsonValueKind.String)
            throw Invalid("CAD_IR_VERSION_MISSING", "CAD-IR declares no schema_version.");
        var declared = version.GetString()!;
        if (declared != CadIrVersion)
            throw Invalid(
                IsNewerThanSupported(declared) ? "CAD_IR_VERSION_TOO_NEW" : "CAD_IR_VERSION_UNSUPPORTED",
                $"This worker builds CAD-IR {CadIrVersion}, not {declared}.");
        if (!root.TryGetProperty("schema", out var schema) ||
            schema.ValueKind != JsonValueKind.String ||
            schema.GetString() != CadIrSchema)
            throw Invalid("CAD_IR_VERSION_UNSUPPORTED", $"CAD-IR schema must be {CadIrSchema}.");
    }

    private static bool IsNewerThanSupported(string declared)
    {
        var supported = CadIrVersion.Split('.').Select(int.Parse).ToArray();
        var parts = declared.Split('.');
        var numbers = new int[parts.Length];
        for (var index = 0; index < parts.Length; index++)
            if (!int.TryParse(parts[index], out numbers[index]))
                return false;
        for (var index = 0; index < Math.Max(numbers.Length, supported.Length); index++)
        {
            var left = index < numbers.Length ? numbers[index] : 0;
            var right = index < supported.Length ? supported[index] : 0;
            if (left != right) return left > right;
        }
        return false;
    }

    private static Parameters ReadParameters(JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", "$.parameters must be an array.");
        var result = new Dictionary<string, (double, string)>(StringComparer.Ordinal);
        foreach (var parameter in element.EnumerateArray())
        {
            var id = RequiredString(parameter, "id", "$.parameters[]");
            // `status` is optional and defaults to confirmed; only an explicitly
            // unresolved value blocks a build.
            var status = parameter.TryGetProperty("status", out var declared) &&
                         declared.ValueKind == JsonValueKind.String
                ? declared.GetString()!
                : "confirmed";
            var type = RequiredString(parameter, "type", "$.parameters[]");
            if (type is not ("length" or "angle"))
                throw Invalid("UNSUPPORTED_PARAMETER_TYPE",
                    $"This adapter supports length and angle parameters: {id} is {type}.");
            var value = Required(parameter, "value", "$.parameters[]");
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var number))
                throw Invalid("CAD_IR_INVALID", $"Parameter {id} has no numeric value.");
            if (!result.TryAdd(id, (number, status)))
                throw Invalid("DUPLICATE_ID", $"Duplicate parameter id: {id}.");
        }
        return result;
    }

    private static double ResolveScalar(JsonElement value, Parameters parameters)
    {
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
            return number;
        RequireObject(value, "scalar");
        if (value.TryGetProperty("parameter", out var parameter))
            return ResolveParameter(parameter.GetString(), parameters);
        throw Invalid("CAD_IR_INVALID", "A scalar must be a number or a parameter reference.");
    }

    private static double ResolveParameter(string? id, Parameters parameters)
    {
        if (id is null || !parameters.TryGetValue(id, out var parameter))
            throw Invalid("PARAMETER_NOT_FOUND", $"Unknown parameter: {id ?? "<null>"}.");
        if (parameter.Status == "unresolved")
            throw Invalid("UNRESOLVED_PARAMETER_USED", $"Unresolved parameter is used: {id}.");
        return parameter.Value;
    }

    private static JsonElement Required(JsonElement owner, string property, string path)
    {
        RequireObject(owner, path);
        if (!owner.TryGetProperty(property, out var value))
            throw Invalid("CAD_IR_INVALID", $"{path}.{property} is required.");
        return value;
    }

    private static string RequiredString(JsonElement owner, string property, string path)
    {
        var value = Required(owner, property, path);
        if (value.ValueKind != JsonValueKind.String)
            throw Invalid("CAD_IR_INVALID", $"{path}.{property} must be a string.");
        return value.GetString()!;
    }

    private static void RequireObject(JsonElement value, string path)
    {
        if (value.ValueKind != JsonValueKind.Object)
            throw Invalid("CAD_IR_INVALID", $"{path} must be an object.");
    }

    private static CadAdapterException Invalid(string code, string message) =>
        new(code, "cad-ir", message);
}
