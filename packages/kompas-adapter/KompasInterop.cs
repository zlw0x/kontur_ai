using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

[ComImport, Guid("7B60E769-06C3-4FDC-9677-7B5EF5180308"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKompasDocument3D
{
    [DispId(5002)] object TopPart { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("FA4A5FDE-A08C-4F5A-8C04-98395BA44307"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPart7
{
    [DispId(19)] [return: MarshalAs(UnmanagedType.IDispatch)] object DefaultObject(int type);
    [DispId(22)] bool RebuildModel(bool redraw);
    [DispId(10002)] object Sketchs { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10003)] object Extrusions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("EE562963-395C-4748-9726-FCA9C531B1CA"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ISketchs
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("E6BBF50D-8401-4FB3-A6B6-153D3F447255"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ISketch
{
    [DispId(1)] object Plane { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    [DispId(7)] [return: MarshalAs(UnmanagedType.IDispatch)] object BeginEdit();
    [DispId(8)] bool EndEdit();
}

[ComImport, Guid("E19CE626-DF9C-48C4-A83D-3E3BC7F0DACA"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IFragmentDocument
{
    [DispId(1)] object ViewsAndLayersManager { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("A4737593-578B-4187-8CAD-E1056EB5404B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IViewsAndLayersManager
{
    [DispId(1)] object Views { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("9CD1B5E6-C1A2-4910-8D0C-97080B14AA3D"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IViews
{
    [DispId(4)] object ActiveView { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("21A7BA87-1C8B-41B4-8247-CDD593546F37"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IView
{
    [DispId(5003)] object LineSegments { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(5007)] object Circles { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("B211C782-A830-468E-9F4F-C499A77078D8"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegments
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("64ACC86F-4B10-4897-8552-BC0A556D228B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegment
{
    [DispId(1)] double X1 { set; }
    [DispId(2)] double Y1 { set; }
    [DispId(3)] double X2 { set; }
    [DispId(4)] double Y2 { set; }
    [DispId(3004)] bool Update();
}

[ComImport, Guid("C8CA9255-E5FE-4396-9C3F-75EE7377C508"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ICircles
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("5C952F95-DFED-4EEE-B39A-6699EDE08676"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ICircle
{
    [DispId(1)] double Xc { set; }
    [DispId(2)] double Yc { set; }
    [DispId(5)] double Radius { set; }
    [DispId(3004)] bool Update();
}

[ComImport, Guid("A160C032-CF96-4467-A682-CE2243DF76BD"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IExtrusions
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add(int extrusionType);
}

[ComImport, Guid("0D7FFE70-33EB-442C-A9B6-A205EA85A237"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IExtrusion
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

[ComImport, Guid("58B4011D-3C0B-499A-A441-7870B663E8CF"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IExtrusion1
{
    [DispId(14)] int OperationResult { set; }
}

[ComImport, Guid("E36BC97C-39D6-4402-9C25-C7008A217E02"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKompasApi5Application
{
    [DispId(3)] [return: MarshalAs(UnmanagedType.IDispatch)] object ActiveDocument3D();
}

[ComImport, Guid("111CEFE1-A0A7-11D6-95CE-00C0262D30E3"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IKompasApi5Document3D
{
    [DispId(37)] bool SaveAsToAdditionFormat(
        [MarshalAs(UnmanagedType.BStr)] string fileName,
        [MarshalAs(UnmanagedType.IDispatch)] object additionParameters);
    [DispId(38)] [return: MarshalAs(UnmanagedType.IDispatch)] object AdditionFormatParam();
}

[ComImport, Guid("0FD25FF9-AB0A-48F3-BAD4-F193116C0887"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IAdditionFormatParam
{
    [DispId(1)] short Format { set; }
    [DispId(2)] bool FormatBinary { set; }
    [DispId(4)] bool Init();
    [DispId(7)] int StepType { set; }
    [DispId(8)] double Step { set; }
    [DispId(9)] double Angle { set; }
    [DispId(11)] int MaxTessellationCellCount { set; }
    [DispId(12)] int LengthUnits { set; }
}
