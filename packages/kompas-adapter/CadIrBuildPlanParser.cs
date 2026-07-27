using System.Text.Json;

namespace CadAi.KompasAdapter;

public static class CadIrBuildPlanParser
{
    private const int MaxCadIrBytes = 1_048_576;

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
        if (RequiredString(root, "schema_version", "$") != "0.1.0")
            throw Invalid("UNSUPPORTED_CAD_IR_VERSION", "Only CAD-IR 0.1.0 is supported.");

        var parameters = ReadParameters(Required(root, "parameters", "$"));
        var features = Required(root, "features", "$");
        if (features.ValueKind != JsonValueKind.Array)
            throw Invalid("CAD_IR_INVALID", "$.features must be an array.");

        var enabled = features.EnumerateArray().Where(feature =>
            RequiredBoolean(feature, "enabled", "$.features[]")).ToArray();
        if (enabled.Length is < 1 or > 20)
            throw Invalid("UNSUPPORTED_FEATURE_SET", "Adapter v0 requires one to twenty enabled features.");
        var feature = enabled[0];
        if (RequiredString(feature, "type", "$.features[]") != "extrude_add")
            throw Invalid("UNSUPPORTED_FEATURE_TYPE", "Adapter v0 supports only extrude_add.");

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

    private static CircularCutPlan ParseCircularCut(
        JsonElement feature,
        IReadOnlyDictionary<string, (double Value, string Status)> parameters)
    {
        if (RequiredString(feature, "type", "$.features[]") != "extrude_cut")
            throw Invalid("UNSUPPORTED_FEATURE_TYPE", "Adapter v0 supports extrude_cut after the base feature.");
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
            var status = RequiredString(parameter, "status", "$.parameters[]");
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
        if (value.TryGetProperty("param", out var parameter))
            return ResolveParameter(parameter.GetString(), parameters);
        if (value.TryGetProperty("expr", out var expression))
        {
            var source = expression.GetString() ?? "";
            return new SafeExpression(source, id => ResolveParameter(id, parameters)).Evaluate();
        }
        throw Invalid("CAD_IR_INVALID", "Scalar must be a number, parameter reference or expression.");
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

    private static bool RequiredBoolean(JsonElement owner, string property, string path)
    {
        var value = Required(owner, property, path);
        if (value.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw Invalid("CAD_IR_INVALID", $"{path}.{property} must be a boolean.");
        return value.GetBoolean();
    }

    private static void RequireObject(JsonElement value, string path)
    {
        if (value.ValueKind != JsonValueKind.Object)
            throw Invalid("CAD_IR_INVALID", $"{path} must be an object.");
    }

    private static CadAdapterException Invalid(string code, string message) =>
        new(code, "cad-ir", message);

    private sealed class SafeExpression(string source, Func<string, double> parameter)
    {
        private int position;
        private int depth;

        public double Evaluate()
        {
            if (source.Length is < 1 or > 512)
                throw Invalid("EXPRESSION_INVALID", "CAD expression length is invalid.");
            var result = Sum();
            SkipWhitespace();
            if (position != source.Length || !double.IsFinite(result))
                throw Invalid("EXPRESSION_INVALID", "CAD expression is invalid or non-finite.");
            return result;
        }

        private double Sum()
        {
            var value = Product();
            while (true)
            {
                SkipWhitespace();
                if (Take('+')) value += Product();
                else if (Take('-')) value -= Product();
                else return value;
            }
        }

        private double Product()
        {
            var value = Unary();
            while (true)
            {
                SkipWhitespace();
                if (Take('*')) value *= Unary();
                else if (Take('/'))
                {
                    var divisor = Unary();
                    if (divisor == 0) throw Invalid("EXPRESSION_INVALID", "CAD expression divides by zero.");
                    value /= divisor;
                }
                else return value;
            }
        }

        private double Unary()
        {
            SkipWhitespace();
            if (Take('+')) return Unary();
            if (Take('-')) return -Unary();
            return Primary();
        }

        private double Primary()
        {
            SkipWhitespace();
            if (++depth > 32) throw Invalid("EXPRESSION_INVALID", "CAD expression is too deeply nested.");
            try
            {
                if (Take('('))
                {
                    var value = Sum();
                    SkipWhitespace();
                    if (!Take(')')) throw Invalid("EXPRESSION_INVALID", "CAD expression has unmatched parentheses.");
                    return value;
                }
                if (position < source.Length && (char.IsDigit(source[position]) || source[position] == '.'))
                    return Number();
                var name = Identifier();
                if (name == "pi") return Math.PI;
                SkipWhitespace();
                if (!Take('(')) return parameter(name);
                var arguments = new List<double> { Sum() };
                SkipWhitespace();
                while (Take(','))
                {
                    arguments.Add(Sum());
                    SkipWhitespace();
                }
                if (!Take(')')) throw Invalid("EXPRESSION_INVALID", "CAD function call is not closed.");
                return name switch
                {
                    "abs" when arguments.Count == 1 => Math.Abs(arguments[0]),
                    "min" when arguments.Count >= 1 => arguments.Min(),
                    "max" when arguments.Count >= 1 => arguments.Max(),
                    _ => throw Invalid("EXPRESSION_INVALID", $"Unsupported CAD expression function: {name}.")
                };
            }
            finally { depth--; }
        }

        private double Number()
        {
            var start = position;
            while (position < source.Length &&
                   (char.IsDigit(source[position]) || source[position] is '.' or 'e' or 'E' or '+' or '-'))
            {
                if ((source[position] is '+' or '-') && position > start &&
                    source[position - 1] is not ('e' or 'E')) break;
                position++;
            }
            if (!double.TryParse(
                    source[start..position],
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture,
                    out var value))
                throw Invalid("EXPRESSION_INVALID", "CAD expression contains an invalid number.");
            return value;
        }

        private string Identifier()
        {
            SkipWhitespace();
            var start = position;
            if (position >= source.Length || !(char.IsLetter(source[position]) || source[position] == '_'))
                throw Invalid("EXPRESSION_INVALID", "CAD expression expected a parameter identifier.");
            position++;
            while (position < source.Length &&
                   (char.IsLetterOrDigit(source[position]) || source[position] is '_' or '.' or '-'))
                position++;
            return source[start..position];
        }

        private bool Take(char value)
        {
            if (position >= source.Length || source[position] != value) return false;
            position++;
            return true;
        }

        private void SkipWhitespace()
        {
            while (position < source.Length && char.IsWhiteSpace(source[position])) position++;
        }
    }
}
