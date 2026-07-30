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

public sealed record WorkerConfig(string ServerUrl, string WorkerId, string WorkerName, int PollSeconds = 5, int LeaseSeconds = 60);

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

public sealed class DpapiCredentialStore(WorkerPaths paths)
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

public static class EnrollmentCommand
{
    public static async Task<int> RunAsync(string[] args, WorkerConfigStore configs, DpapiCredentialStore credentials)
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
    public static Task<int> RunAsync(WorkerConfigStore configs, DpapiCredentialStore credentials, WorkerPaths paths)
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
            workspace = "writable", kompas = "not-probed", codex = "not-probed"
        }));
        return Task.FromResult(status == "READY" ? 0 : 3);
    }
}
