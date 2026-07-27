using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

public sealed class KompasApi7Adapter : ICadAdapter
{
    private const string ProgId = "KOMPAS.Application.7";
    private const string Api5ProgId = "KOMPAS.Application.5";

    public Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsWindows())
            throw new CadAdapterException("KOMPAS_NOT_INSTALLED", "activation", "KOMPAS requires Windows.");
        var completion = new TaskCompletionSource<CadBuildResult>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            try
            {
                cancellationToken.ThrowIfCancellationRequested();
                completion.SetResult(BuildOnSta(request, cancellationToken));
            }
            catch (OperationCanceledException) { completion.SetCanceled(cancellationToken); }
            catch (Exception error) { completion.SetException(error); }
        })
        {
            IsBackground = true,
            Name = "CadAi.Kompas.STA"
        };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        return completion.Task;
    }

    private static CadBuildResult BuildOnSta(CadBuildRequest request, CancellationToken cancellationToken)
    {
        var output = FakeCadAdapter.SafeOutputDirectory(request.OutputDirectory);
        Directory.CreateDirectory(output);
        var m3dPath = Path.Combine(output, "model.m3d");
        var stepPath = Path.Combine(output, "model.step");
        var stlPath = Path.Combine(output, "model.stl");
        var existingPids = Process.GetProcessesByName("KOMPAS").Select(process => process.Id).ToHashSet();
        object? application = null;
        object? documents = null;
        object? document = null;
        Process? ownedProcess = null;
        var stage = "activation";
        // Each step is timed separately so a slow startup, a slow hole and a
        // slow export are distinguishable in the ledger instead of arriving as
        // one opaque CAD duration.
        var operations = new List<CadOperationRecord>();
        var stepStarted = Stopwatch.GetTimestamp();
        long StepMs()
        {
            var elapsed = (long)Stopwatch.GetElapsedTime(stepStarted).TotalMilliseconds;
            stepStarted = Stopwatch.GetTimestamp();
            return elapsed;
        }
        try
        {
            var comType = Type.GetTypeFromProgID(ProgId, throwOnError: false)
                ?? throw Failure("COM_INITIALIZATION_FAILED", stage, "KOMPAS API7 registration was not found.");
            application = Activator.CreateInstance(comType)
                ?? throw Failure("COM_INITIALIZATION_FAILED", stage, "KOMPAS API7 returned no application object.");
            ownedProcess = WaitForOwnedProcess(existingPids);
            dynamic api = application;
            api.Visible = false;
            documents = api.Documents;
            operations.Add(new CadOperationRecord("kompas_startup", stage, StepMs(), Success: true));

            stage = "document";
            document = ((dynamic)documents).Add(4, false); // ksDocumentPart=4
            if (document is null || !Marshal.IsComObject(document))
                throw Failure("DOCUMENT_CREATE_FAILED", stage, "KOMPAS did not create a part document.");
            operations.Add(new CadOperationRecord("document_create", stage, StepMs(), Success: true));

            cancellationToken.ThrowIfCancellationRequested();
            stage = "sketch";
            BuildRectangleExtrusion(document, request.Plan);
            operations.Add(new CadOperationRecord("rectangular_prism", stage, StepMs(), Success: true));

            var holeNumber = 0;
            foreach (var cut in request.Plan.CircularCuts ?? [])
            {
                cancellationToken.ThrowIfCancellationRequested();
                stage = "feature";
                holeNumber++;
                BuildCircularCut(document, cut, request.Plan.Depth);
                operations.Add(new CadOperationRecord(
                    $"hole_{holeNumber:D3}", stage, StepMs(), Success: true));
            }

            cancellationToken.ThrowIfCancellationRequested();
            stage = "save";
            ((dynamic)document).SaveAs(m3dPath);
            if (!File.Exists(m3dPath) || new FileInfo(m3dPath).Length == 0)
                throw Failure("SAVE_FAILED", stage, "KOMPAS did not create model.m3d.");
            operations.Add(new CadOperationRecord("save_m3d", stage, StepMs(), Success: true));

            stage = "export";
            ExportAdditionalFormats(stepPath, stlPath);
            operations.Add(new CadOperationRecord("export_step_stl", stage, StepMs(), Success: true));

            return new CadBuildResult([
                FakeCadAdapter.CreateArtifact("M3D", m3dPath),
                FakeCadAdapter.CreateArtifact("STEP", stepPath),
                FakeCadAdapter.CreateArtifact("STL", stlPath)
            ], operations);
        }
        catch (CadAdapterException error)
        {
            operations.Add(new CadOperationRecord(error.Code, stage, StepMs(), Success: false, error.Code));
            throw error.WithOperations(operations);
        }
        catch (COMException error)
        {
            operations.Add(new CadOperationRecord(MapCode(stage), stage, StepMs(), Success: false, MapCode(stage)));
            throw Failure(MapCode(stage), stage, $"KOMPAS failed at {stage} (HRESULT 0x{error.HResult:X8}).", error)
                .WithOperations(operations);
        }
        catch (Exception error)
        {
            operations.Add(new CadOperationRecord(MapCode(stage), stage, StepMs(), Success: false, MapCode(stage)));
            throw Failure(MapCode(stage), stage, $"KOMPAS failed at {stage}.", error)
                .WithOperations(operations);
        }
        finally
        {
            if (document is not null)
            {
                try { ((dynamic)document).Close(0); } catch { }
                Release(document);
            }
            Release(documents);
            if (application is not null)
            {
                try { ((dynamic)application).Quit(); } catch { }
                Release(application);
            }
            ownedProcess ??= Process.GetProcessesByName("KOMPAS")
                .FirstOrDefault(process => !existingPids.Contains(process.Id));
            if (ownedProcess is not null && !ownedProcess.HasExited)
            {
                ownedProcess.CloseMainWindow();
                if (!ownedProcess.WaitForExit(5_000))
                    ownedProcess.Kill(entireProcessTree: true);
            }
            ownedProcess?.Dispose();
        }
    }

    private static void BuildCircularCut(object document, CircularCutPlan cut, double baseDepth)
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
            var fragment = (IFragmentDocument)fragmentObject;
            var view = (IView)((IViews)((IViewsAndLayersManager)fragment.ViewsAndLayersManager).Views).ActiveView;
            var circleObject = ((ICircles)view.Circles).Add();
            try
            {
                var circle = (ICircle)circleObject;
                circle.Xc = cut.CenterX;
                circle.Yc = cut.CenterY;
                circle.Radius = cut.Radius;
                if (!circle.Update())
                    throw Failure("SKETCH_INVALID", "sketch", "KOMPAS rejected a circular cut contour.");
            }
            finally { Release(circleObject); }
            if (!sketch.EndEdit())
                throw Failure("SKETCH_INVALID", "sketch", "KOMPAS did not close circular sketch editing.");

            extrusionObject = ((IExtrusions)part.Extrusions).Add(26); // o3d_cutExtrusion=26
            var extrusion = (IExtrusion)extrusionObject;
            ((IExtrusion1)extrusionObject).OperationResult = 2; // ksOperationCut=2
            extrusion.Sketch = sketchObject;
            extrusion.Direction = 1; // dtReverse=1; enters the +Z body from XOY in KOMPAS v22
            if (!extrusion.SetSideParameters(false, 0, baseDepth, 0, false, null) || // exact full body depth
                !extrusion.Update() ||
                !part.RebuildModel(false))
                throw Failure("FEATURE_BUILD_FAILED", "feature", "KOMPAS did not build the circular through cut.");
        }
        finally
        {
            Release(extrusionObject);
            Release(fragmentObject);
            Release(sketchObject);
            Release(topPartObject);
        }
    }

    private static void ExportAdditionalFormats(string stepPath, string stlPath)
    {
        object? api5Object = null;
        object? documentObject = null;
        try
        {
            var api5Type = Type.GetTypeFromProgID(Api5ProgId, throwOnError: false)
                ?? throw Failure("EXPORT_FAILED", "export", "KOMPAS API5 registration was not found.");
            api5Object = Activator.CreateInstance(api5Type)
                ?? throw Failure("EXPORT_FAILED", "export", "KOMPAS API5 returned no application object.");
            documentObject = ((IKompasApi5Application)api5Object).ActiveDocument3D();
            var document = (IKompasApi5Document3D)documentObject;
            Export(document, stepPath, format: 3, binary: false); // format_STEP=3
            Export(document, stlPath, format: 6, binary: true); // format_STL=6
        }
        finally
        {
            Release(documentObject);
            Release(api5Object);
        }
    }

    private static void Export(IKompasApi5Document3D document, string path, short format, bool binary)
    {
        object? parametersObject = null;
        try
        {
            parametersObject = document.AdditionFormatParam();
            var parameters = (IAdditionFormatParam)parametersObject;
            if (!parameters.Init())
                throw Failure("EXPORT_FAILED", "export", "KOMPAS did not initialize export parameters.");
            parameters.Format = format;
            parameters.FormatBinary = binary;
            parameters.StepType = 1; // ksSpaceStep=1
            parameters.Step = 0.05;
            parameters.Angle = 5.0;
            parameters.LengthUnits = 0;
            parameters.MaxTessellationCellCount = 5_000_000;
            if (!document.SaveAsToAdditionFormat(path, parametersObject) ||
                !File.Exists(path) ||
                new FileInfo(path).Length == 0)
                throw Failure("EXPORT_FAILED", "export", $"KOMPAS did not create {Path.GetFileName(path)}.");
        }
        finally { Release(parametersObject); }
    }

    private static void BuildRectangleExtrusion(object document, RectangleExtrusionPlan plan)
    {
        object? topPartObject = null;
        object? sketchObject = null;
        object? fragmentObject = null;
        object? extrusionObject = null;
        try
        {
            topPartObject = ((IKompasDocument3D)document).TopPart;
            var part = (IPart7)topPartObject;
            var sketchCollection = (ISketchs)part.Sketchs;
            sketchObject = sketchCollection.Add();
            var sketch = (ISketch)sketchObject;
            sketch.Plane = part.DefaultObject(1); // o3d_planeXOY=1
            fragmentObject = sketch.BeginEdit();
            var fragment = (IFragmentDocument)fragmentObject;
            var manager = (IViewsAndLayersManager)fragment.ViewsAndLayersManager;
            var views = (IViews)manager.Views;
            var view = (IView)views.ActiveView;
            var lines = (ILineSegments)view.LineSegments;
            var left = plan.CenterX - plan.Width / 2;
            var right = plan.CenterX + plan.Width / 2;
            var bottom = plan.CenterY - plan.Height / 2;
            var top = plan.CenterY + plan.Height / 2;
            foreach (var edge in new[]
            {
                (left, bottom, right, bottom), (right, bottom, right, top),
                (right, top, left, top), (left, top, left, bottom)
            })
            {
                var lineObject = lines.Add();
                try
                {
                    var line = (ILineSegment)lineObject;
                    line.X1 = edge.Item1; line.Y1 = edge.Item2;
                    line.X2 = edge.Item3; line.Y2 = edge.Item4;
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
            if (!extrusion.SetSideParameters(true, 0, plan.Depth, 0, false, null) ||
                !extrusion.Update() ||
                !part.RebuildModel(false))
                throw Failure("FEATURE_BUILD_FAILED", "feature", "KOMPAS did not build the extrusion.");
        }
        finally
        {
            Release(extrusionObject);
            Release(fragmentObject);
            Release(sketchObject);
            Release(topPartObject);
        }
    }

    private static Process? WaitForOwnedProcess(HashSet<int> existingPids)
    {
        for (var attempt = 0; attempt < 20; attempt++)
        {
            var process = Process.GetProcessesByName("KOMPAS")
                .FirstOrDefault(candidate => !existingPids.Contains(candidate.Id));
            if (process is not null) return process;
            Thread.Sleep(100);
        }
        return null;
    }

    private static void Release(object? value)
    {
        if (value is not null && Marshal.IsComObject(value))
            Marshal.FinalReleaseComObject(value);
    }

    private static string MapCode(string stage) => stage switch
    {
        "activation" => "COM_INITIALIZATION_FAILED",
        "document" => "DOCUMENT_CREATE_FAILED",
        "sketch" => "SKETCH_INVALID",
        "feature" => "FEATURE_BUILD_FAILED",
        "save" => "SAVE_FAILED",
        "export" => "EXPORT_FAILED",
        _ => "KOMPAS_OPERATION_FAILED"
    };

    private static CadAdapterException Failure(string code, string stage, string message, Exception? inner = null) =>
        new(code, stage, message, inner);
}
