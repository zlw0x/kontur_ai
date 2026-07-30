using CadAi.CadEngine;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

/// <summary>
/// Resolves the acceptance selector set against real KOMPAS geometry three
/// times: as built, after the plate is widened and rebuilt, and after the
/// document is reopened in a fresh KOMPAS process.
/// </summary>
/// <remarks>
/// This is the test that cannot be faked. A resolver can look correct on
/// synthetic descriptors and still be wrong about the thing that matters,
/// because the failure it exists to prevent only appears when the kernel
/// renumbers faces — which happens on a rebuild, and again on a reopen.
///
/// It builds its own plate rather than calling the production adapter: the
/// widening step has to keep the base sketch alive to edit it, and handing out
/// live COM handles from the build path so a diagnostic can hold one would be
/// a worse trade than sixty lines of duplication.
/// </remarks>
public static class SelectorStabilityRun
{
    private const string ProgId = "KOMPAS.Application.7";
    private const string Api5ProgId = "KOMPAS.Application.5";

    private const double InitialWidthMm = 40;
    private const double WidenedWidthMm = 60;
    private const double HeightMm = 30;
    private const double ThicknessMm = 8;
    private const double HoleRadiusMm = 2.5;
    private const double HoleOffsetXMm = 13;

    public static Task<SelectorStabilityReport> RunAsync(
        string outputDirectory,
        CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsWindows())
            throw new CadAdapterException("KOMPAS_NOT_INSTALLED", "activation", "KOMPAS requires Windows.");
        var completion = new TaskCompletionSource<SelectorStabilityReport>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            try { completion.SetResult(RunOnSta(outputDirectory, cancellationToken)); }
            catch (OperationCanceledException) { completion.SetCanceled(cancellationToken); }
            catch (Exception error) { completion.SetException(error); }
        })
        {
            IsBackground = true,
            Name = "CadAi.Kompas.Selectors.STA"
        };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        return completion.Task;
    }

    private static SelectorStabilityReport RunOnSta(
        string outputDirectory,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(outputDirectory);
        var m3dPath = Path.Combine(outputDirectory, "selector-stability.m3d");
        if (File.Exists(m3dPath)) File.Delete(m3dPath);
        var catalogue = SelectorCatalogue.AcceptancePlate(HoleRadiusMm, ThicknessMm);
        var phases = new List<SelectorPhase>();

        using (var session = KompasSession.Start())
        {
            cancellationToken.ThrowIfCancellationRequested();
            var document = session.NewPart();
            var sketch = BuildPlate(document, InitialWidthMm);
            try
            {
                // Saved before the first read, not after the last: API5 finds
                // the document through `ActiveDocument3D`, and a part that has
                // never been written to disk is not one it will answer with.
                ((dynamic)document).SaveAs(m3dPath);
                if (!File.Exists(m3dPath) || new FileInfo(m3dPath).Length == 0)
                    throw Failure("SAVE_FAILED", "save", "KOMPAS did not write the stability model.");
                phases.Add(Resolve(session, "initial", catalogue));

                cancellationToken.ThrowIfCancellationRequested();
                Widen(document, sketch, InitialWidthMm, WidenedWidthMm);
                phases.Add(Resolve(session, "widened", catalogue));
                ((dynamic)document).Save();
            }
            finally { Release(sketch); }
        }

        // A second process, so nothing measured above can possibly still be
        // in scope: COM handles, face indexes and the kernel's numbering all
        // died with the first KOMPAS. Only the selectors crossed over.
        cancellationToken.ThrowIfCancellationRequested();
        using (var reopened = KompasSession.Start())
        {
            var document = reopened.Open(m3dPath);
            phases.Add(Resolve(reopened, "reopened", catalogue));

            // Then the case the milestone was written for: a feature added
            // ahead of the ones a selector was written against. Face numbering
            // moves, and nothing that was not about holes may notice.
            cancellationToken.ThrowIfCancellationRequested();
            AddHole(document, 0);
            phases.Add(Resolve(reopened, "third_hole", SelectorCatalogue.WithAThirdHole(catalogue)));
        }

        return new SelectorStabilityReport(
            m3dPath, phases, SelectorStabilityChecks.Evaluate(phases, ThicknessMm));
    }

    private static SelectorPhase Resolve(
        KompasSession session,
        string phase,
        IReadOnlyList<SelectorExpectation> catalogue)
    {
        object? documentObject = null;
        object? partObject = null;
        try
        {
            documentObject = session.ActiveDocument5()
                ?? throw Failure("TOPOLOGY_READ_FAILED", "selectors",
                    $"KOMPAS reported no active 3D document in phase {phase}.");
            partObject = ((IKompasApi5Document3D)documentObject).GetPart(KompasApi5Constants.TopPart)
                ?? throw Failure("TOPOLOGY_READ_FAILED", "selectors", "KOMPAS returned no top part.");

            var readStarted = Stopwatch.GetTimestamp();
            var faces = KompasTopologyReader.ReadFaces(partObject);
            var edges = KompasTopologyReader.ReadEdges(partObject);
            var readMs = (long)Stopwatch.GetElapsedTime(readStarted).TotalMilliseconds;

            var resolveStarted = Stopwatch.GetTimestamp();
            var outcomes = catalogue.Select(expectation => Describe(expectation, faces, edges)).ToList();
            var resolveMs = (long)Stopwatch.GetElapsedTime(resolveStarted).TotalMilliseconds;

            return new SelectorPhase(phase, faces.Count, edges.Count, readMs, resolveMs, outcomes);
        }
        finally
        {
            Release(partObject);
            Release(documentObject);
        }
    }

    private static SelectorOutcome Describe(
        SelectorExpectation expectation,
        IReadOnlyList<FaceDescriptor> faces,
        IReadOnlyList<EdgeDescriptor> edges)
    {
        var selector = expectation.Selector;
        if (selector.Kind == SelectorKind.Face)
        {
            var resolution = SelectorResolver.ResolveFaces(selector, faces);
            var matches = resolution.MatchedIndexes
                .Select(index => faces.First(face => face.Index == index))
                .Select(face => new SelectorMatch(
                    face.Index,
                    face.SurfaceType.ToString().ToLowerInvariant(),
                    Triple(face.Bounds.Min),
                    Triple(face.Bounds.Max),
                    face.Normal is { } normal ? Triple(normal) : null))
                .ToList();
            return new SelectorOutcome(
                selector.Id, expectation.Purpose, expectation.ExpectedErrorCode, resolution, matches);
        }

        var edgeResolution = SelectorResolver.ResolveEdges(selector, edges);
        var edgeMatches = edgeResolution.MatchedIndexes
            .Select(index => edges.First(edge => edge.Index == index))
            .Select(edge => new SelectorMatch(
                edge.Index,
                edge.CurveType.ToString().ToLowerInvariant(),
                Triple(edge.Bounds.Min),
                Triple(edge.Bounds.Max),
                edge.Direction is { } direction ? Triple(direction) : null))
            .ToList();
        return new SelectorOutcome(
            selector.Id, expectation.Purpose, expectation.ExpectedErrorCode, edgeResolution, edgeMatches);
    }

    private static double[] Triple(Vector3 vector) => [vector.X, vector.Y, vector.Z];

    /// <summary>Builds the plate and hands back the base sketch, still live.</summary>
    private static object BuildPlate(object document, double widthMm)
    {
        object? topPartObject = null;
        object? sketchObject = null;
        object? fragmentObject = null;
        object? extrusionObject = null;
        try
        {
            topPartObject = ((IKompasDocument3D)document).TopPart;
            var part = (IPart7)topPartObject;
            sketchObject = ((ISketchs)part.Sketchs).Add();
            var sketch = (ISketch)sketchObject;
            sketch.Plane = part.DefaultObject(1); // o3d_planeXOY=1
            fragmentObject = sketch.BeginEdit();
            var segments = (ILineSegments)Segments(fragmentObject);
            var half = widthMm / 2;
            foreach (var (x1, y1, x2, y2) in Rectangle(half, HeightMm / 2))
            {
                var lineObject = segments.Add();
                try
                {
                    var line = (ILineSegment)lineObject;
                    line.X1 = x1; line.Y1 = y1; line.X2 = x2; line.Y2 = y2;
                    if (!line.Update())
                        throw Failure("SKETCH_INVALID", "sketch", "KOMPAS rejected a rectangle edge.");
                }
                finally { Release(lineObject); }
            }
            if (!sketch.EndEdit())
                throw Failure("SKETCH_INVALID", "sketch", "KOMPAS did not close sketch editing.");

            extrusionObject = ((IExtrusions)part.Extrusions).Add(24); // o3d_baseExtrusion=24
            var extrusion = (IExtrusion)extrusionObject;
            extrusion.Sketch = sketchObject;
            extrusion.Direction = 0; // dtNormal=0
            if (!extrusion.SetSideParameters(true, 0, ThicknessMm, 0, false, null) ||
                !extrusion.Update() ||
                !part.RebuildModel(false))
                throw Failure("FEATURE_BUILD_FAILED", "feature", "KOMPAS did not build the plate.");

            foreach (var centerX in new[] { -HoleOffsetXMm, HoleOffsetXMm })
                Drill(part, centerX);

            var kept = sketchObject;
            sketchObject = null;
            return kept;
        }
        finally
        {
            Release(extrusionObject);
            Release(fragmentObject);
            Release(sketchObject);
            Release(topPartObject);
        }
    }

    private static void AddHole(object document, double centerX)
    {
        object? topPartObject = null;
        try
        {
            topPartObject = ((IKompasDocument3D)document).TopPart;
            Drill((IPart7)topPartObject, centerX);
        }
        finally { Release(topPartObject); }
    }

    private static void Drill(IPart7 part, double centerX)
    {
        object? sketchObject = null;
        object? fragmentObject = null;
        object? extrusionObject = null;
        try
        {
            sketchObject = ((ISketchs)part.Sketchs).Add();
            var sketch = (ISketch)sketchObject;
            sketch.Plane = part.DefaultObject(1);
            fragmentObject = sketch.BeginEdit();
            var view = (IView)ActiveView(fragmentObject);
            var circleObject = ((ICircles)view.Circles).Add();
            try
            {
                var circle = (ICircle)circleObject;
                circle.Xc = centerX;
                circle.Yc = 0;
                circle.Radius = HoleRadiusMm;
                if (!circle.Update())
                    throw Failure("SKETCH_INVALID", "sketch", "KOMPAS rejected a hole contour.");
            }
            finally { Release(circleObject); }
            if (!sketch.EndEdit())
                throw Failure("SKETCH_INVALID", "sketch", "KOMPAS did not close the hole sketch.");

            extrusionObject = ((IExtrusions)part.Extrusions).Add(26); // o3d_cutExtrusion=26
            var extrusion = (IExtrusion)extrusionObject;
            ((IExtrusion1)extrusionObject).OperationResult = 2; // ksOperationCut=2
            extrusion.Sketch = sketchObject;
            extrusion.Direction = 1; // dtReverse=1
            if (!extrusion.SetSideParameters(false, 0, ThicknessMm, 0, false, null) ||
                !extrusion.Update() ||
                !part.RebuildModel(false))
                throw Failure("FEATURE_BUILD_FAILED", "feature", "KOMPAS did not cut a hole.");
        }
        finally
        {
            Release(extrusionObject);
            Release(fragmentObject);
            Release(sketchObject);
        }
    }

    /// <summary>
    /// Edits the base sketch in place so the kernel has to rebuild everything
    /// downstream of it, holes included.
    /// </summary>
    /// <remarks>
    /// Rebuilding the whole document from scratch at the new width would not
    /// test anything: face numbering is stable when the history is identical.
    /// The interesting case is a model that already exists being changed under
    /// a selector that was written against the old one.
    /// </remarks>
    private static void Widen(object document, object sketchObject, double fromWidthMm, double toWidthMm)
    {
        object? topPartObject = null;
        object? fragmentObject = null;
        try
        {
            var sketch = (ISketch)sketchObject;
            fragmentObject = sketch.BeginEdit();
            var segments = (ILineSegments)Segments(fragmentObject);
            var before = fromWidthMm / 2;
            var after = toWidthMm / 2;
            var moved = 0;
            for (var index = 0; index < 64; index++)
            {
                var lineObject = segments.LineSegment(index);
                if (lineObject is null) break;
                try
                {
                    var line = (ILineSegment)lineObject;
                    var x1 = Snap(line.X1, before, after);
                    var x2 = Snap(line.X2, before, after);
                    if (x1 is null && x2 is null) continue;
                    if (x1 is { } newX1) line.X1 = newX1;
                    if (x2 is { } newX2) line.X2 = newX2;
                    if (!line.Update())
                        throw Failure("SKETCH_INVALID", "sketch", "KOMPAS rejected the widened rectangle.");
                    moved++;
                }
                finally { Release(lineObject); }
            }
            if (!sketch.EndEdit())
                throw Failure("SKETCH_INVALID", "sketch", "KOMPAS did not close the widening edit.");
            if (moved == 0)
                throw Failure("SKETCH_INVALID", "sketch", "No rectangle edge sat at the expected width.");

            topPartObject = ((IKompasDocument3D)document).TopPart;
            if (!((IPart7)topPartObject).RebuildModel(false))
                throw Failure("FEATURE_BUILD_FAILED", "rebuild", "KOMPAS did not rebuild the widened plate.");
        }
        finally
        {
            Release(fragmentObject);
            Release(topPartObject);
        }
    }

    private static double? Snap(double value, double before, double after) =>
        Math.Abs(Math.Abs(value) - before) <= 1e-6 ? Math.Sign(value) * after : null;

    private static IEnumerable<(double, double, double, double)> Rectangle(double halfWidth, double halfHeight)
    {
        yield return (-halfWidth, -halfHeight, halfWidth, -halfHeight);
        yield return (halfWidth, -halfHeight, halfWidth, halfHeight);
        yield return (halfWidth, halfHeight, -halfWidth, halfHeight);
        yield return (-halfWidth, halfHeight, -halfWidth, -halfHeight);
    }

    private static object Segments(object fragmentObject) => ((IView)ActiveView(fragmentObject)).LineSegments;

    private static object ActiveView(object fragmentObject)
    {
        var fragment = (IFragmentDocument)fragmentObject;
        var manager = (IViewsAndLayersManager)fragment.ViewsAndLayersManager;
        return ((IViews)manager.Views).ActiveView;
    }

    private static void Release(object? value)
    {
        if (value is not null && Marshal.IsComObject(value))
            Marshal.FinalReleaseComObject(value);
    }

    private static CadAdapterException Failure(string code, string stage, string message) =>
        new(code, stage, message);

    /// <summary>
    /// One KOMPAS process, owned and disposed of. Nothing it produced outlives
    /// it, which is the point of the reopen phase.
    /// </summary>
    private sealed class KompasSession : IDisposable
    {
        private readonly HashSet<int> foreignPids;
        private object? application;
        private object? documents;
        private object? document;
        private object? api5;
        private Process? owned;

        private KompasSession(HashSet<int> foreignPids) => this.foreignPids = foreignPids;

        public static KompasSession Start()
        {
            var foreign = Process.GetProcessesByName("KOMPAS").Select(process => process.Id).ToHashSet();
            var session = new KompasSession(foreign);
            var comType = Type.GetTypeFromProgID(ProgId, throwOnError: false)
                ?? throw Failure("COM_INITIALIZATION_FAILED", "activation", "KOMPAS API7 registration was not found.");
            session.application = Activator.CreateInstance(comType)
                ?? throw Failure("COM_INITIALIZATION_FAILED", "activation", "KOMPAS API7 returned no application object.");
            for (var attempt = 0; attempt < 20 && session.owned is null; attempt++)
            {
                session.owned = Process.GetProcessesByName("KOMPAS")
                    .FirstOrDefault(process => !foreign.Contains(process.Id));
                if (session.owned is null) Thread.Sleep(100);
            }
            dynamic api = session.application;
            api.Visible = false;
            session.documents = api.Documents;
            return session;
        }

        public object NewPart()
        {
            document = ((dynamic)documents!).Add(4, false); // ksDocumentPart=4
            if (document is null || !Marshal.IsComObject(document))
                throw Failure("DOCUMENT_CREATE_FAILED", "document", "KOMPAS did not create a part document.");
            return document;
        }

        public object Open(string path)
        {
            document = ((dynamic)documents!).Open(path, false, false); // visible=false, readOnly=false
            if (document is null || !Marshal.IsComObject(document))
                throw Failure("DOCUMENT_OPEN_FAILED", "document", "KOMPAS did not reopen the saved model.");
            return document;
        }

        /// <summary>
        /// The API5 view of whatever document this session has open.
        /// </summary>
        /// <remarks>
        /// The application object is created once and held for the life of the
        /// session. Creating it per read starts a second KOMPAS process — the
        /// first is busy serving API7 — and the second has no document open, so
        /// `ActiveDocument3D` answers with nothing. Found by a real run: the
        /// first phase read fine and the second could not find the model.
        /// </remarks>
        public object? ActiveDocument5()
        {
            if (api5 is null)
            {
                var api5Type = Type.GetTypeFromProgID(Api5ProgId, throwOnError: false)
                    ?? throw Failure("TOPOLOGY_READ_FAILED", "selectors", "KOMPAS API5 registration was not found.");
                api5 = Activator.CreateInstance(api5Type)
                    ?? throw Failure("TOPOLOGY_READ_FAILED", "selectors", "KOMPAS API5 returned no application object.");
            }
            return ((IKompasApi5Application)api5).ActiveDocument3D();
        }

        public void Dispose()
        {
            Release(api5);
            api5 = null;
            if (document is not null)
            {
                try { ((dynamic)document).Close(0); } catch { }
                Release(document);
                document = null;
            }
            Release(documents);
            documents = null;
            if (application is not null)
            {
                try { ((dynamic)application).Quit(); } catch { }
                Release(application);
                application = null;
            }
            owned ??= Process.GetProcessesByName("KOMPAS")
                .FirstOrDefault(process => !foreignPids.Contains(process.Id));
            if (owned is not null && !owned.HasExited)
            {
                owned.CloseMainWindow();
                if (!owned.WaitForExit(5_000)) owned.Kill(entireProcessTree: true);
            }
            owned?.Dispose();
            owned = null;
        }
    }
}
