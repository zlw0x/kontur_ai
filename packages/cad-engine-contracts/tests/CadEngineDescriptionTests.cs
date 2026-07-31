using CadAi.CadEngine;
using Xunit;

namespace CadAi.CadEngine.Tests;

/// <summary>
/// An engine says what it is and what it produces; nothing else gets to assume.
/// </summary>
/// <remarks>
/// The pipeline used to carry `M3D`, `STEP`, `STL` as a literal list and refuse
/// any job that did not upload an `M3D` — a KOMPAS-native format written into the
/// definition of a finished job. ADR-023 introduces an engine that produces no
/// such file, so the list had to come from the engine instead.
///
/// These tests run on plain net8.0. That is the point of the project they are in:
/// the engine-neutral half must be testable on a machine with no CAD installed at
/// all, and a Windows-only test project would have hidden the day that stopped
/// being true.
/// </remarks>
public sealed class CadEngineDescriptionTests
{
    [Fact]
    public async Task TheFakeEngineDescribesItselfWithoutBuildingAnything()
    {
        var report = await new FakeDocumentEngine("1.6").DescribeAsync([], CancellationToken.None);

        Assert.Equal("fake", report.Engine.EngineId);
        Assert.Equal("1.6", report.Engine.CadIrVersion);
        Assert.Equal("FAKE_CAD", Assert.Single(report.Engine.Artifacts).Kind);
        // Nothing declared, so the API will not schedule real work to a worker
        // running it. A fake that advertised operations would be a fake that gets
        // given a customer's order.
        Assert.Empty(report.Capabilities);
    }

    /// <summary>
    /// A result that did not say which engine produced it would be untraceable
    /// exactly when it matters: a delivered model nobody can trace to a build.
    /// </summary>
    [Fact]
    public async Task ABuildResultCarriesTheEngineThatProducedIt()
    {
        var job = Directory.CreateTempSubdirectory("cad-fake-");
        try
        {
            File.WriteAllText(Path.Combine(job.FullName, "cad-ir.json"), "{}");
            var result = await new FakeDocumentEngine("1.6").BuildAsync(
                new CadDocumentBuildRequest(job.FullName, []), CancellationToken.None);

            Assert.NotNull(result.Engine);
            // Field by field rather than record equality: the description holds a
            // list, and a record compares that by reference, so two equal
            // descriptions built separately would compare unequal.
            var expected = FakeDocumentEngine.Identity("1.6");
            Assert.Equal(expected.EngineId, result.Engine!.EngineId);
            Assert.Equal(expected.EngineVersion, result.Engine.EngineVersion);
            Assert.Equal(expected.KernelId, result.Engine.KernelId);
            Assert.Equal(expected.CadIrVersion, result.Engine.CadIrVersion);
            Assert.Equal(
                FakeDocumentEngine.FileName,
                Path.GetFileName(Assert.Single(result.Artifacts).Path));
        }
        finally
        {
            job.Delete(recursive: true);
        }
    }

    /// <summary>A job with no document is a typed refusal, not an empty success.</summary>
    [Fact]
    public async Task TheFakeStillRefusesAJobWithNoDocument()
    {
        var job = Directory.CreateTempSubdirectory("cad-fake-");
        try
        {
            var refused = await Assert.ThrowsAsync<CadAdapterException>(() =>
                new FakeDocumentEngine("1.6").BuildAsync(
                    new CadDocumentBuildRequest(job.FullName, []), CancellationToken.None));
            Assert.Equal("CAD_IR_MISSING", refused.Code);
        }
        finally
        {
            job.Delete(recursive: true);
        }
    }

    [Fact]
    public void OnlyTheArtifactsAnEngineCallsRequiredAreRequired()
    {
        var engine = new CadEngineDescription(
            "example", "1", "kernel", "9", "1.6",
            [
                new CadArtifactKind("STEP", "model.step"),
                new CadArtifactKind("STL", "model.stl"),
                new CadArtifactKind("PREVIEW", "preview.png", Required: false)
            ]);

        Assert.Equal(["STEP", "STL"], engine.RequiredArtifacts.Select(item => item.Kind));
    }

    /// <summary>
    /// An engine that cannot read its kernel's version says nothing rather than
    /// reporting a number somebody typed into a constant.
    /// </summary>
    /// <remarks>
    /// An unverified version string is worse than an absent one: it reads as
    /// measured, and it is wrong on the first machine with a different install.
    /// </remarks>
    [Fact]
    public void AnUnknownKernelVersionIsExpressible()
    {
        var engine = new CadEngineDescription("example", "1", "kernel", null, "1.6", []);

        Assert.Null(engine.KernelVersion);
    }

    [Fact]
    public void AnEmptyOutputDirectoryIsRefusedRatherThanResolvedToSomewhere()
    {
        var error = Assert.Throws<CadAdapterException>(() => CadOutputDirectory.Safe("  "));

        Assert.Equal("OUTPUT_PATH_INVALID", error.Code);
    }
}
