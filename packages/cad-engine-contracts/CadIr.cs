namespace CadAi.CadEngine;

/// <summary>
/// The CAD-IR version this build of the .NET side speaks.
/// </summary>
/// <remarks>
/// One declaration, in the assembly every other project references. It was in
/// <c>WorkerCapabilities</c> before, which the worker's own tests could see and the
/// launcher's could not — so the launcher pinned the version as a literal, and a literal
/// is a copy waiting to fall behind.
///
/// This is the .NET side's *claim* about the version, not the engine's. The engine
/// declares its own (<c>cad_engine_build123d</c> reads it from the contract package), and
/// the two being compared is the point of
/// <c>RealEngineTests.TheEngineDescribesItselfInTheShapeThisSideParses</c>: the assertion
/// is not a tautology, it is the two halves of the boundary agreeing.
/// </remarks>
public static class CadIr
{
    public const string Version = "1.12";

    /// <summary>The version as a filename fragment: <c>1.10</c> is <c>v1_10</c>.</summary>
    public static string FileSuffix => "v" + Version.Replace('.', '_');
}
