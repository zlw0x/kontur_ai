using System.Text.Json;
using CadAi.KompasAdapter;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// A rollback that does not actually stop the operation is worse than none: the
/// operator believes the bad geometry has stopped being produced. So the tests
/// here are about both halves of the switch — the manifest the API schedules
/// from, and the gate the build refuses at.
/// </summary>
public sealed class FeatureFlagsTests : IDisposable
{
    private readonly string root = Path.Combine(
        Path.GetTempPath(), $"cad-ai-flags-{Guid.NewGuid():N}");

    private WorkerPaths Paths() => new(
        StateRoot: root,
        WorkspaceRoot: Path.Combine(root, "work"),
        ConfigPath: Path.Combine(root, "config.json"),
        CredentialPath: Path.Combine(root, "credential.bin"));

    public void Dispose()
    {
        if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
    }

    private void WriteFlags(string json)
    {
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, FeatureFlags.FileName), json);
    }

    // --- the default ------------------------------------------------------

    /// <summary>
    /// A missing file must not be able to disable a service. The absence of a
    /// rollback is not a rollback.
    /// </summary>
    [Fact]
    public void WithNoFileEveryOperationIsOn()
    {
        var flags = FeatureFlags.Load(Paths());

        Assert.Empty(flags.Disabled);
        Assert.All(CadCapabilities.All, key => Assert.True(flags.IsEnabled(key)));
    }

    [Fact]
    public void TheManifestReportsTheBuiltInStatusWhenNothingIsDisabled()
    {
        var manifest = WorkerCapabilities.Manifest(flags: FeatureFlags.Load(Paths()));

        Assert.Equal("stable", manifest.Capabilities[CadCapabilities.SolidRectangularPrism].Status);
        // Everything POSTMVP-006 added is beta: one acceptance part is not the
        // ten positive and ten negative fixtures the roadmap asks for.
        Assert.Equal("beta", manifest.Capabilities[CadCapabilities.SketchArc].Status);
        Assert.Equal("beta", manifest.Capabilities[CadCapabilities.SketchPlaneFaceSelector].Status);
    }

    // --- turning something off --------------------------------------------

    [Fact]
    public void ADisabledOperationIsPublishedAsDisabledRatherThanDowngraded()
    {
        WriteFlags("""{"disabled":["sketch.arc"]}""");

        var manifest = WorkerCapabilities.Manifest(flags: FeatureFlags.Load(Paths()));

        // `disabled` is not a low rung on the maturity ladder; the API treats it
        // as "no", so the job stops being scheduled rather than being scheduled
        // reluctantly.
        Assert.Equal("disabled", manifest.Capabilities[CadCapabilities.SketchArc].Status);
        Assert.Equal("beta", manifest.Capabilities[CadCapabilities.SketchSlot].Status);
    }

    [Fact]
    public void ADisabledOperationIsRefusedByTheParserBeforeAnyCom()
    {
        WriteFlags("""{"disabled":["sketch.arc"]}""");
        var gate = FeatureFlags.Load(Paths()).Gate();

        using var document = JsonDocument.Parse(PlateWithArcProfile());
        var error = Assert.Throws<CadAdapterException>(
            () => CadIrBuildPlanParser.Parse(document.RootElement, gate));

        Assert.Equal("CAPABILITY_DISABLED", error.Code);
        Assert.Contains("sketch.arc", error.SafeMessage);
    }

    /// <summary>
    /// The point of per-operation granularity: turning off arcs must not turn
    /// off the plate.
    /// </summary>
    [Fact]
    public void TurningOffOneOperationLeavesTheRestBuildable()
    {
        WriteFlags("""{"disabled":["sketch.arc","sketch.plane.face_selector"]}""");
        var gate = FeatureFlags.Load(Paths()).Gate();

        using var document = JsonDocument.Parse(PlainPlate());
        var plan = CadIrBuildPlanParser.Parse(document.RootElement, gate);

        Assert.Single(plan.Features);
    }

    // --- the file is a promise --------------------------------------------

    /// <summary>
    /// An operator who wrote a flag file believes it is in force. Reading it as
    /// "no flags" would run an operation they had turned off.
    /// </summary>
    [Fact]
    public void AMalformedFileIsRefusedRatherThanTreatedAsAbsent()
    {
        WriteFlags("{ this is not json");

        var error = Assert.Throws<WorkerException>(() => FeatureFlags.Load(Paths()));
        Assert.Equal("FEATURE_FLAGS_UNREADABLE", error.Code);
    }

    /// <summary>
    /// A typo in a rollback switch is the worst possible moment to fail
    /// silently: the operation is still running and the operator thinks it is
    /// not.
    /// </summary>
    [Fact]
    public void AFlagNamingSomethingThisBuildDoesNotHaveIsRefused()
    {
        WriteFlags("""{"disabled":["sketch.arcs"]}""");

        var error = Assert.Throws<WorkerException>(() => FeatureFlags.Load(Paths()));
        Assert.Equal("FEATURE_FLAGS_UNKNOWN_CAPABILITY", error.Code);
        Assert.Contains("sketch.arcs", error.SafeMessage);
    }

    [Fact]
    public void DisablingAndEnablingRoundTripThroughTheFile()
    {
        var flags = FeatureFlags.Load(Paths());

        Assert.True(flags.Disable(CadCapabilities.SketchSlot));
        Assert.False(flags.Disable(CadCapabilities.SketchSlot));
        flags.Save(Paths());
        Assert.Equal([CadCapabilities.SketchSlot], FeatureFlags.Load(Paths()).Disabled);

        Assert.True(flags.Enable(CadCapabilities.SketchSlot));
        flags.Save(Paths());
        Assert.Empty(FeatureFlags.Load(Paths()).Disabled);
    }

    [Fact]
    public void TurningOffSomethingUnknownIsRefusedRatherThanRecorded()
    {
        var flags = FeatureFlags.Load(Paths());

        Assert.Equal(
            "FEATURE_FLAGS_UNKNOWN_CAPABILITY",
            Assert.Throws<WorkerException>(() => flags.Disable("solid.revolve")).Code);
    }

    // --- the manifest and the gate cannot drift ---------------------------

    /// <summary>
    /// Every key the adapter can refuse on must be a key the manifest declares,
    /// or an operation could be turned off without the API ever hearing about
    /// it — a rollback that stops the build but not the scheduling.
    /// </summary>
    [Fact]
    public void EveryCapabilityTheAdapterKnowsIsDeclaredInTheManifest()
    {
        var declared = WorkerCapabilities.Manifest().Capabilities.Keys.ToHashSet(StringComparer.Ordinal);

        Assert.Equal(CadCapabilities.All.Order(), declared.Order());
    }

    // --- fixtures ---------------------------------------------------------

    private const string Tail =
        @"""expectations"":[" +
        @"{""id"":""expect.bounds"",""type"":""bounding_box"",""size_mm"":{""x"":40,""y"":20,""z"":10},""tolerance_mm"":0.05}," +
        @"{""id"":""expect.bodies"",""type"":""body_count"",""value"":1}]," +
        @"""metadata"":{""generator"":""test"",""generator_version"":""1.0""}}";

    private const string Head =
        @"{""schema"":""cad-ai/cad-ir"",""schema_version"":""1.3""," +
        @"""document"":{""units"":""mm""}," +
        @"""parameters"":[{""id"":""param.depth"",""type"":""length"",""unit"":""mm"",""value"":10}],";

    private static string PlainPlate() =>
        Head +
        @"""features"":[{""id"":""feature.base"",""type"":""solid.extrude"",""depends_on"":[]," +
        @"""produces"":[{""id"":""body.main"",""kind"":""solid_body""}]," +
        @"""inputs"":{""direction"":""+Z"",""distance"":{""parameter"":""param.depth""}," +
        @"""sketch"":{""id"":""sketch.base"",""plane"":{""on"":""base"",""plane"":""XY""}," +
        @"""outer"":{""type"":""rectangle"",""center"":[0,0],""width"":40,""height"":20}," +
        @"""inner"":[],""construction"":[]}}}]," + Tail;

    private static string PlateWithArcProfile() =>
        Head +
        @"""features"":[{""id"":""feature.base"",""type"":""solid.extrude"",""depends_on"":[]," +
        @"""produces"":[{""id"":""body.main"",""kind"":""solid_body""}]," +
        @"""inputs"":{""direction"":""+Z"",""distance"":{""parameter"":""param.depth""}," +
        @"""sketch"":{""id"":""sketch.base"",""plane"":{""on"":""base"",""plane"":""XY""}," +
        @"""outer"":{""type"":""path"",""segments"":[" +
        @"{""type"":""line"",""start"":[-10,5],""end"":[10,5]}," +
        @"{""type"":""arc"",""start"":[10,5],""end"":[10,-5],""center"":[10,0],""sweep"":""cw""}," +
        @"{""type"":""line"",""start"":[10,-5],""end"":[-10,-5]}," +
        @"{""type"":""arc"",""start"":[-10,-5],""end"":[-10,5],""center"":[-10,0],""sweep"":""cw""}]}," +
        @"""inner"":[],""construction"":[]}}}]," + Tail;
}
