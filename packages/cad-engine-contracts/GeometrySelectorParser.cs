using System.Text.Json;

namespace CadAi.CadEngine;

/// <summary>
/// Reads a CAD-IR selector into the resolver's model.
/// </summary>
/// <remarks>
/// Separate from the resolver on purpose. The resolver works on values and is
/// testable without KOMPAS or JSON; this is the untrusted-input edge, and it
/// refuses anything it does not recognise instead of ignoring it. A predicate
/// silently dropped here would widen a selector — a selector that was meant to
/// name one face would match several, which is precisely the failure the
/// selector layer exists to remove.
/// </remarks>
public static class GeometrySelectorParser
{
    public static GeometrySelector Parse(JsonElement element, string path)
    {
        RequireObject(element, path);
        var id = RequiredString(element, "id", path);
        var kind = RequiredString(element, "kind", path);
        if (kind != "face")
            throw Invalid("SELECTOR_UNSUPPORTED_PREDICATE",
                $"{path} is an {kind} selector; only face selectors are used here.");
        var fromResult = RequiredString(element, "from_result", path);
        var cardinality = ParseCardinality(Required(element, "cardinality", path), $"{path}.cardinality");
        var where = ParseFacePredicates(Required(element, "where", path), $"{path}.where");
        return new GeometrySelector(id, SelectorKind.Face, fromResult, cardinality, Face: where);
    }

    private static Cardinality ParseCardinality(JsonElement element, string path)
    {
        if (element.ValueKind == JsonValueKind.String)
            return element.GetString() switch
            {
                "exactly_one" => new Cardinality(CardinalityKind.ExactlyOne),
                "zero_or_one" => new Cardinality(CardinalityKind.ZeroOrOne),
                "one_or_more" => new Cardinality(CardinalityKind.OneOrMore),
                "all" => new Cardinality(CardinalityKind.All),
                var other => throw Invalid("CAD_IR_INVALID", $"{path} cannot be {other}.")
            };
        RequireObject(element, path);
        if (RequiredString(element, "type", path) != "exactly_n")
            throw Invalid("CAD_IR_INVALID", $"{path} is not a cardinality this build understands.");
        var value = Required(element, "value", path);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out var count) || count < 0)
            throw Invalid("CAD_IR_INVALID", $"{path}.value must be a non-negative whole number.");
        return new Cardinality(CardinalityKind.ExactlyN, count);
    }

    private static FacePredicates ParseFacePredicates(JsonElement element, string path)
    {
        RequireObject(element, path);
        foreach (var property in element.EnumerateObject())
        {
            if (property.Name is "surface_type" or "normal" or "position" or "area_mm2"
                or "radius_mm" or "adjacent" or "produced_by") continue;
            throw Invalid("SELECTOR_UNSUPPORTED_PREDICATE",
                $"{path}.{property.Name} is not a predicate this build resolves.");
        }

        var surfaceType = Optional(element, "surface_type") is { } surface
            ? ParseSurfaceType(surface.GetString(), $"{path}.surface_type")
            : (SurfaceType?)null;
        var normal = Optional(element, "normal") is { } normalElement
            ? ParseNormal(normalElement, $"{path}.normal")
            : null;
        var position = Optional(element, "position") is { } positionElement
            ? ParsePosition(positionElement, $"{path}.position")
            : null;
        var area = ParseMeasurement(Optional(element, "area_mm2"), $"{path}.area_mm2");
        var radius = ParseMeasurement(Optional(element, "radius_mm"), $"{path}.radius_mm");
        var adjacent = Optional(element, "adjacent") is { } adjacentElement
            ? ParseAdjacency(adjacentElement, $"{path}.adjacent")
            : null;

        var predicates = new FacePredicates(surfaceType, normal, position, area, radius, adjacent);
        if (surfaceType is null && normal is null && position is null &&
            area is null && radius is null && adjacent is null)
            // An empty predicate set matches every face on the body.
            throw Invalid("SELECTOR_UNSUPPORTED_PREDICATE", $"{path} states no predicate.");
        return predicates;
    }

    private static NormalPredicate ParseNormal(JsonElement element, string path)
    {
        RequireObject(element, path);
        var parallel = Optional(element, "parallel_to") is { } value
            ? ParseAxis(value.GetString(), $"{path}.parallel_to")
            : (SelectorAxis?)null;
        var perpendicular = Optional(element, "perpendicular_to") is { } other
            ? ParseAxis(other.GetString(), $"{path}.perpendicular_to")
            : (SelectorAxis?)null;
        var direction = Optional(element, "direction") is { } sense
            ? sense.GetString() switch
            {
                "positive" => AxisDirection.Positive,
                "negative" => AxisDirection.Negative,
                var text => throw Invalid("CAD_IR_INVALID", $"{path}.direction cannot be {text}.")
            }
            : (AxisDirection?)null;
        if (parallel is null && perpendicular is null)
            throw Invalid("CAD_IR_INVALID", $"{path} must name an axis.");
        return new NormalPredicate(parallel, perpendicular, direction);
    }

    private static PositionPredicate ParsePosition(JsonElement element, string path)
    {
        RequireObject(element, path);
        var extremeAlong = Optional(element, "extreme_along") is { } axis
            ? ParseAxis(axis.GetString(), $"{path}.extreme_along")
            : (SelectorAxis?)null;
        var extreme = Optional(element, "extreme") is { } kind
            ? kind.GetString() switch
            {
                "minimum" => ExtremeKind.Minimum,
                "maximum" => ExtremeKind.Maximum,
                var text => throw Invalid("CAD_IR_INVALID", $"{path}.extreme cannot be {text}.")
            }
            : (ExtremeKind?)null;
        var centerAlong = Optional(element, "center_along") is { } centreAxis
            ? ParseAxis(centreAxis.GetString(), $"{path}.center_along")
            : (SelectorAxis?)null;
        var centerValue = ParseMeasurement(Optional(element, "center_value_mm"), $"{path}.center_value_mm");
        if ((extremeAlong is null) != (extreme is null))
            throw Invalid("CAD_IR_INVALID", $"{path} states extreme_along and extreme together or not at all.");
        if ((centerAlong is null) != (centerValue is null))
            throw Invalid("CAD_IR_INVALID",
                $"{path} states center_along and center_value_mm together or not at all.");
        if (extremeAlong is null && centerAlong is null)
            throw Invalid("CAD_IR_INVALID", $"{path} must state an extreme or a centre.");
        return new PositionPredicate(extremeAlong, extreme, centerAlong, centerValue);
    }

    private static AdjacencyPredicate ParseAdjacency(JsonElement element, string path)
    {
        RequireObject(element, path);
        var types = Required(element, "contains_surface_types", path);
        if (types.ValueKind != JsonValueKind.Array || types.GetArrayLength() == 0)
            throw Invalid("CAD_IR_INVALID", $"{path}.contains_surface_types must list at least one type.");
        var parsed = types.EnumerateArray()
            .Select((item, index) => ParseSurfaceType(item.GetString(),
                $"{path}.contains_surface_types[{index}]"))
            .ToArray();
        int? faceCount = null;
        if (Optional(element, "face_count") is { } count)
        {
            if (count.ValueKind != JsonValueKind.Number || !count.TryGetInt32(out var value) || value < 1)
                throw Invalid("CAD_IR_INVALID", $"{path}.face_count must be a positive whole number.");
            faceCount = value;
        }
        return new AdjacencyPredicate(parsed, faceCount);
    }

    private static Measurement? ParseMeasurement(JsonElement? element, string path)
    {
        if (element is not { } value) return null;
        RequireObject(value, path);
        var measured = Required(value, "value", path);
        var tolerance = Required(value, "tolerance", path);
        if (measured.ValueKind != JsonValueKind.Number || !measured.TryGetDouble(out var number) ||
            !double.IsFinite(number))
            throw Invalid("CAD_IR_INVALID", $"{path}.value must be a finite number.");
        if (tolerance.ValueKind != JsonValueKind.Number || !tolerance.TryGetDouble(out var band) ||
            !double.IsFinite(band) || band < 0)
            throw Invalid("SELECTOR_INVALID_TOLERANCE", $"{path}.tolerance must be zero or more.");
        return new Measurement(number, band);
    }

    private static SurfaceType ParseSurfaceType(string? value, string path) => value switch
    {
        "planar" => SurfaceType.Planar,
        "cylindrical" => SurfaceType.Cylindrical,
        "conical" => SurfaceType.Conical,
        "spherical" => SurfaceType.Spherical,
        "toroidal" => SurfaceType.Toroidal,
        _ => throw Invalid("SELECTOR_UNSUPPORTED_PREDICATE", $"{path} cannot be {value ?? "null"}.")
    };

    private static SelectorAxis ParseAxis(string? value, string path) => value switch
    {
        "axis.x" => SelectorAxis.X,
        "axis.y" => SelectorAxis.Y,
        "axis.z" => SelectorAxis.Z,
        _ => throw Invalid("CAD_IR_INVALID", $"{path} cannot be {value ?? "null"}.")
    };

    private static JsonElement? Optional(JsonElement owner, string property) =>
        owner.TryGetProperty(property, out var value) && value.ValueKind != JsonValueKind.Null
            ? value
            : null;

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
