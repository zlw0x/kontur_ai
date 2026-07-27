using System.Buffers.Binary;
using System.Globalization;

namespace CadAi.GeometryValidation;

public sealed record ExpectedGeometry(
    double Width,
    double Height,
    double Depth,
    int SolidBodyCount,
    int ThroughHoleCount,
    double Tolerance = 0.05);

public sealed record GeometryMetrics(
    uint TriangleCount,
    int VertexCount,
    int EdgeCount,
    int MeshComponentCount,
    int BoundaryOrNonManifoldEdgeCount,
    int DegenerateTriangleCount,
    double[] BoundingBox,
    int? Genus);

public sealed record ValidationCheck(string Name, bool Passed, string Detail);

public sealed record GeometryValidationResult(
    bool Valid,
    IReadOnlyList<ValidationCheck> Checks,
    GeometryMetrics Mesh);

public static class GeometryValidator
{
    public static GeometryValidationResult Validate(
        string m3dPath,
        string stepPath,
        string stlPath,
        ExpectedGeometry expected)
    {
        var checks = new List<ValidationCheck>();
        CheckNonEmpty(m3dPath, "m3d_nonempty", checks);
        CheckStep(stepPath, checks);
        var mesh = ReadBinaryStl(stlPath);
        checks.Add(new("stl_structure", mesh.TriangleCount > 0,
            $"{mesh.TriangleCount} complete triangles parsed."));
        checks.Add(new("finite_non_degenerate_triangles", mesh.DegenerateTriangleCount == 0,
            $"{mesh.DegenerateTriangleCount} degenerate or non-finite triangles."));
        checks.Add(new("closed_manifold_mesh", mesh.BoundaryOrNonManifoldEdgeCount == 0,
            $"{mesh.BoundaryOrNonManifoldEdgeCount} edges do not have exactly two incident triangles."));
        checks.Add(new("solid_body_count", mesh.MeshComponentCount == expected.SolidBodyCount,
            $"expected {expected.SolidBodyCount}, measured {mesh.MeshComponentCount}."));
        checks.Add(new("bounding_box", MatchesBounds(mesh.BoundingBox, expected),
            $"expected [{expected.Width}, {expected.Height}, {expected.Depth}], measured [{string.Join(", ", mesh.BoundingBox.Select(value => value.ToString("G8")))}]."));
        checks.Add(new("through_hole_count", mesh.Genus == expected.ThroughHoleCount,
            $"expected {expected.ThroughHoleCount}, topology-derived genus {mesh.Genus?.ToString() ?? "unavailable"}."));
        return new GeometryValidationResult(checks.All(check => check.Passed), checks, mesh);
    }

    private static void CheckNonEmpty(string path, string name, ICollection<ValidationCheck> checks)
    {
        var size = File.Exists(path) ? new FileInfo(path).Length : 0;
        checks.Add(new(name, size > 0, $"{size} bytes."));
    }

    private static void CheckStep(string path, ICollection<ValidationCheck> checks)
    {
        var valid = false;
        if (File.Exists(path) && new FileInfo(path).Length > 0)
        {
            using var reader = new StreamReader(path);
            valid = string.Equals(reader.ReadLine()?.Trim(), "ISO-10303-21;", StringComparison.Ordinal);
        }
        checks.Add(new("step_header", valid, valid ? "ISO-10303-21 header found." : "STEP header is missing."));
    }

    private static GeometryMetrics ReadBinaryStl(string path)
    {
        if (!File.Exists(path))
            throw new InvalidDataException("STL artifact is missing.");
        var bytes = File.ReadAllBytes(path);
        if (bytes.AsSpan(0, Math.Min(bytes.Length, 5)).SequenceEqual("solid"u8))
            return AnalyzeTriangles(ReadAsciiTriangles(path));
        if (bytes.Length < 84)
            throw new InvalidDataException("STL is shorter than the binary header.");
        var triangleCount = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(80, 4));
        var expectedLength = checked(84L + 50L * triangleCount);
        if (bytes.LongLength != expectedLength)
            throw new InvalidDataException("STL byte length does not match its triangle count.");

        var triangles = new List<double[][]>(checked((int)triangleCount));
        for (var triangleIndex = 0; triangleIndex < triangleCount; triangleIndex++)
        {
            var offset = checked(84 + (int)triangleIndex * 50);
            var points = new double[3][];
            for (var vertexIndex = 0; vertexIndex < 3; vertexIndex++)
            {
                var vertexOffset = offset + 12 + vertexIndex * 12;
                points[vertexIndex] =
                [
                    ReadFloat(bytes, vertexOffset),
                    ReadFloat(bytes, vertexOffset + 4),
                    ReadFloat(bytes, vertexOffset + 8)
                ];
            }
            triangles.Add(points);
        }
        return AnalyzeTriangles(triangles);
    }

    private static List<double[][]> ReadAsciiTriangles(string path)
    {
        var vertices = new List<double[]>();
        foreach (var line in File.ReadLines(path))
        {
            var trimmed = line.Trim();
            if (!trimmed.StartsWith("vertex ", StringComparison.OrdinalIgnoreCase)) continue;
            var components = trimmed.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (components.Length != 4 ||
                !double.TryParse(components[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var x) ||
                !double.TryParse(components[2], NumberStyles.Float, CultureInfo.InvariantCulture, out var y) ||
                !double.TryParse(components[3], NumberStyles.Float, CultureInfo.InvariantCulture, out var z))
                throw new InvalidDataException("ASCII STL contains an invalid vertex.");
            vertices.Add([x, y, z]);
        }
        if (vertices.Count == 0 || vertices.Count % 3 != 0)
            throw new InvalidDataException("ASCII STL does not contain complete triangles.");
        return vertices.Chunk(3).Select(chunk => chunk.ToArray()).ToList();
    }

    private static GeometryMetrics AnalyzeTriangles(IReadOnlyList<double[][]> triangles)
    {
        var vertices = new Dictionary<VertexKey, int>();
        var edges = new Dictionary<EdgeKey, List<int>>();
        var degenerate = 0;
        var min = new[] { double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity };
        var max = new[] { double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity };
        for (var triangleIndex = 0; triangleIndex < triangles.Count; triangleIndex++)
        {
            var ids = new int[3];
            var points = triangles[triangleIndex];
            var finite = true;
            for (var vertexIndex = 0; vertexIndex < 3; vertexIndex++)
            {
                finite &= points[vertexIndex].All(double.IsFinite);
                if (!finite) continue;
                for (var axis = 0; axis < 3; axis++)
                {
                    min[axis] = Math.Min(min[axis], points[vertexIndex][axis]);
                    max[axis] = Math.Max(max[axis], points[vertexIndex][axis]);
                }
                var key = VertexKey.From(points[vertexIndex]);
                if (!vertices.TryGetValue(key, out ids[vertexIndex]))
                {
                    ids[vertexIndex] = vertices.Count;
                    vertices.Add(key, ids[vertexIndex]);
                }
            }
            if (!finite || ids.Distinct().Count() != 3 || TwiceArea(points[0], points[1], points[2]) < 1e-10)
                degenerate++;
            foreach (var edge in new[]
            {
                EdgeKey.Create(ids[0], ids[1]),
                EdgeKey.Create(ids[1], ids[2]),
                EdgeKey.Create(ids[2], ids[0])
            })
            {
                if (!edges.TryGetValue(edge, out var incidents))
                {
                    incidents = [];
                    edges.Add(edge, incidents);
                }
                incidents.Add(triangleIndex);
            }
        }

        var components = CountComponents(triangles.Count, edges.Values);
        var badEdges = edges.Values.Count(incidents => incidents.Count != 2);
        int? genus = null;
        if (components == 1 && badEdges == 0)
        {
            var numerator = 2 - (vertices.Count - edges.Count + triangles.Count);
            if (numerator >= 0 && numerator % 2 == 0) genus = numerator / 2;
        }
        return new(
            checked((uint)triangles.Count), vertices.Count, edges.Count, components, badEdges, degenerate,
            [max[0] - min[0], max[1] - min[1], max[2] - min[2]], genus);
    }

    private static int CountComponents(int triangleCount, IEnumerable<List<int>> incidentLists)
    {
        if (triangleCount == 0) return 0;
        var adjacency = Enumerable.Range(0, triangleCount).Select(_ => new List<int>()).ToArray();
        foreach (var incidents in incidentLists.Where(list => list.Count > 1))
        {
            for (var index = 1; index < incidents.Count; index++)
            {
                adjacency[incidents[0]].Add(incidents[index]);
                adjacency[incidents[index]].Add(incidents[0]);
            }
        }
        var visited = new bool[triangleCount];
        var count = 0;
        for (var start = 0; start < triangleCount; start++)
        {
            if (visited[start]) continue;
            count++;
            var pending = new Stack<int>();
            pending.Push(start);
            while (pending.TryPop(out var current))
            {
                if (visited[current]) continue;
                visited[current] = true;
                foreach (var neighbor in adjacency[current])
                    if (!visited[neighbor]) pending.Push(neighbor);
            }
        }
        return count;
    }

    private static bool MatchesBounds(IReadOnlyList<double> actual, ExpectedGeometry expected)
    {
        var wanted = new[] { expected.Width, expected.Height, expected.Depth };
        return actual.Select((value, index) => Math.Abs(value - wanted[index]) <= expected.Tolerance).All(value => value);
    }

    private static float ReadFloat(byte[] bytes, int offset) =>
        BitConverter.Int32BitsToSingle(BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(offset, 4)));

    private static double TwiceArea(double[] a, double[] b, double[] c)
    {
        var ab = new[] { b[0] - a[0], b[1] - a[1], b[2] - a[2] };
        var ac = new[] { c[0] - a[0], c[1] - a[1], c[2] - a[2] };
        var x = ab[1] * ac[2] - ab[2] * ac[1];
        var y = ab[2] * ac[0] - ab[0] * ac[2];
        var z = ab[0] * ac[1] - ab[1] * ac[0];
        return Math.Sqrt(x * x + y * y + z * z);
    }

    private readonly record struct VertexKey(long X, long Y, long Z)
    {
        private const double Scale = 100_000;
        public static VertexKey From(IReadOnlyList<double> point) =>
            new(
                checked((long)Math.Round(point[0] * Scale)),
                checked((long)Math.Round(point[1] * Scale)),
                checked((long)Math.Round(point[2] * Scale)));
    }

    private readonly record struct EdgeKey(int A, int B)
    {
        public static EdgeKey Create(int first, int second) =>
            first <= second ? new(first, second) : new(second, first);
    }
}
