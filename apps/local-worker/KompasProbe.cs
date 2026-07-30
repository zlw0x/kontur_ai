using CadAi.CadEngine;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace CadAi.LocalWorker;

public static class KompasProbe
{
    private const string ProgId = "KOMPAS.Application.7";
    private const string ExpectedExecutable = @"C:\Program Files\ASCON\KOMPAS-3D v22\Bin\KOMPAS.exe";

    public static async Task<int> RunAsync()
    {
        if (!OperatingSystem.IsWindows())
            throw new WorkerException("KOMPAS_NOT_INSTALLED", "KOMPAS probe requires Windows.");
        if (!File.Exists(ExpectedExecutable))
            throw new WorkerException("KOMPAS_NOT_INSTALLED", "KOMPAS executable was not found.");

        var existing = Process.GetProcessesByName("KOMPAS").Select(process => process.Id).ToHashSet();
        object? application = null;
        object? documents = null;
        object? document = null;
        Process? ownedProcess = null;
        var outputPath = Path.Combine(Path.GetTempPath(), $"cad-ai-kompas-probe-{Guid.NewGuid():N}.m3d");
        var stage = "activation";
        try
        {
            var comType = Type.GetTypeFromProgID(ProgId, throwOnError: false)
                ?? throw new WorkerException("COM_INITIALIZATION_FAILED", "KOMPAS API7 COM registration was not found.");
            application = Activator.CreateInstance(comType)
                ?? throw new WorkerException("COM_INITIALIZATION_FAILED", "KOMPAS API7 COM activation returned no object.");
            if (!Marshal.IsComObject(application))
                throw new WorkerException("COM_INITIALIZATION_FAILED", "KOMPAS activation did not return a COM object.");
            await Task.Delay(1000);
            ownedProcess = Process.GetProcessesByName("KOMPAS").FirstOrDefault(process => !existing.Contains(process.Id));

            dynamic api = application;
            api.Visible = false;
            documents = api.Documents;
            dynamic docs = documents;
            document = docs.Add(4, false); // kAPI7.tlb: ksDocumentPart = 4
            if (document is null || !Marshal.IsComObject(document))
                throw new WorkerException("DOCUMENT_CREATE_FAILED", "KOMPAS did not create a 3D part document.");
            stage = "document3d-query";
            var document3D = (IKompasDocument3DProbe)document;
            stage = "top-part";
            var topPartObject = document3D.TopPart;
            stage = "part7-query";
            var topPart = (IPart7Probe)topPartObject;
            stage = "sketch-collection";
            var sketchCollection = (ISketchsProbe)topPart.Sketchs;
            stage = "sketch-add";
            object sketchObject = sketchCollection.Add();
            var sketch = (ISketchProbe)sketchObject;
            stage = "sketch-plane";
            sketch.Plane = topPart.DefaultObject(1); // kAPI7.tlb: o3d_planeXOY = 1
            stage = "sketch-edit";
            object fragmentObject = sketch.BeginEdit();
            stage = "line-collection";
            var fragment = (IFragmentDocumentProbe)fragmentObject;
            var manager = (IViewsAndLayersManagerProbe)fragment.ViewsAndLayersManager;
            var views = (IViewsProbe)manager.Views;
            var activeView = (IViewProbe)views.ActiveView;
            var lines = (ILineSegmentsProbe)activeView.LineSegments;
            foreach (var edge in new[] { (-20d, -10d, 20d, -10d), (20d, -10d, 20d, 10d), (20d, 10d, -20d, 10d), (-20d, 10d, -20d, -10d) })
            {
                var lineObject = lines.Add();
                var line = (ILineSegmentProbe)lineObject;
                line.X1 = edge.Item1; line.Y1 = edge.Item2; line.X2 = edge.Item3; line.Y2 = edge.Item4;
                if (!line.Update()) throw new WorkerException("SKETCH_INVALID", "Rectangle edge update failed.");
                Marshal.FinalReleaseComObject(lineObject);
            }
            if (!sketch.EndEdit()) throw new WorkerException("SKETCH_INVALID", "KOMPAS did not finish sketch editing.");
            stage = "extrusion-collection";
            var extrusionCollection = (IExtrusionsProbe)topPart.Extrusions;
            object extrusionObject = extrusionCollection.Add(24); // kAPI3D constants: o3d_baseExtrusion = 24
            stage = "extrusion-parameters";
            var extrusion = (IExtrusionProbe)extrusionObject;
            extrusion.Sketch = sketchObject;
            extrusion.Direction = 0; // dtNormal = 0
            if (!extrusion.SetSideParameters(true, 0, 10d, 0d, false, null)) // etBlind = 0
                throw new WorkerException("FEATURE_BUILD_FAILED", "Extrusion parameters were rejected.");
            if (!extrusion.Update() || !topPart.RebuildModel(false))
                throw new WorkerException("FEATURE_BUILD_FAILED", "Extrusion rebuild failed.");
            Marshal.FinalReleaseComObject(extrusionObject);
            Marshal.FinalReleaseComObject(fragmentObject);
            Marshal.FinalReleaseComObject(sketchObject);
            Marshal.FinalReleaseComObject(topPartObject);

            dynamic partDocument = document;
            partDocument.SaveAs(outputPath);
            if (!File.Exists(outputPath) || new FileInfo(outputPath).Length == 0)
                throw new WorkerException("SAVE_FAILED", "KOMPAS did not create the M3D probe artifact.");

            var version = FileVersionInfo.GetVersionInfo(ExpectedExecutable);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                status = "COM_ACTIVATION_OK",
                api = "7",
                prog_id = ProgId,
                product = version.ProductName,
                file_version = version.FileVersion,
                document = "part",
                geometry = "rectangle_40x20_extrude_10",
                m3d_size_bytes = new FileInfo(outputPath).Length,
                owned_pid = ownedProcess?.Id
            }));
            return 0;
        }
        catch (COMException error)
        {
            throw new WorkerException("COM_INITIALIZATION_FAILED", $"KOMPAS COM activation failed (HRESULT 0x{error.HResult:X8}).");
        }
        catch (WorkerException) { throw; }
        catch (Exception error)
        {
            throw new WorkerException("KOMPAS_PROBE_FAILED", $"KOMPAS geometry probe failed at {stage} ({error.GetType().Name}, HRESULT 0x{error.HResult:X8}).");
        }
        finally
        {
            if (document is not null)
            {
                try { ((dynamic)document).Close(0); } catch { }
                if (Marshal.IsComObject(document)) Marshal.FinalReleaseComObject(document);
            }
            if (documents is not null && Marshal.IsComObject(documents))
                Marshal.FinalReleaseComObject(documents);
            if (application is not null)
            {
                try { ((dynamic)application).Quit(); } catch { }
            }
            if (application is not null && Marshal.IsComObject(application))
                Marshal.FinalReleaseComObject(application);
            ownedProcess ??= Process.GetProcessesByName("KOMPAS").FirstOrDefault(process => !existing.Contains(process.Id));
            if (ownedProcess is not null && !ownedProcess.HasExited)
            {
                ownedProcess.CloseMainWindow();
                if (!ownedProcess.WaitForExit(5000))
                    ownedProcess.Kill(entireProcessTree: true);
            }
            ownedProcess?.Dispose();
            if (File.Exists(outputPath)) File.Delete(outputPath);
        }
    }
}
