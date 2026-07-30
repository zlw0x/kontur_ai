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
    public void TheFakeEngineDescribesItselfWithoutBuildingAnything()
    {
        var engine = new FakeCadAdapter().Describe();

        Assert.Equal("fake", engine.EngineId);
        Assert.Equal(CadIrBuildPlanParser.CadIrVersion, engine.CadIrVersion);
        Assert.Equal("FAKE_CAD", Assert.Single(engine.Artifacts).Kind);
    }

    /// <summary>
    /// A result that did not say which engine produced it would be untraceable
    /// exactly when it matters: two engines building the same document and
    /// disagreeing.
    /// </summary>
    [Fact]
    public async Task ABuildResultCarriesTheEngineThatProducedIt()
    {
        var directory = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        try
        {
            var adapter = new FakeCadAdapter();
            var result = await adapter.BuildAsync(
                new CadBuildRequest(Plan(), directory), CancellationToken.None);

            Assert.NotNull(result.Engine);
            // Field by field rather than record equality: the description holds a
            // list, and a record compares that by reference, so two equal
            // descriptions built separately would compare unequal.
            var expected = adapter.Describe();
            Assert.Equal(expected.EngineId, result.Engine!.EngineId);
            Assert.Equal(expected.EngineVersion, result.Engine.EngineVersion);
            Assert.Equal(expected.KernelId, result.Engine.KernelId);
            Assert.Equal(expected.CadIrVersion, result.Engine.CadIrVersion);
            Assert.Equal(
                expected.Artifacts.Select(item => item.Kind),
                result.Engine.Artifacts.Select(item => item.Kind));
            // And the checksum is of the bytes on disk, not of what was meant.
            var artifact = Assert.Single(result.Artifacts);
            Assert.Equal(new FileInfo(artifact.Path).Length, artifact.SizeBytes);
            Assert.Equal(64, artifact.Sha256.Length);
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }

    /// <remarks>
    /// The distinction the upload check runs on: a job that did not produce
    /// something its engine promised has failed, and a job missing something the
    /// engine called optional has not.
    /// </remarks>
    [Fact]
    public void OnlyTheArtifactsAnEngineCallsRequiredAreRequired()
    {
        var engine = new CadEngineDescription(
            "example", "1", "kernel", "9", "1.3",
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
        var engine = new CadEngineDescription("example", "1", "kernel", null, "1.3", []);

        Assert.Null(engine.KernelVersion);
    }

    [Fact]
    public void AnEmptyOutputDirectoryIsRefusedRatherThanResolvedToSomewhere()
    {
        var error = Assert.Throws<CadAdapterException>(() => CadOutputDirectory.Safe("  "));

        Assert.Equal("OUTPUT_PATH_INVALID", error.Code);
    }

    private static CadBuildPlan Plan() => new(
        [
            new ExtrudeFeaturePlan(
                "feature.base",
                new SketchPlan(
                    "sketch.base",
                    new BasePlanePlan("XY"),
                    new CircleContourPlan(new Point2(0, 0), 10),
                    [],
                    []),
                8,
                IsCut: false)
        ],
        new ExpectedGeometryPlan(20, 20, 8, 0.05, 1, 0));
}
