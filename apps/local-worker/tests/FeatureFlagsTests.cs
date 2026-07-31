using CadAi.CadEngine;
using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// A rollback that does not actually stop the operation is worse than none: the
/// operator believes the bad geometry has stopped being produced.
/// </summary>
/// <remarks>
/// These are about the file and what it means to this worker. The other half of
/// the switch — the manifest the API schedules from and the gate the build refuses
/// at — belongs to the engine now (ENGINE-MIG-008) and is tested where it lives:
/// `test_capabilities.py` for the vocabulary and the gate,
/// `DocumentEngineJobTests` for the flags reaching a job, and `RealEngineTests`
/// for a key becoming an argument the real engine acts on.
/// </remarks>
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

    /// <summary>
    /// A missing file must not be able to disable a service. The absence of a
    /// rollback is not a rollback.
    /// </summary>
    [Fact]
    public void WithNoFileEveryOperationIsOn()
    {
        var flags = FeatureFlags.Load(Paths());

        Assert.Empty(flags.Disabled);
        Assert.True(flags.IsEnabled("sketch.arc"));
        Assert.True(flags.IsEnabled("anything.at.all"));
    }

    [Fact]
    public void ADisabledOperationIsPublishedAsDisabledRatherThanDowngraded()
    {
        // `disabled` is not a low rung on the maturity ladder. The API reads it
        // as "no" outright, so the operation stops being scheduled instead of
        // being scheduled reluctantly.
        WriteFlags("""{"disabled":["sketch.arc"]}""");
        var flags = FeatureFlags.Load(Paths());

        Assert.Equal("disabled", flags.EffectiveStatus("sketch.arc", "beta"));
        Assert.Equal("beta", flags.EffectiveStatus("sketch.slot", "beta"));
    }

    /// <summary>
    /// An operator who wrote a file believes it is in force. Quietly running an
    /// operation they turned off is the one outcome this must never produce.
    /// </summary>
    [Fact]
    public void AMalformedFileIsRefusedRatherThanTreatedAsAbsent()
    {
        WriteFlags("{ not json");

        var error = Assert.Throws<WorkerException>(() => FeatureFlags.Load(Paths()));

        Assert.Equal("FEATURE_FLAGS_UNREADABLE", error.Code);
    }

    /// <summary>
    /// The half of a typo a file can be judged on without an engine. `Sketch Arc`
    /// is not a capability key in any engine, so it is refused here; a well-formed
    /// key the engine does not declare is refused by the engine, loudly, before it
    /// does anything else.
    /// </summary>
    [Fact]
    public void AKeyThatIsNotEvenShapedLikeOneIsRefused()
    {
        WriteFlags("""{"disabled":["Sketch Arc"]}""");

        var error = Assert.Throws<WorkerException>(() => FeatureFlags.Load(Paths()));

        Assert.Equal("FEATURE_FLAGS_UNKNOWN_CAPABILITY", error.Code);
        Assert.Contains("Sketch Arc", error.SafeMessage);
    }

    [Fact]
    public void DisablingAndEnablingRoundTripThroughTheFile()
    {
        var flags = FeatureFlags.Load(Paths());

        Assert.True(flags.Disable("sketch.slot"));
        Assert.False(flags.Disable("sketch.slot"));
        flags.Save(Paths());
        Assert.Equal(["sketch.slot"], FeatureFlags.Load(Paths()).Disabled);

        Assert.True(flags.Enable("sketch.slot"));
        flags.Save(Paths());
        Assert.Empty(FeatureFlags.Load(Paths()).Disabled);
    }

    [Fact]
    public void TurningOffSomethingThatCannotBeAKeyIsRefusedRatherThanRecorded()
    {
        var flags = FeatureFlags.Load(Paths());

        var error = Assert.Throws<WorkerException>(() => flags.Disable("Sketch.Arc"));

        Assert.Equal("FEATURE_FLAGS_UNKNOWN_CAPABILITY", error.Code);
        Assert.Empty(flags.Disabled);
    }

    /// <summary>
    /// The fake engine declares no capability at all, so the API cannot schedule
    /// real work to a worker running it. A fake that advertised operations would
    /// be a fake that gets given a customer's order.
    /// </summary>
    [Fact]
    public async Task TheFakeEngineAdvertisesNothing()
    {
        var report = await new FakeDocumentEngine(WorkerCapabilities.CadIrVersion)
            .DescribeAsync([], CancellationToken.None);

        Assert.Empty(report.Capabilities);
        Assert.Equal("fake", report.Engine.EngineId);
        Assert.Equal(["FAKE_CAD"], report.Engine.Artifacts.Select(item => item.Kind));
    }
}
