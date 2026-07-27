using System.Runtime.InteropServices;

namespace CadAi.LocalWorker;

[ComImport, Guid("7B60E769-06C3-4FDC-9677-7B5EF5180308"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKompasDocument3DProbe
{
    [DispId(5002)] object TopPart { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("FA4A5FDE-A08C-4F5A-8C04-98395BA44307"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPart7Probe
{
    [DispId(19)]
    [return: MarshalAs(UnmanagedType.IDispatch)]
    object DefaultObject(int type);
    [DispId(22)] bool RebuildModel(bool redraw);
    // kAPI7.tlb exposes these members through the IModelContainer auxiliary
    // dispatch implemented by Part7. Keeping the IPart7 IID avoids a QI for
    // IModelContainer, which KOMPAS does not advertise as a standalone COM
    // interface even though it accepts the documented DISPIDs.
    [DispId(10002)] object Sketchs { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10003)] object Extrusions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("2C6E8A0F-EDC8-413C-9304-9278817B915B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IModelContainerProbe
{
    [DispId(10002)] object Sketchs { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10003)] object Extrusions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("EE562963-395C-4748-9726-FCA9C531B1CA"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ISketchsProbe
{
    [DispId(2)]
    [return: MarshalAs(UnmanagedType.IDispatch)]
    object Add();
}

[ComImport, Guid("E6BBF50D-8401-4FB3-A6B6-153D3F447255"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ISketchProbe
{
    [DispId(1)] object Plane { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    [DispId(7)]
    [return: MarshalAs(UnmanagedType.IDispatch)]
    object BeginEdit();
    [DispId(8)] bool EndEdit();
}

[ComImport, Guid("E19CE626-DF9C-48C4-A83D-3E3BC7F0DACA"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IFragmentDocumentProbe
{
    [DispId(1)] object ViewsAndLayersManager { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("A4737593-578B-4187-8CAD-E1056EB5404B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IViewsAndLayersManagerProbe
{
    [DispId(1)] object Views { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("9CD1B5E6-C1A2-4910-8D0C-97080B14AA3D"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IViewsProbe
{
    [DispId(4)] object ActiveView { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("21A7BA87-1C8B-41B4-8247-CDD593546F37"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IViewProbe
{
    // IDrawingContainer auxiliary dispatch member implemented by View.
    [DispId(5003)] object LineSegments { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("D603FEC9-75B7-4FA5-918F-47074C45B848"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDrawingContainerProbe
{
    [DispId(5003)] object LineSegments { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("B211C782-A830-468E-9F4F-C499A77078D8"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegmentsProbe
{
    [DispId(2)]
    [return: MarshalAs(UnmanagedType.IDispatch)]
    object Add();
}

[ComImport, Guid("64ACC86F-4B10-4897-8552-BC0A556D228B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegmentProbe
{
    [DispId(1)] double X1 { set; }
    [DispId(2)] double Y1 { set; }
    [DispId(3)] double X2 { set; }
    [DispId(4)] double Y2 { set; }
    [DispId(3004)] bool Update();
}

[ComImport, Guid("07EF021F-11C1-4015-8D87-4DC94A2A71B0"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDrawingObjectProbe
{
    [DispId(3004)] bool Update();
}

[ComImport, Guid("A160C032-CF96-4467-A682-CE2243DF76BD"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IExtrusionsProbe
{
    [DispId(2)]
    [return: MarshalAs(UnmanagedType.IDispatch)]
    object Add(int extrusionType);
}

[ComImport, Guid("0D7FFE70-33EB-442C-A9B6-A205EA85A237"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IExtrusionProbe
{
    [DispId(1)] object Sketch { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    [DispId(2)] int Direction { set; }
    [DispId(9)]
    bool SetSideParameters(
        [MarshalAs(UnmanagedType.VariantBool)] bool normal,
        int extrusionType,
        double depth,
        double draftValue,
        [MarshalAs(UnmanagedType.VariantBool)] bool draftOutward,
        [MarshalAs(UnmanagedType.Interface)] object? depthObject);
    [DispId(503)] bool Update();
}

[ComImport, Guid("E37256D4-9021-47AC-8FAF-3713FB2A50C3"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IModelObjectProbe
{
    [DispId(503)] bool Update();
}
