# TASK-006: KOMPAS probe evidence

## Installed product

- Product: KOMPAS-3D v22 x64
- Executable: `C:\Program Files\ASCON\KOMPAS-3D v22\Bin\KOMPAS.exe`
- File version: `22.0.0.1302`
- API7 ProgID: `KOMPAS.Application.7`
- API7 CLSID: `{8C3719B5-0DF2-4C12-9CA8-3AF4827A3BBB}`
- API7 typelib SHA-256:
  `610E23A8FD013E63E9AC338C0F2ED03957A7C99A7369DE7E2A76613CFB3B5413`
- API5 typelib SHA-256:
  `690EAB61EF6B004A1CB7F4EDA19FDE778EF11F8DAB0EB05ED25A90D0B1C5EE9C`

## Probe result

The probe activates the registered API7 COM server, creates a part document,
saves a non-empty M3D file and closes the document/application. On 2026-07-27
the command

```powershell
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-kompas
```

returned:

```json
{"status":"COM_ACTIVATION_OK","api":"7","prog_id":"KOMPAS.Application.7","product":"KOMPAS v22 (x64)","file_version":"22.0.0.1302","document":"part","geometry":"rectangle_40x20_extrude_10","m3d_size_bytes":53038,"owned_pid":11096}
```

The generated geometry is a closed 40 x 20 mm rectangle on XOY, followed by a
10 mm base extrusion. The probe verifies that the temporary M3D exists and is
non-empty before removing it.

## Typelib evidence

Every invoked member, IID, DISPID and enum value was extracted from the
installed `kAPI7.tlb` and KOMPAS 3D constants typelib. The minimal interop
declarations are isolated in `apps/local-worker/KompasProbeInterop.cs`.

- document lifecycle: `IApplication.Documents`, `IDocuments.Add`,
  `ksDocumentPart=4`, `IKompasDocument.SaveAs`,
  `IKompasDocument.Close`, `kdDoNotSaveChanges=0`, `IApplication.Quit`;
- 3D root: `IKompasDocument3D.TopPart`, `IPart7.DefaultObject`,
  `o3d_planeXOY=1`, `IPart7.RebuildModel`;
- model container dispatch: `IModelContainer.Sketchs` (DISPID 10002) and
  `IModelContainer.Extrusions` (DISPID 10003), invoked through the `Part7`
  dispatch as required by the installed implementation;
- sketch: `ISketchs.Add`, `ISketch.Plane`, `ISketch.BeginEdit`,
  `ISketch.EndEdit`;
- 2D geometry: `IFragmentDocument.ViewsAndLayersManager`,
  `IViewsAndLayersManager.Views`, `IViews.ActiveView`,
  `IDrawingContainer.LineSegments`, `ILineSegments.Add`,
  `ILineSegment.X1/Y1/X2/Y2`, `IDrawingObject.Update`;
- feature: `IExtrusions.Add`, `o3d_baseExtrusion=24`,
  `IExtrusion.Sketch`, `IExtrusion.Direction`, `dtNormal=0`,
  `IExtrusion.SetSideParameters`, `etBlind=0`, `IModelObject.Update`.

## Process discipline

If activation creates a new KOMPAS process, cleanup targets only that PID;
pre-existing user processes are never terminated.

Hole, STEP and STL probes are intentionally deferred to the versioned
`KompasAdapter` feature handlers. They may only be added after their exact
members are confirmed from the same installed type libraries.
