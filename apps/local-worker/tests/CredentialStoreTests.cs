using CadAi.LocalWorker;
using Xunit;

namespace CadAi.LocalWorker.Tests;

/// <summary>
/// Where a worker's bearer token is kept, now that the worker is not a Windows
/// program (ENGINE-MIG-008).
/// </summary>
/// <remarks>
/// The store is chosen by the platform, not configured: a setting would let a
/// deployment ask for the weaker option on a machine that supports the stronger
/// one, and nobody choosing that would be doing it deliberately.
/// </remarks>
public sealed class CredentialStoreTests : IDisposable
{
    private readonly string root = Path.Combine(
        Path.GetTempPath(), $"cad-ai-cred-{Guid.NewGuid():N}");

    private WorkerPaths Paths() => new(
        StateRoot: root,
        WorkspaceRoot: Path.Combine(root, "work"),
        ConfigPath: Path.Combine(root, "worker.json"),
        CredentialPath: Path.Combine(root, "credential.bin"));

    public void Dispose()
    {
        if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
    }

    [Fact]
    public void ThePlatformDecidesWhichStoreIsUsed()
    {
        var store = CredentialStore.CreateDefault(Paths());
        if (OperatingSystem.IsWindows()) Assert.IsType<DpapiCredentialStore>(store);
        else Assert.IsType<OwnerOnlyFileCredentialStore>(store);
    }

    [Fact]
    public void ACredentialRoundTripsAndCanBeRevoked()
    {
        var store = CredentialStore.CreateDefault(Paths());
        Assert.False(store.Exists);

        store.Save("worker-token-ABC");
        Assert.True(store.Exists);
        Assert.Equal("worker-token-ABC", store.Load());

        store.Delete();
        Assert.False(store.Exists);
    }

    [Fact]
    public void AMissingCredentialIsAnEnrollmentProblemAndSaysSo()
    {
        var error = Assert.Throws<WorkerException>(() => CredentialStore.CreateDefault(Paths()).Load());

        Assert.Equal("AUTH_REQUIRED", error.Code);
        Assert.Equal(3, error.ExitCode);
    }

    /// <summary>
    /// The mode is set before the secret is written, so there is no window in
    /// which the file exists and anyone can read it.
    /// </summary>
    [Fact]
    public void OnUnixNobodyButTheOwnerCanReadIt()
    {
        if (OperatingSystem.IsWindows()) return;

        var paths = Paths();
        new OwnerOnlyFileCredentialStore(paths).Save("worker-token-ABC");

        Assert.Equal(
            UnixFileMode.UserRead | UnixFileMode.UserWrite,
            File.GetUnixFileMode(paths.CredentialPath));
        // The directory too: a readable directory with an unreadable file in it
        // still tells anyone who looks that a worker is enrolled here.
        Assert.Equal(
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute,
            File.GetUnixFileMode(paths.StateRoot));
    }

    [Fact]
    public void SavingTwiceReplacesRatherThanAppends()
    {
        var store = CredentialStore.CreateDefault(Paths());
        store.Save("first");
        store.Save("second");
        Assert.Equal("second", store.Load());
    }
}
