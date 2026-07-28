using System.Text.Json;

namespace CadAi.KompasAdapter;

/// <summary>
/// The last gate before COM: canonical CAD-IR in, a build plan out.
/// </summary>
/// <remarks>
/// Deliberately narrower than the CAD-IR schema. The schema says what version
/// 1.1 can express; this says what this adapter can actually build, which is
/// one rectangular prism and any number of circular through-cuts. Everything
/// else is refused here, while the cost is a typed error rather than a
/// half-built model.
///
/// There is no expression evaluator any more. Version 1.1 has no expression
/// language, so a value is a number or a named parameter — and a parser for
/// untrusted arithmetic that nothing calls is attack surface with no purpose.
/// </remarks>
public static class CadIrBuildPlanParser
{
    private const int MaxCadIrBytes = 1_048_576;
    private const string CadIrSchema = "cad-ai/cad-ir";
    private const string CadIrVersion = "1.1";

    public static async Task<RectangleExtrusionPlan> ParseFileAsync(
        string path,
        CancellationToken cancellationToken = default)
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
            return Parse(document.RootElement);
        }
        catch (JsonException error)
        {
            throw new CadAdapterException("CAD_IR_INVALID", "parse", "CAD-IR is not valid JSON.", error);
        }
    }

    public static RectangleExtrusionPlan Parse(JsonElement root)
    {
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
        if (enabled.Length is < 1 or > 20)
            throw Invalid("UNSUPPORTED_FEATURE_SET", "Adapter v0 requires one to twenty enabled features.");
        var feature = enabled[0];
        if (RequiredString(feature, "type", "$.features[]") != "solid.extrude")
            throw Invalid("UNSUPPORTED_FEATURE_TYPE", "Adapter v0 supports only solid.extrude as the base feature.");

        var inputs = Required(feature, "inputs", "$.features[]");
        RequireObject(inputs, "$.features[].inputs");
        if (RequiredString(inputs, "direction", "$.features[].inputs") != "+Z")
            throw Invalid("UNSUPPORTED_DIRECTION", "Adapter v0 supports only +Z extrusion.");
        var depth = ResolveScalar(Required(inputs, "distance", "$.features[].inputs"), parameters);

        var sketch = Required(inputs, "sketch", "$.features[].inputs");
        if (RequiredString(sketch, "plane", "$.features[].inputs.sketch") != "XY")
            throw Invalid("UNSUPPORTED_PLANE", "Adapter v0 supports only the XY sketch plane.");
        var entities = Required(sketch, "entities", "$.features[].inputs.sketch");
        if (entities.ValueKind != JsonValueKind.Array || entities.GetArrayLength() != 1)
            throw Invalid("UNSUPPORTED_SKETCH", "Adapter v0 requires one center_rectangle entity.");
        var rectangle = entities[0];
        if (RequiredString(rectangle, "type", "$.features[].inputs.sketch.entities[0]") != "center_rectangle")
            throw Invalid("UNSUPPORTED_SKETCH", "Adapter v0 requires a center_rectangle entity.");
        var center = Required(rectangle, "center", "$.features[].inputs.sketch.entities[0]");
        if (center.ValueKind != JsonValueKind.Array || center.GetArrayLength() != 2)
            throw Invalid("CAD_IR_INVALID", "Rectangle center must contain two coordinates.");

        var cuts = enabled.Skip(1).Select(item => ParseCircularCut(item, parameters)).ToArray();
        var plan = new RectangleExtrusionPlan(
            ResolveScalar(center[0], parameters),
            ResolveScalar(center[1], parameters),
            ResolveScalar(Required(rectangle, "width", "$.features[].inputs.sketch.entities[0]"), parameters),
            ResolveScalar(Required(rectangle, "height", "$.features[].inputs.sketch.entities[0]"), parameters),
            depth,
            cuts);
        if (plan.Width <= 0 || plan.Height <= 0 || plan.Depth <= 0 ||
            cuts.Any(cut => cut.Radius <= 0) ||
            new[] { plan.CenterX, plan.CenterY, plan.Width, plan.Height, plan.Depth }
                .Concat(cuts.SelectMany(cut => new[] { cut.CenterX, cut.CenterY, cut.Radius }))
                .Any(value => !double.IsFinite(value) || Math.Abs(value) > 1_000_000))
            throw Invalid("DIMENSION_OUT_OF_RANGE", "Resolved CAD dimensions are outside safe bounds.");
        if (cuts.Any(cut =>
            Math.Abs(cut.CenterX - plan.CenterX) + cut.Radius > plan.Width / 2 ||
            Math.Abs(cut.CenterY - plan.CenterY) + cut.Radius > plan.Height / 2))
            throw Invalid("HOLE_OUTSIDE_BODY", "A circular cut is not contained by the base rectangle.");
        return plan;
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

    private static CircularCutPlan ParseCircularCut(
        JsonElement feature,
        IReadOnlyDictionary<string, (double Value, string Status)> parameters)
    {
        if (RequiredString(feature, "type", "$.features[]") != "cut.extrude")
            throw Invalid("UNSUPPORTED_FEATURE_TYPE", "Adapter v0 supports cut.extrude after the base feature.");
        var inputs = Required(feature, "inputs", "$.features[]");
        if (RequiredString(inputs, "direction", "$.features[].inputs") != "+Z")
            throw Invalid("UNSUPPORTED_DIRECTION", "Circular cuts support only +Z.");
        if (!inputs.TryGetProperty("through_all", out var throughAll) ||
            throughAll.ValueKind != JsonValueKind.True)
            throw Invalid("UNSUPPORTED_CUT_DEPTH", "Circular cuts must use through_all=true.");
        var sketch = Required(inputs, "sketch", "$.features[].inputs");
        if (RequiredString(sketch, "plane", "$.features[].inputs.sketch") != "XY")
            throw Invalid("UNSUPPORTED_PLANE", "Circular cuts support only the XY plane.");
        var entities = Required(sketch, "entities", "$.features[].inputs.sketch");
        if (entities.ValueKind != JsonValueKind.Array || entities.GetArrayLength() != 1)
            throw Invalid("UNSUPPORTED_SKETCH", "Circular cut requires one circle entity.");
        var circle = entities[0];
        if (RequiredString(circle, "type", "$.features[].inputs.sketch.entities[0]") != "circle")
            throw Invalid("UNSUPPORTED_SKETCH", "Circular cut requires one circle entity.");
        var center = Required(circle, "center", "$.features[].inputs.sketch.entities[0]");
        if (center.ValueKind != JsonValueKind.Array || center.GetArrayLength() != 2)
            throw Invalid("CAD_IR_INVALID", "Circle center must contain two coordinates.");
        return new CircularCutPlan(
            ResolveScalar(center[0], parameters),
            ResolveScalar(center[1], parameters),
            ResolveScalar(Required(circle, "radius", "$.features[].inputs.sketch.entities[0]"), parameters));
    }

    private static Dictionary<string, (double Value, string Status)> ReadParameters(JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", "$.parameters must be an array.");
        var result = new Dictionary<string, (double, string)>(StringComparer.Ordinal);
        foreach (var parameter in element.EnumerateArray())
        {
            var id = RequiredString(parameter, "id", "$.parameters[]");
            // `status` is optional in 1.1 and defaults to confirmed; only an
            // explicitly unresolved value blocks a build.
            var status = parameter.TryGetProperty("status", out var declared) &&
                         declared.ValueKind == JsonValueKind.String
                ? declared.GetString()!
                : "confirmed";
            if (RequiredString(parameter, "type", "$.parameters[]") != "length")
                throw Invalid("UNSUPPORTED_PARAMETER_TYPE", $"Adapter v0 supports only length parameters: {id}.");
            var value = Required(parameter, "value", "$.parameters[]");
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetDouble(out var number))
                throw Invalid("CAD_IR_INVALID", $"Parameter {id} has no numeric value.");
            if (!result.TryAdd(id, (number, status)))
                throw Invalid("DUPLICATE_ID", $"Duplicate parameter id: {id}.");
        }
        return result;
    }

    private static double ResolveScalar(
        JsonElement value,
        IReadOnlyDictionary<string, (double Value, string Status)> parameters)
    {
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
            return number;
        RequireObject(value, "scalar");
        if (value.TryGetProperty("parameter", out var parameter))
            return ResolveParameter(parameter.GetString(), parameters);
        throw Invalid("CAD_IR_INVALID", "A scalar must be a number or a parameter reference.");
    }

    private static double ResolveParameter(
        string? id,
        IReadOnlyDictionary<string, (double Value, string Status)> parameters)
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
