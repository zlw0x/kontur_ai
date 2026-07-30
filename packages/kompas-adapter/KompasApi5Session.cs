using CadAi.CadEngine;

namespace CadAi.KompasAdapter;

/// <summary>
/// One KOMPAS API5 application object, held for the life of a build.
/// </summary>
/// <remarks>
/// Created once, not once per use. Activating API5 again while the first
/// instance is busy serving API7 starts a *second* KOMPAS process, and that one
/// has no document open — so `ActiveDocument3D` answers with nothing and
/// whatever needed it fails for a reason that looks nothing like the cause.
///
/// Found twice, the hard way: once when a selector stability run could read the
/// first phase and not the second (POSTMVP-005), and again when a build that
/// resolved a face for a sketch then could not export (POSTMVP-006). Holding
/// the object is the fix in both cases.
///
/// API5 is needed at all because API7 has no face collection and no additional
/// export format; see ADR-019.
/// </remarks>
internal sealed class KompasApi5Session : IDisposable
{
    private const string Api5ProgId = "KOMPAS.Application.5";

    private object? application;

    private object Application()
    {
        if (application is not null) return application;
        var api5Type = Type.GetTypeFromProgID(Api5ProgId, throwOnError: false)
            ?? throw KompasApi7Adapter.Failure(
                "COM_INITIALIZATION_FAILED", "activation", "KOMPAS API5 registration was not found.");
        application = Activator.CreateInstance(api5Type)
            ?? throw KompasApi7Adapter.Failure(
                "COM_INITIALIZATION_FAILED", "activation", "KOMPAS API5 returned no application object.");
        return application;
    }

    /// <summary>The API5 view of whatever document is active. Caller releases.</summary>
    public object ActiveDocument3D(string stage) =>
        ((IKompasApi5Application)Application()).ActiveDocument3D()
        ?? throw KompasApi7Adapter.Failure(
            "TOPOLOGY_READ_FAILED", stage, "KOMPAS reported no active 3D document.");

    /// <summary>The top part, for reading topology. Caller releases both.</summary>
    public (object Document, object Part) TopPart(string stage)
    {
        var documentObject = ActiveDocument3D(stage);
        var partObject = ((IKompasApi5Document3D)documentObject).GetPart(KompasApi5Constants.TopPart);
        if (partObject is null)
        {
            KompasApi7Adapter.Release(documentObject);
            throw KompasApi7Adapter.Failure(
                "TOPOLOGY_READ_FAILED", stage, "KOMPAS returned no top part.");
        }
        return (documentObject, partObject);
    }

    public void Dispose()
    {
        KompasApi7Adapter.Release(application);
        application = null;
    }
}
