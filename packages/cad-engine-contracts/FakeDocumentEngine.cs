using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace CadAi.CadEngine;

/// <summary>
/// An engine that writes plausible files and builds nothing.
/// </summary>
/// <remarks>
/// The replacement for `FakeCadAdapter`, which was shaped around a build plan and
/// went with the plan (ENGINE-MIG-008). The reason to have one is unchanged and is
/// a rule in `AGENTS.md`: **CI must not require a real engine.** Every test of the
/// lease, the ledger, the state file, the artifact upload and the retry path needs
/// a job that finishes, and none of them needs geometry.
///
/// It is honest about being a fake. Its `EngineId` is `fake`, the one file it
/// writes is called `model.fake-cad.json` and says so inside, and it declares no
/// STEP and no STL — so anything downstream that requires a real artifact refuses
/// a fake job rather than shipping one. A fake that produced a file named
/// `model.step` would be a way for a test double to reach a customer.
/// </remarks>
public sealed class FakeDocumentEngine : ICadDocumentEngine
{
    public const string FileName = "model.fake-cad.json";

    /// <remarks>
    /// The fake has a kernel version because it *is* its own kernel: there is
    /// nothing underneath it that could be a different version from itself.
    /// </remarks>
    public static CadEngineDescription Identity(string cadIrVersion) => new(
        EngineId: "fake",
        EngineVersion: "1",
        KernelId: "none",
        KernelVersion: "none",
        CadIrVersion: cadIrVersion,
        Artifacts: [new CadArtifactKind("FAKE_CAD", FileName)]);

    private readonly string cadIrVersion;

    public FakeDocumentEngine(string cadIrVersion) => this.cadIrVersion = cadIrVersion;

    public Task<CadEngineReport> DescribeAsync(
        IReadOnlyCollection<string> disabledCapabilities,
        CancellationToken cancellationToken) =>
        Task.FromResult(new CadEngineReport(
            Identity(cadIrVersion),
            // No capability is declared, so the API will not schedule real work
            // to a worker running this. A fake that advertised operations would
            // be a fake that gets given a customer's order.
            new Dictionary<string, CadCapabilityDeclaration>(StringComparer.Ordinal)));

    /// <remarks>
    /// The fake accepts any document that is there at all. It has no opinion
    /// about what a valid one is, and forming one would be exactly the second
    /// validator this design avoids.
    /// </remarks>
    public Task<IReadOnlyCollection<string>> ValidateAsync(
        CadDocumentBuildRequest request,
        CancellationToken cancellationToken)
    {
        var document = Path.Combine(CadOutputDirectory.Safe(request.JobDirectory), "cad-ir.json");
        if (!File.Exists(document))
            throw new CadAdapterException(
                "CAD_IR_MISSING", "prepare", "No cad-ir.json in the job directory.");
        return Task.FromResult<IReadOnlyCollection<string>>([]);
    }

    public async Task<CadBuildResult> BuildAsync(
        CadDocumentBuildRequest request,
        CancellationToken cancellationToken)
    {
        var started = Stopwatch.GetTimestamp();
        var job = CadOutputDirectory.Safe(request.JobDirectory);
        var document = Path.Combine(job, "cad-ir.json");
        if (!File.Exists(document))
            throw new CadAdapterException(
                "CAD_IR_MISSING", "prepare", $"No cad-ir.json in {Path.GetFileName(job)}.");

        var output = Directory.CreateDirectory(Path.Combine(job, "output")).FullName;
        var path = Path.Combine(output, FileName);
        await File.WriteAllTextAsync(
            path,
            JsonSerializer.Serialize(new
            {
                engine = "fake",
                note = "No geometry was built. This file exists so a pipeline can be tested.",
                // Read rather than parsed: the fake has no opinion about what a
                // valid document is, and forming one would be a third validator.
                cad_ir_bytes = new FileInfo(document).Length,
                disabled_capabilities = request.DisabledCapabilities.Order(StringComparer.Ordinal)
            }),
            Encoding.UTF8,
            cancellationToken);

        return new CadBuildResult(
            [CadArtifact.Read("FAKE_CAD", path)],
            // The fake reports a timing too, so the ledger's instrumentation is
            // exercised by CI rather than only on a machine with an engine.
            [new CadOperationRecord(
                "document_build",
                "feature",
                (long)Stopwatch.GetElapsedTime(started).TotalMilliseconds,
                Success: true)],
            Identity(cadIrVersion));
    }
}
