using CadAi.CadEngine;
using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

// Interface identifiers and DispIds read from
// "C:\Program Files\ASCON\KOMPAS-3D v22\Bin\kAPI5.tlb" by
// scripts/probe_kompas_topology.py. Nothing here is remembered from
// documentation; see docs/TASK-POSTMVP-005-selectors.md for the mapping from
// each selector predicate to the member that answers it.
//
// Topology lives in API5 because KOMPAS API7's IPart7 exposes no body, face or
// edge collection — only FindBody, GetBodyById and DefaultObject. The adapter
// already uses API5 for STEP and STL export, so no new process is involved.

[ComImport, Guid("508A0CCD-9D74-11D6-95CE-00C0262D30E3"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsPart
{
    [DispId(18)] [return: MarshalAs(UnmanagedType.IDispatch)] object EntityCollection(short objType);
    [DispId(33)] [return: MarshalAs(UnmanagedType.IDispatch)] object BodyCollection();
    [DispId(37)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetMainBody();
}

[ComImport, Guid("03EFC9DD-E05A-4277-BC7C-4FD499A252DE"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsBody
{
    [DispId(1)] bool GetGabarit(out double x1, out double y1, out double z1, out double x2, out double y2, out double z2);
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object FaceCollection();
}

[ComImport, Guid("0E95ACE0-0E73-406F-AE94-E8A0592E298D"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsFaceCollection
{
    [DispId(2)] int GetCount();
    [DispId(7)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetByIndex(int index);
}

[ComImport, Guid("0307BBA8-C193-11D6-8734-00C0262CDD2C"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsFaceDefinition
{
    [DispId(1)] bool IsPlanar();
    [DispId(2)] bool IsCone();
    [DispId(3)] bool IsCylinder();
    [DispId(4)] bool GetCylinderParam(out double h, out double r);
    [DispId(6)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetSurface();
    [DispId(8)] bool normalOrientation();
    [DispId(10)] [return: MarshalAs(UnmanagedType.IDispatch)] object ConnectedFaceCollection();
    [DispId(11)] [return: MarshalAs(UnmanagedType.IDispatch)] object EdgeCollection();
    [DispId(13)] bool IsTorus();
    [DispId(14)] bool IsSphere();
    [DispId(19)] double GetArea(int bitVector);
}

[ComImport, Guid("6096A4FD-970B-468C-815E-37CA1970A203"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsEdgeCollection
{
    [DispId(2)] int GetCount();
    [DispId(7)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetByIndex(int index);
}

[ComImport, Guid("0307BBAB-C193-11D6-8734-00C0262CDD2C"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsEdgeDefinition
{
    [DispId(1)] bool IsStraight();
    [DispId(3)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetCurve3D();
    [DispId(4)] [return: MarshalAs(UnmanagedType.IDispatch)] object GetAdjacentFace(bool facePlus);
    [DispId(8)] bool IsArc();
    [DispId(9)] bool IsCircle();
    [DispId(10)] bool IsEllipse();
    [DispId(11)] bool IsNurbs();
    [DispId(13)] double GetLength(int bitVector);
}

[ComImport, Guid("963CB6E1-B9BF-4234-964A-13BFE6C0282A"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsSurface
{
    [DispId(1)] bool GetGabarit(out double x1, out double y1, out double z1, out double x2, out double y2, out double z2);
    [DispId(3)] bool GetNormal(double paramU, double paramV, out double x, out double y, out double z);
    [DispId(15)] double GetParamUMin();
    [DispId(16)] double GetParamUMax();
    [DispId(17)] double GetParamVMin();
    [DispId(18)] double GetParamVMax();
}

[ComImport, Guid("7572648A-D4EE-41FE-8D74-EC7D1F91BDE2"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKsCurve3D
{
    [DispId(1)] bool GetPoint(double paramT, out double x, out double y, out double z);
    [DispId(2)] bool GetTangentVector(double paramT, out double x, out double y, out double z);
}

/// <summary>
/// Measures the topology of a built model into plain descriptors.
/// </summary>
/// <remarks>
/// The COM half of selector resolution. It reads and releases; it hands back
/// values and keeps no handle, because a COM pointer is not valid across a
/// rebuild, a reopen or a new KOMPAS process. Everything downstream — the
/// matching, the trace, the errors — works on the descriptors alone, which is
/// why that half is testable without KOMPAS installed.
/// </remarks>
public static class KompasTopologyReader
{
    /// <summary>
    /// The unit bit vector `GetLength` and `GetArea` take, set to millimetres.
    /// </summary>
    /// <remarks>
    /// Measured rather than assumed. On a Ø5 rim KOMPAS v22 answers 1.570796,
    /// 15.707963, 0.15708 and 0.015708 for bit vectors 0 to 3, and 2π · 2.5 is
    /// 15.707963 — so 1 is millimetres and 0, the value this reader first
    /// used, is centimetres. Nothing failed loudly: every length came back a
    /// plausible number ten times too small, and the first real run had every
    /// rim selector miss.
    /// </remarks>
    private const int Millimetres = 1;

    public static IReadOnlyList<FaceDescriptor> ReadFaces(object part)
    {
        var body = ((IKsPart)part).GetMainBody()
            ?? throw Failure("TOPOLOGY_NO_BODY", "The part contains no solid body to inspect.");
        var faces = ((IKsBody)body).FaceCollection()
            ?? throw Failure("TOPOLOGY_NO_FACES", "The body exposes no face collection.");
        var collection = (IKsFaceCollection)faces;
        var count = collection.GetCount();
        var descriptors = new List<FaceDescriptor>(count);
        for (var index = 0; index < count; index++)
        {
            var face = collection.GetByIndex(index);
            if (face is null) continue;
            descriptors.Add(Describe((IKsFaceDefinition)face, index));
        }
        return descriptors;
    }

    public static IReadOnlyList<EdgeDescriptor> ReadEdges(object part)
    {
        var body = ((IKsPart)part).GetMainBody()
            ?? throw Failure("TOPOLOGY_NO_BODY", "The part contains no solid body to inspect.");
        var faces = (IKsFaceCollection)((IKsBody)body).FaceCollection();
        var descriptors = new List<EdgeDescriptor>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var faceCount = faces.GetCount();
        for (var faceIndex = 0; faceIndex < faceCount; faceIndex++)
        {
            var face = faces.GetByIndex(faceIndex);
            if (face is null) continue;
            var edges = ((IKsFaceDefinition)face).EdgeCollection();
            if (edges is null) continue;
            var edgeCollection = (IKsEdgeCollection)edges;
            var edgeCount = edgeCollection.GetCount();
            for (var edgeIndex = 0; edgeIndex < edgeCount; edgeIndex++)
            {
                var edge = edgeCollection.GetByIndex(edgeIndex);
                if (edge is null) continue;
                var descriptor = Describe((IKsEdgeDefinition)edge, descriptors.Count);
                // Every edge is shared by two faces, so walking faces visits it
                // twice. Geometry is the only identity available here — there
                // is no stable edge id to deduplicate on.
                var key = EdgeKey(descriptor);
                if (seen.Add(key)) descriptors.Add(descriptor);
            }
        }
        return descriptors;
    }

    private static string EdgeKey(EdgeDescriptor edge) =>
        string.Join(
            '|',
            edge.CurveType,
            Round(edge.LengthMm),
            Round(edge.Bounds.Min.X), Round(edge.Bounds.Min.Y), Round(edge.Bounds.Min.Z),
            Round(edge.Bounds.Max.X), Round(edge.Bounds.Max.Y), Round(edge.Bounds.Max.Z));

    private static string Round(double? value) =>
        value is null ? "-" : Math.Round(value.Value, 6).ToString("F6");

    private static FaceDescriptor Describe(IKsFaceDefinition face, int index)
    {
        var surfaceType = SurfaceTypeOf(face);
        double? radius = null;
        if (surfaceType == SurfaceType.Cylindrical &&
            TryOptional(() => face.GetCylinderParam(out _, out var r) ? r : (double?)null) is { } cylinderRadius)
            radius = cylinderRadius;

        var area = TryValue(() => face.GetArea(Millimetres));
        var surface = Try(() => face.GetSurface());
        var bounds = surface is null ? default : Gabarit((IKsSurface)surface);
        var normal = surfaceType == SurfaceType.Planar && surface is not null
            ? PlanarNormal((IKsSurface)surface, TryValue(() => face.normalOrientation()) ?? true)
            : null;

        var adjacent = new List<SurfaceType>();
        var adjacentCount = 0;
        if (Try(() => face.ConnectedFaceCollection()) is { } connected)
        {
            var collection = (IKsFaceCollection)connected;
            adjacentCount = TryValue(() => collection.GetCount()) ?? 0;
            for (var neighbour = 0; neighbour < adjacentCount; neighbour++)
            {
                var item = Try(() => collection.GetByIndex(neighbour));
                if (item is null) continue;
                adjacent.Add(SurfaceTypeOf((IKsFaceDefinition)item));
            }
        }

        return new FaceDescriptor(
            index, surfaceType, bounds, area, radius, normal,
            adjacent.Distinct().ToArray(), adjacentCount);
    }

    private static EdgeDescriptor Describe(IKsEdgeDefinition edge, int index)
    {
        var curveType = CurveTypeOf(edge);
        var length = TryValue(() => edge.GetLength(Millimetres));
        var curve = Try(() => edge.GetCurve3D());
        var bounds = default(BoundingBox);
        Vector3? direction = null;
        double? radius = null;

        if (curve is not null)
        {
            var curve3D = (IKsCurve3D)curve;
            var start = PointAt(curve3D, 0);
            var end = PointAt(curve3D, 1);
            if (start is { } from && end is { } to)
            {
                bounds = new BoundingBox(
                    new Vector3(Math.Min(from.X, to.X), Math.Min(from.Y, to.Y), Math.Min(from.Z, to.Z)),
                    new Vector3(Math.Max(from.X, to.X), Math.Max(from.Y, to.Y), Math.Max(from.Z, to.Z)));
            }
            if (curveType == CurveType.Line && TryOptional(() =>
                    curve3D.GetTangentVector(0, out var x, out var y, out var z)
                        ? new Vector3(x, y, z)
                        : (Vector3?)null) is { } tangent)
                direction = tangent;
        }

        // A full circle's radius follows from its circumference. KOMPAS
        // exposes no radius on ksEdgeDefinition, and deriving it is exact
        // rather than a guess.
        if (curveType == CurveType.Circle && length is { } circumference && circumference > 0)
            radius = circumference / (2 * Math.PI);

        var adjacent = new List<SurfaceType>();
        foreach (var side in new[] { true, false })
        {
            var neighbour = Try(() => edge.GetAdjacentFace(side));
            if (neighbour is null) continue;
            adjacent.Add(SurfaceTypeOf((IKsFaceDefinition)neighbour));
        }

        return new EdgeDescriptor(
            index, curveType, bounds, length, radius, direction, adjacent.Distinct().ToArray());
    }

    private static Vector3? PointAt(IKsCurve3D curve, double t) =>
        TryOptional(() => curve.GetPoint(t, out var x, out var y, out var z) ? new Vector3(x, y, z) : (Vector3?)null);

    private static BoundingBox Gabarit(IKsSurface surface) =>
        TryOptional(() => surface.GetGabarit(out var x1, out var y1, out var z1, out var x2, out var y2, out var z2)
            ? new BoundingBox(
                new Vector3(Math.Min(x1, x2), Math.Min(y1, y2), Math.Min(z1, z2)),
                new Vector3(Math.Max(x1, x2), Math.Max(y1, y2), Math.Max(z1, z2)))
            : (BoundingBox?)null) ?? default;

    private static Vector3? PlanarNormal(IKsSurface surface, bool orientation)
    {
        // A plane's normal is the same everywhere, so the mid-parameter point
        // is as good as any and avoids the boundary.
        var u = Midpoint(() => surface.GetParamUMin(), () => surface.GetParamUMax());
        var v = Midpoint(() => surface.GetParamVMin(), () => surface.GetParamVMax());
        var normal = TryOptional(() =>
            surface.GetNormal(u, v, out var x, out var y, out var z) ? new Vector3(x, y, z) : (Vector3?)null);
        if (normal is not { } vector) return null;
        // `normalOrientation` is false when the surface normal points into the
        // solid; the outward normal is what a selector means.
        return orientation ? vector : new Vector3(-vector.X, -vector.Y, -vector.Z);
    }

    private static double Midpoint(Func<double> min, Func<double> max)
    {
        var low = TryValue(min) ?? 0;
        var high = TryValue(max) ?? 0;
        return (low + high) / 2;
    }

    private static SurfaceType SurfaceTypeOf(IKsFaceDefinition face)
    {
        if (TryValue(() => face.IsPlanar()) == true) return SurfaceType.Planar;
        if (TryValue(() => face.IsCylinder()) == true) return SurfaceType.Cylindrical;
        if (TryValue(() => face.IsCone()) == true) return SurfaceType.Conical;
        if (TryValue(() => face.IsSphere()) == true) return SurfaceType.Spherical;
        if (TryValue(() => face.IsTorus()) == true) return SurfaceType.Toroidal;
        return SurfaceType.Other;
    }

    private static CurveType CurveTypeOf(IKsEdgeDefinition edge)
    {
        if (TryValue(() => edge.IsStraight()) == true) return CurveType.Line;
        if (TryValue(() => edge.IsCircle()) == true) return CurveType.Circle;
        if (TryValue(() => edge.IsArc()) == true) return CurveType.Arc;
        if (TryValue(() => edge.IsEllipse()) == true) return CurveType.Ellipse;
        if (TryValue(() => edge.IsNurbs()) == true) return CurveType.Spline;
        return CurveType.Other;
    }

    /// <summary>
    /// A member that fails leaves its property unmeasured rather than failing
    /// the read, so one unsupported call cannot make a whole model
    /// unselectable. A predicate over a null property simply does not match.
    /// </summary>
    /// <remarks>
    /// Split by kind because an unconstrained <c>T?</c> is only a nullability
    /// annotation for value types: <c>Try(() => face.IsPlanar())</c> would
    /// return <c>bool</c>, not <c>bool?</c>, and silently report false for a
    /// member that threw.
    /// </remarks>
    private static T? TryValue<T>(Func<T> read) where T : struct
    {
        try { return read(); }
        catch (COMException) { return null; }
        catch (InvalidCastException) { return null; }
    }

    /// <summary>
    /// For a read that already answers "not available" itself, typically an
    /// out-parameter member that returns false.
    /// </summary>
    private static T? TryOptional<T>(Func<T?> read) where T : struct
    {
        try { return read(); }
        catch (COMException) { return null; }
        catch (InvalidCastException) { return null; }
    }

    private static T? Try<T>(Func<T?> read) where T : class
    {
        try { return read(); }
        catch (COMException) { return null; }
        catch (InvalidCastException) { return null; }
    }

    private static CadAdapterException Failure(string code, string message) =>
        new(code, "topology", message);
}
