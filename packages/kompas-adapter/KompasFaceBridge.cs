using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

/// <summary>
/// Turns a resolved selector into the API7 face object a sketch can sit on.
/// </summary>
/// <remarks>
/// Two APIs have to meet here, and neither offers a handle the other
/// understands. Topology is enumerated through API5 because API7 has no face
/// collection (ADR-019), so a selector resolves to a *measurement* of a face,
/// not a pointer to one. A sketch, meanwhile, needs an API7 object.
///
/// The bridge is a point: `IPart7.FindObjectsByPoint` answers with whatever is
/// at a coordinate, and a point on the face is something the measurement can
/// supply. But "a point derived from a face" is only *probably* on it — a
/// surface's mid-parameter point lies inside a trimmed planar face for the
/// shapes this build makes and not for every shape it will ever make.
///
/// So the answer is verified rather than trusted. The face KOMPAS returns must
/// be planar and its area must match the area the selector measured, or the
/// build stops. Sketching on the wrong face produces a part that looks
/// plausible, and a plausible wrong part is the failure this whole line of work
/// exists to remove.
/// </remarks>
internal static class KompasFaceBridge
{
    /// <summary>
    /// How closely the API7 face's area must match the measurement.
    /// </summary>
    /// <remarks>
    /// A part in ten thousand. The two APIs measure the same face with the same
    /// kernel, so this is floating-point noise rather than a real tolerance;
    /// anything looser would start accepting a different face of similar size.
    /// </remarks>
    private const double AreaAgreement = 1e-4;

    private const int Millimetres = 1; // the unit bit vector; see KompasTopologyReader

    public static object Resolve(KompasApi5Session api5, IPart7 part, GeometrySelector selector)
    {
        var (descriptor, resolution) = Measure(api5, selector);
        var probe = ProbePoint(descriptor);
        var found = part.FindObjectsByPoint(probe.X, probe.Y, probe.Z, firstLevel: true);
        var candidates = found as object[] ?? (found is null ? [] : [found]);

        foreach (var candidate in candidates)
        {
            if (candidate is null) continue;
            IFace face;
            try { face = (IFace)candidate; }
            catch (InvalidCastException) { continue; }
            if (!face.IsPlanar) continue;
            double area;
            try { area = face.GetArea(Millimetres); }
            catch (COMException) { continue; }
            if (descriptor.AreaMm2 is { } measured &&
                Math.Abs(area - measured) > AreaAgreement * Math.Max(measured, 1))
                continue;
            return candidate;
        }

        throw new SelectorException(
            "SELECTOR_FACE_UNVERIFIED",
            $"Selector {selector.Id} measured a face of {descriptor.AreaMm2:F3} mm² at " +
            $"({probe.X:F3}, {probe.Y:F3}, {probe.Z:F3}), but KOMPAS reported " +
            $"{candidates.Length} object(s) there and none of them was that face.",
            resolution);
    }

    private static (FaceDescriptor Face, SelectorResolution Resolution) Measure(
        KompasApi5Session api5,
        GeometrySelector selector)
    {
        var (documentObject, partObject) = api5.TopPart("sketch");
        try
        {
            var faces = KompasTopologyReader.ReadFaces(partObject);
            var resolution = SelectorResolver.ResolveFaces(selector, faces);
            if (!resolution.Satisfied)
                throw new SelectorException(
                    resolution.ErrorCode ?? "SELECTOR_NO_MATCH",
                    $"Selector {selector.Id} did not name one face: {resolution.ResultCount} matched.",
                    resolution);
            var index = resolution.MatchedIndexes[0];
            return (faces.First(face => face.Index == index), resolution);
        }
        finally
        {
            KompasApi7Adapter.Release(partObject);
            KompasApi7Adapter.Release(documentObject);
        }
    }

    /// <summary>
    /// A point to ask KOMPAS about: the centre of the measured face's bounds.
    /// </summary>
    /// <remarks>
    /// Correct for a planar face whose bounds it lies within, which is every
    /// planar face this build produces. It is not correct in general — an
    /// L-shaped face's bounding-box centre is outside it — and that is exactly
    /// why the answer is verified against the measured area instead of being
    /// assumed to be the right face.
    /// </remarks>
    private static (double X, double Y, double Z) ProbePoint(FaceDescriptor face)
    {
        var bounds = face.Bounds;
        return (
            (bounds.Min.X + bounds.Max.X) / 2,
            (bounds.Min.Y + bounds.Max.Y) / 2,
            (bounds.Min.Z + bounds.Max.Z) / 2);
    }
}
