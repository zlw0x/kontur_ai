using CadAi.CadEngine;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CadAi.LocalWorker;

public sealed class WorkerException(string code, string safeMessage, int exitCode = 1) : Exception(safeMessage)
{
    public string Code { get; } = code;
    public string SafeMessage { get; } = safeMessage;
    public int ExitCode { get; } = exitCode;
}

public sealed record WorkerPaths(string StateRoot, string WorkspaceRoot, string ConfigPath, string CredentialPath)
{
    public static WorkerPaths CreateDefault()
    {
        var stateRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CadAiWorker");
        return new(stateRoot, Path.Combine(stateRoot, "jobs"), Path.Combine(stateRoot, "worker.json"), Path.Combine(stateRoot, "credential.dpapi"));
    }
}

/// <summary>Which CAD engine this worker builds with, and how to reach it.</summary>
/// <remarks>
/// Configuration, unlike the engine's identity, is a deployment concern: the
/// image tag, whether a developer machine runs the interpreter directly, which
/// container runtime is installed. What it never says is what to <em>pass</em>
/// the engine — the command line is built from a fixed vocabulary in the
/// launcher, and the only variable in it is a job directory this worker chose.
///
/// There is one engine, so there is no longer a setting that names it
/// (ENGINE-MIG-008). What is left is how to reach it: `container` is the mode with
/// the isolation ADR-023 asks for and is the default, and `process` runs the same
/// entry point through a local interpreter for a developer machine.
/// </remarks>
public sealed record CadEngineConfig(
    string Runtime = "container",
    string ContainerCommand = "docker",
    string Image = "cad-ai/cad-worker:latest",
    string PythonCommand = "python",
    string? WorkingDirectory = null,
    int BuildTimeoutMinutes = 15);

public sealed record WorkerConfig(
    string ServerUrl,
    string WorkerId,
    string WorkerName,
    int PollSeconds = 5,
    int LeaseSeconds = 60,
    // Optional so a worker enrolled before this setting existed keeps working:
    // an absent section means the defaults, which is a container.
    CadEngineConfig? CadEngine = null);

public sealed class WorkerConfigStore(WorkerPaths paths)
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    public WorkerConfig? Load() => File.Exists(paths.ConfigPath)
        ? JsonSerializer.Deserialize<WorkerConfig>(File.ReadAllText(paths.ConfigPath, Encoding.UTF8))
        : null;

    public void Save(WorkerConfig config)
    {
        Directory.CreateDirectory(paths.StateRoot);
        var temp = paths.ConfigPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(config, JsonOptions), new UTF8Encoding(false));
        File.Move(temp, paths.ConfigPath, true);
    }
}

/// <summary>
/// Where the worker's credential is kept.
/// </summary>
/// <remarks>
/// One interface and two implementations because the worker stopped being a
/// Windows program (ENGINE-MIG-008) and DPAPI is a Windows facility. Windows keeps
/// the behaviour it had; everywhere else the credential is a file only its owner
/// can read.
///
/// Chosen by the platform rather than configured. A setting here would let a
/// deployment ask for the weaker option on a machine that supports the stronger
/// one, and nobody choosing that would be doing it deliberately.
/// </remarks>
public interface ICredentialStore
{
    bool Exists { get; }

    void Save(string credential);

    string Load();

    void Delete();
}

public static class CredentialStore
{
    public static ICredentialStore CreateDefault(WorkerPaths paths) =>
        OperatingSystem.IsWindows()
            ? new DpapiCredentialStore(paths)
            : new OwnerOnlyFileCredentialStore(paths);
}

/// <summary>The credential, encrypted to the current user by Windows.</summary>
[System.Runtime.Versioning.SupportedOSPlatform("windows")]
public sealed class DpapiCredentialStore(WorkerPaths paths) : ICredentialStore
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("cad-ai-worker-v1");
    public bool Exists => File.Exists(paths.CredentialPath);

    public void Save(string credential)
    {
        Directory.CreateDirectory(paths.StateRoot);
        var encrypted = ProtectedData.Protect(Encoding.UTF8.GetBytes(credential), Entropy, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(paths.CredentialPath, encrypted);
    }

    public string Load()
    {
        if (!Exists) throw new WorkerException("AUTH_REQUIRED", "Worker enrollment is required.", 3);
        var decrypted = ProtectedData.Unprotect(File.ReadAllBytes(paths.CredentialPath), Entropy, DataProtectionScope.CurrentUser);
        return Encoding.UTF8.GetString(decrypted);
    }

    public void Delete()
    {
        if (Exists) File.Delete(paths.CredentialPath);
    }
}

/// <summary>
/// The credential in a file no other user can read.
/// </summary>
/// <remarks>
/// What a Unix daemon does with a bearer token, and stated plainly rather than
/// dressed up: this is *not* encryption. It is the same protection the worker's
/// job directories and its Codex session already have — the file mode, and the
/// fact that the account owning it is the account the credential belongs to.
/// Encrypting at rest with a key stored beside the ciphertext would look stronger
/// and be the same thing.
///
/// The mode is set before the secret is written, not after. A file created
/// world-readable and then narrowed is readable for as long as that takes.
/// </remarks>
public sealed class OwnerOnlyFileCredentialStore(WorkerPaths paths) : ICredentialStore
{
    public bool Exists => File.Exists(paths.CredentialPath);

    public void Save(string credential)
    {
        Directory.CreateDirectory(paths.StateRoot);
        if (!OperatingSystem.IsWindows())
            File.SetUnixFileMode(paths.StateRoot, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);

        var temp = paths.CredentialPath + ".tmp";
        using (var stream = new FileStream(
                   temp, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            if (!OperatingSystem.IsWindows())
                File.SetUnixFileMode(temp, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            stream.Write(Encoding.UTF8.GetBytes(credential));
        }
        File.Move(temp, paths.CredentialPath, true);
    }

    public string Load()
    {
        if (!Exists) throw new WorkerException("AUTH_REQUIRED", "Worker enrollment is required.", 3);
        return File.ReadAllText(paths.CredentialPath, Encoding.UTF8);
    }

    public void Delete()
    {
        if (Exists) File.Delete(paths.CredentialPath);
    }
}

public static class EnrollmentCommand
{
    public static async Task<int> RunAsync(string[] args, WorkerConfigStore configs, ICredentialStore credentials)
    {
        var server = Argument(args, "--server") ?? throw new WorkerException("CONFIG_INVALID", "--server is required.", 2);
        var token = Argument(args, "--token") ?? throw new WorkerException("CONFIG_INVALID", "--token is required.", 2);
        if (!Uri.TryCreate(server, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttps && !IsLoopback(uri)))
            throw new WorkerException("CONFIG_INVALID", "Server URL must use HTTPS, except localhost.", 2);

        using var client = new HttpClient { BaseAddress = uri, Timeout = TimeSpan.FromSeconds(30) };
        var response = await client.PostAsJsonAsync("/api/v1/workers/register", new
        {
            enrollment_token = token, worker_name = Environment.MachineName, app_version = WorkerCapabilities.WorkerVersion
        });
        if (!response.IsSuccessStatusCode) throw new WorkerException("ENROLLMENT_REJECTED", "Worker enrollment was rejected.", 4);
        var result = await response.Content.ReadFromJsonAsync<EnrollmentResponse>()
            ?? throw new WorkerException("PROTOCOL_INVALID", "Enrollment response was invalid.");
        credentials.Save(result.credential);
        configs.Save(new WorkerConfig(server.TrimEnd('/'), result.worker_id, Environment.MachineName));
        Console.WriteLine(JsonSerializer.Serialize(new { status = "ENROLLED", worker_id = result.worker_id }));
        return 0;
    }

    private static string? Argument(string[] args, string name)
    {
        var index = Array.IndexOf(args, name);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
    }

    private static bool IsLoopback(Uri uri) =>
        uri.IsLoopback ||
        (System.Net.IPAddress.TryParse(uri.Host, out var address) &&
         System.Net.IPAddress.IsLoopback(address));

    private sealed record EnrollmentResponse(string worker_id, string credential);
}

public static class WorkerDoctor
{
    public static Task<int> RunAsync(WorkerConfigStore configs, ICredentialStore credentials, WorkerPaths paths)
    {
        Directory.CreateDirectory(paths.WorkspaceRoot);
        var writeProbe = Path.Combine(paths.WorkspaceRoot, $".probe-{Guid.NewGuid():N}");
        File.WriteAllText(writeProbe, "ok");
        File.Delete(writeProbe);
        var config = configs.Load();
        var status = config is not null && credentials.Exists ? "READY" : "AUTH_REQUIRED";
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            status, worker = WorkerCapabilities.WorkerVersion, mode = "fake", credential = credentials.Exists ? "protected" : "missing",
            workspace = "writable", engine = "not-started", codex = "not-probed"
        }));
        return Task.FromResult(status == "READY" ? 0 : 3);
    }
}
