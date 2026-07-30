using CadAi.CadEngine;
using System.Runtime.InteropServices;

namespace CadAi.KompasAdapter;

internal static class KompasSketchStyles
{
    /// <summary>The only curve style an extrusion's profile is built from.</summary>
    /// <remarks>
    /// Measured on KOMPAS v22: with a stray line at style 1 inside a closed
    /// rectangle the extrusion fails, and at every style from 2 to 8 it
    /// succeeds. So the style is not decoration — it is what separates profile
    /// geometry from geometry that is merely present.
    /// </remarks>
    public const int Profile = 1;

    /// <summary>`Вспомогательная`: drawn, ignored by the profile.</summary>
    public const int Construction = 7;
}

internal static class KompasApi5Constants
{
    /// <summary>
    /// `pTop_Part`, the argument that makes `ksDocument3D.GetPart` answer with
    /// the top part.
    /// </summary>
    /// <remarks>
    /// The type library exports no named constant for it. Probed live on
    /// KOMPAS v22 against a plate this service had just built: -1 returned a
    /// part whose main body had six planar faces, while 0, 1 and 2 all
    /// returned nothing.
    /// </remarks>
    public const int TopPart = -1;
}

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
    // Answers with a VARIANT holding a SAFEARRAY of IDispatch: the objects at
    // that coordinate, of which one may be a face.
    [DispId(32)] [return: MarshalAs(UnmanagedType.Struct)] object? FindObjectsByPoint(
        double x, double y, double z, [MarshalAs(UnmanagedType.VariantBool)] bool firstLevel);
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
    [DispId(5008)] object Points { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(5003)] object LineSegments { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(5004)] object Arcs { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(5007)] object Circles { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10001)] object LineDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10002)] object RadialDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10003)] object DiametralDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10004)] object AngleDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    /// <summary>
    /// The variable a driving dimension's constraint created, looked up by name.
    /// </summary>
    /// <remarks>
    /// By name rather than by index: the index is a VARIANT and takes either, and
    /// a name is the only unambiguous handle. `Variables` returns the whole set as
    /// a single object when there is one variable and as something else when there
    /// are several, so reading it works for exactly one dimension and then stops.
    /// </remarks>
    [DispId(16)] [return: MarshalAs(UnmanagedType.IDispatch)] object? Variable(
        [MarshalAs(UnmanagedType.Struct)] object index);
    [DispId(17)] int VariablesCount();
}

[ComImport, Guid("B211C782-A830-468E-9F4F-C499A77078D8"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegments
{
    // The collection publishes an indexer and no count; walking it means
    // asking for indexes until one comes back empty.
    [DispId(1)] [return: MarshalAs(UnmanagedType.IDispatch)] object? LineSegment(int index);
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("4FCB4C17-3B9E-45E8-B83C-9284027BAA0D"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IArcs
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

/// <summary>
/// An arc is set from its centre, radius and two angles.
/// </summary>
/// <remarks>
/// The endpoint properties X1/Y1/X2/Y2 exist and are readable, but setting them
/// instead leaves `Update()` returning false with the radius at zero.
///
/// `Direction` 0 sweeps anticlockwise from Angle1 to Angle2; 1 and -1 both
/// sweep clockwise. Both facts measured on KOMPAS v22 — the direction by
/// extruding a half-disc and reading which side of the chord the material
/// landed on. See docs/TASK-POSTMVP-006-sketch-primitives.md.
/// </remarks>
[ComImport, Guid("A22DFB7E-21E0-4B28-9CA1-29B7950CF256"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IArc
{
    [DispId(1)] double Radius { get; set; }
    [DispId(2)] int Direction { get; set; }
    [DispId(3)] double Xc { get; set; }
    [DispId(4)] double Yc { get; set; }
    [DispId(11)] double Angle1 { get; set; }
    [DispId(12)] double Angle2 { get; set; }
    [DispId(13)] int Style { set; }
    [DispId(3004)] bool Update();
}

[ComImport, Guid("64ACC86F-4B10-4897-8552-BC0A556D228B"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineSegment
{
    [DispId(1)] double X1 { get; set; }
    [DispId(2)] double Y1 { get; set; }
    [DispId(3)] double X2 { get; set; }
    [DispId(4)] double Y2 { get; set; }
    [DispId(7)] int Style { set; }
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
    [DispId(6)] int Style { set; }
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
    [DispId(7)] [return: MarshalAs(UnmanagedType.IDispatch)] object? GetPart(int type);
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

[ComImport, Guid("950FEBE2-F916-4E77-A37D-B061E5C22FA8"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IAuxiliaryGeomContainer
{
    [DispId(14028)] object Planes3D { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("71B69C8B-FEAE-484F-BBDA-F7C71A94DDC7"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPlanes3D
{
    // 14 is the offset plane, 15 by angle, 16 through three points. The type
    // library exports no named constant; probed live on KOMPAS v22.
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object? Add(int planeType);
}

[ComImport, Guid("5F5E0FA2-84D7-44D1-A946-018EBEB82926"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPlane3DByOffset
{
    [DispId(101)] double Offset { set; }
    [DispId(102)] bool Direction { set; }
    [DispId(103)] object BasePlane { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
}

/// <summary>A model feature, as opposed to a sketch entity: Update is 503.</summary>
[ComImport, Guid("E37256D4-9021-47AC-8FAF-3713FB2A50C3"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IModelObject
{
    [DispId(503)] bool Update();
}

[ComImport, Guid("299A549E-3F82-4F60-98A3-258D632AA635"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IFace
{
    [DispId(11)] double GetArea(int units);
    [DispId(15)] bool IsPlanar { get; }
}

[ComImport, Guid("8C6846A4-EE3B-4C00-A708-5C0FD01E21B7"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPoints
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("D0C19C87-14E7-401D-AEF5-A2E88E899F6E"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IPoint
{
    [DispId(1)] double X { set; }
    [DispId(2)] double Y { set; }
    [DispId(4)] int Style { set; }
    [DispId(3004)] bool Update();
}

/// <summary>
/// The constraint and association half of a sketch entity.
/// </summary>
/// <remarks>
/// `Associate()` takes no arguments: it binds a dimension to whatever its own
/// points already sit on, and it has to be called before any constraint on a
/// dimension will create at all. Measured on KOMPAS v22.
/// </remarks>
[ComImport, Guid("649F0EB2-EBC0-449B-8B61-DC3CF1953BF9"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDrawingObject1
{
    [DispId(6002)] [return: MarshalAs(UnmanagedType.IDispatch)] object? NewConstraint();
    [DispId(6003)] bool Associate();
    [DispId(6001)] object? Constraints { [return: MarshalAs(UnmanagedType.Struct)] get; }
}

/// <summary>
/// One constraint. The `ConstraintType` integers were identified by measurement,
/// not read: the type libraries export no enumerations at all. See
/// <see cref="KompasConstraintTypes"/> and scripts/probe_kompas_constraints.py.
/// </summary>
/// <remarks>
/// `Valid` is deliberately not declared. It reports false for types 3 to 7,
/// which plainly work, and true for 9 to 11 — so reading it would invite
/// treating a working constraint as a failure.
/// </remarks>
[ComImport, Guid("131069F4-A4E2-4DB4-A559-85EACCC74CE4"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IParametriticConstraint
{
    [DispId(1)] int ConstraintType { set; }
    [DispId(2)] int Index { set; }
    [DispId(3)] object Partner { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    [DispId(4)] int PartnerIndex { set; }
    [DispId(8)] string Variable { [param: MarshalAs(UnmanagedType.BStr)] set; }
    [DispId(13)] bool Create();
    [DispId(15)] object Axis { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
}

/// <summary>
/// The `Update` every drawing object answers on, dimensions included.
/// </summary>
/// <remarks>
/// A dimension has to be updated before `Associate()` will bind it: without the
/// call the association simply returns false, which reads like a refusal rather
/// than an unfinished object.
/// </remarks>
[ComImport, Guid("07EF021F-11C1-4015-8D87-4DC94A2A71B0"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDrawingObject
{
    [DispId(3004)] bool Update();
}

/// <summary>Dimensions live here, not on the geometry container.</summary>
[ComImport, Guid("F46B0086-17F2-4489-A5A7-0AA677610AFD"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ISymbols2DContainer
{
    [DispId(10001)] object LineDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10002)] object RadialDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
    [DispId(10003)] object DiametralDimensions { [return: MarshalAs(UnmanagedType.IDispatch)] get; }
}

[ComImport, Guid("A6F6A18A-78FA-4A77-BB75-90647E0C545C"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineDimensions
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("A3767BDA-E605-4FC1-988D-81809DEB36F4"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface ILineDimension
{
    [DispId(1)] double X1 { set; }
    [DispId(2)] double Y1 { set; }
    [DispId(3)] double X2 { set; }
    [DispId(4)] double Y2 { set; }
    [DispId(5)] double X3 { set; }
    [DispId(6)] double Y3 { set; }
}

[ComImport, Guid("12D26993-449E-42E2-A909-B047AFD6E27D"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IRadialDimensions
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

[ComImport, Guid("712A9437-D772-4EAE-AF83-ABC9C22EB281"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IRadialDimension
{
    [DispId(1)] double Xc { set; }
    [DispId(2)] double Yc { set; }
    [DispId(3)] double Radius { set; }
}

[ComImport, Guid("8E45FEB9-7BCD-4C9F-9767-320736980662"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDiametralDimensions
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object Add();
}

/// <summary>
/// Angular dimensions. `Add` takes a type, unlike every other dimension
/// collection here, and answers nothing for almost every value.
/// </summary>
/// <remarks>
/// Swept from -2 to 64 by `scripts/probe_kompas_driving.py`: only 10 and 39
/// create anything. An earlier probe tried 0 to 4, found nothing, and recorded
/// that angular dimensions do not exist — which was a statement about the range
/// swept, not about KOMPAS.
/// </remarks>
[ComImport, Guid("DF9ABB77-BBB6-4B29-A0E0-81DCFD525C2E"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IAngleDimensions
{
    [DispId(2)] [return: MarshalAs(UnmanagedType.IDispatch)] object? Add(int dimensionType);
}

[ComImport, Guid("0F2CE9EC-5D2A-4B21-B96A-46201C120ED1"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IAngleDimension
{
    [DispId(1)] double Xc { set; }
    [DispId(2)] double Yc { set; }
    [DispId(3)] double Radius { set; }
    /// <summary>The two objects the angle is between, named outright.</summary>
    /// <remarks>
    /// This is why an angle needs no `Associate()`: it says what it measures
    /// instead of being bound to whatever its points happen to land on.
    /// </remarks>
    [DispId(10)] object BaseObject1 { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
    [DispId(11)] object BaseObject2 { [param: MarshalAs(UnmanagedType.IDispatch)] set; }
}

[ComImport, Guid("2B4CE92F-438D-4D3E-8F8D-4D14E5D0E214"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IDiametralDimension
{
    [DispId(1)] double Xc { set; }
    [DispId(2)] double Yc { set; }
    [DispId(3)] double Radius { set; }
}

/// <summary>
/// The variable a driving dimension's constraint created, on the view.
/// </summary>
/// <remarks>
/// Its `Value` reads back as the measurement KOMPAS took, which is exactly what
/// the confirmatory design needs. Setting it does *not* move the geometry —
/// four ways of trying are recorded in
/// docs/TASK-POSTMVP-007-sketch-constraints.md — and the design does not need
/// it to, because the document already carries the coordinates.
/// </remarks>
[ComImport, Guid("8BAB52D9-8EF6-43A6-A1B8-AF42D5961A94"), InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
internal interface IVariable7
{
    [DispId(1)] string Name { [return: MarshalAs(UnmanagedType.BStr)] get; }
    [DispId(3)] double Value { get; }
}
