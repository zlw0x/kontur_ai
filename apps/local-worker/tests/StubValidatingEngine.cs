using CadAi.CadEngine;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// Enough of an engine to exercise the repair loop, and no more.
/// </summary>
/// <remarks>
/// The repair loop asks the engine whether it would accept a candidate document
/// (ENGINE-MIG-008), so a test of the loop needs something that can say no. It is
/// deliberately not a validator: it applies one rule the real engine also applies —
/// a document whose only geometric feature is a cut has nothing to cut, and the
/// engine refuses it with `UNSUPPORTED_FEATURE_SET` before making a face.
///
/// Testing the loop against a stub rather than the real engine is the right trade
/// here: what is under test is whether a refusal provokes exactly one repair and
/// whether the ledger sees it, and nothing about that is geometry. That the real
/// engine refuses the real thing is checked in `RealEngineTests` and
/// `test_capabilities.py`.
/// </remarks>
internal sealed class StubValidatingEngine : ICadDocumentEngine
{
    public int Validations { get; private set; }

    public Task<CadEngineReport> DescribeAsync(
        IReadOnlyCollection<string> disabledCapabilities, CancellationToken cancellationToken) =>
        Task.FromResult(new CadEngineReport(
            FakeDocumentEngine.Identity(WorkerCapabilities.CadIrVersion),
            new Dictionary<string, CadCapabilityDeclaration>(StringComparer.Ordinal)));

    public async Task<IReadOnlyCollection<string>> ValidateAsync(
        CadDocumentBuildRequest request, CancellationToken cancellationToken)
    {
        Validations++;
        var document = await File.ReadAllTextAsync(
            Path.Combine(request.JobDirectory, "cad-ir.json"), cancellationToken);
        if (!document.Contains("solid.extrude", StringComparison.Ordinal) &&
            !document.Contains("solid.revolve", StringComparison.Ordinal))
            throw new CadAdapterException(
                "UNSUPPORTED_FEATURE_SET",
                "feature",
                "The document cuts, and nothing has been built for it to cut.");
        return ["solid.rectangular_prism"];
    }

    public Task<CadBuildResult> BuildAsync(
        CadDocumentBuildRequest request, CancellationToken cancellationToken) =>
        new FakeDocumentEngine(WorkerCapabilities.CadIrVersion)
            .BuildAsync(request, cancellationToken);
}
