using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CadAi.CodexRunner;

public sealed record CodexStageRequest(
    string Workspace,
    string OutputSchemaPath,
    string OutputPath,
    string Prompt,
    IReadOnlyList<string>? Images = null,
    string? Model = null,
    string ReasoningEffort = "medium",
    TimeSpan? Timeout = null);

public sealed record CodexUsage(
    long InputTokens,
    long CachedInputTokens,
    long OutputTokens,
    long ReasoningOutputTokens);

/// <summary>Resources one Codex process consumed, as far as the OS reports.</summary>
public sealed record CodexProcessMetrics(
    long? CpuUserMs,
    long? CpuSystemMs,
    long? PeakMemoryBytes,
    int? ExitCode);

public sealed record CodexStageResult(
    string? ThreadId,
    CodexUsage? Usage,
    string OutputPath,
    string OutputSha256,
    string EventsPath,
    CodexUsageResolution? UsageReading = null,
    CodexProcessMetrics? Process = null,
    string? CliVersion = null,
    string? Model = null,
    string? ReasoningEffort = null);

public interface ICodexRunner
{
    Task<CodexStageResult> RunAsync(
        CodexStageRequest request,
        CancellationToken cancellationToken = default);
}

public sealed class CodexRunnerException(string code, string safeMessage, Exception? inner = null)
    : Exception(safeMessage, inner)
{
    public string Code { get; } = code;
    public string SafeMessage { get; } = safeMessage;
}

public sealed class LocalCodexRunner : ICodexRunner
{
    private const long MaxEventsBytes = 20 * 1024 * 1024;
    private const int MaxStderrChars = 1_000_000;
    private static readonly Regex ModelPattern = new(
        "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$",
        RegexOptions.CultureInvariant);
    private readonly string executable;
    private readonly CodexUsageParserRegistry usageRegistry;
    private string? cliVersion;

    public LocalCodexRunner(
        string? executablePath = null,
        CodexUsageParserRegistry? usageRegistry = null)
    {
        executable = executablePath ?? DiscoverExecutable();
        this.usageRegistry = usageRegistry ?? new CodexUsageParserRegistry();
    }

    /// <summary>
    /// Version string of the installed CLI, or null when it cannot be read.
    /// Cached: it cannot change while this process runs, and every stage would
    /// otherwise pay for another process launch.
    /// </summary>
    public string? CliVersion => cliVersion ??= ReadCliVersion();

    private string? ReadCliVersion()
    {
        try
        {
            using var probe = Process.Start(new ProcessStartInfo(executable)
            {
                ArgumentList = { "--version" },
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            });
            if (probe is null) return null;
            var text = probe.StandardOutput.ReadToEnd().Trim();
            probe.WaitForExit(10_000);
            return probe.ExitCode == 0 && text.Length is > 0 and <= 200 ? text : null;
        }
        catch
        {
            // The version is diagnostic metadata. Failing to read it must not
            // fail the stage that is about to run.
            return null;
        }
    }

    private static CodexProcessMetrics ReadProcessMetrics(Process process)
    {
        // These throw once the OS has released the process. An unavailable
        // metric is recorded as null rather than as a fabricated zero.
        long? user = null, system = null, peak = null;
        int? exitCode = null;
        try { user = (long)process.UserProcessorTime.TotalMilliseconds; } catch { }
        try { system = (long)process.PrivilegedProcessorTime.TotalMilliseconds; } catch { }
        try { peak = process.PeakWorkingSet64; } catch { }
        try { exitCode = process.ExitCode; } catch { }
        return new CodexProcessMetrics(user, system, peak, exitCode);
    }

    public async Task<CodexStageResult> RunAsync(
        CodexStageRequest request,
        CancellationToken cancellationToken = default)
    {
        var workspace = Path.GetFullPath(request.Workspace);
        if (!Directory.Exists(workspace))
            throw Failure("CODEX_WORKSPACE_INVALID", "Codex stage workspace does not exist.");
        var schema = RequireContainedFile(workspace, request.OutputSchemaPath, "output schema");
        var output = RequireContainedPath(workspace, request.OutputPath, "output path");
        if (request.Prompt.Length is < 1 or > 20_000)
            throw Failure("CODEX_PROMPT_INVALID", "Codex stage prompt length is invalid.");
        if (request.Model is not null && !ModelPattern.IsMatch(request.Model))
            throw Failure("CODEX_MODEL_INVALID", "Configured Codex model identifier is invalid.");
        if (request.ReasoningEffort is not ("low" or "medium" or "high" or "xhigh"))
            throw Failure("CODEX_CONFIG_INVALID", "Configured reasoning effort is invalid.");

        var images = (request.Images ?? []).Select(path =>
        {
            var image = RequireContainedFile(workspace, path, "image");
            if (Path.GetExtension(image).ToLowerInvariant() is not (".png" or ".jpg" or ".jpeg"))
                throw Failure("CODEX_INPUT_INVALID", "Codex image must be PNG or JPEG.");
            return image;
        }).ToArray();
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var logs = Path.Combine(workspace, "logs");
        Directory.CreateDirectory(logs);
        var eventsPath = Path.Combine(logs, "codex-events.jsonl");
        var stderrPath = Path.Combine(logs, "codex-stderr.log");

        var start = new ProcessStartInfo(executable)
        {
            WorkingDirectory = workspace,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        AddArguments(start, request, workspace, schema, output, images);
        // Runtime AI must use persisted local ChatGPT auth. API/access-token
        // environment overrides are deliberately removed from the child.
        start.Environment.Remove("OPENAI_API_KEY");
        start.Environment.Remove("CODEX_API_KEY");
        start.Environment.Remove("CODEX_ACCESS_TOKEN");

        using var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        try
        {
            if (!process.Start())
                throw Failure("CODEX_START_FAILED", "Codex CLI did not start.");
        }
        catch (Exception error) when (error is not CodexRunnerException)
        {
            throw Failure("CODEX_START_FAILED", "Codex CLI could not be started.", error);
        }

        var parser = new CodexEventParser();
        var policyViolation = false;
        var stdoutTask = CaptureEventsAsync(
            process.StandardOutput,
            eventsPath,
            parser,
            () =>
            {
                policyViolation = true;
                TryKill(process);
            },
            cancellationToken);
        var stderrTask = CaptureStderrAsync(process.StandardError, stderrPath, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(request.Timeout ?? TimeSpan.FromMinutes(10));
        try
        {
            await process.WaitForExitAsync(timeout.Token);
            await Task.WhenAll(stdoutTask, stderrTask);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            TryKill(process);
            throw Failure("CODEX_TIMEOUT", "Codex stage exceeded its runtime limit.");
        }
        catch (OperationCanceledException)
        {
            TryKill(process);
            throw;
        }

        if (policyViolation || parser.ToolUseDetected)
            throw Failure("CODEX_POLICY_VIOLATION", "Runtime Codex attempted to use a tool.");
        if (parser.Failed || process.ExitCode != 0)
            throw Failure(MapExit(parser), "Codex stage did not complete successfully.");
        if (!File.Exists(output))
            throw Failure("CODEX_OUTPUT_MISSING", "Codex did not create the structured output.");
        var outputInfo = new FileInfo(output);
        if (outputInfo.Length is <= 0 or > 5_000_000)
            throw Failure("CODEX_OUTPUT_INVALID", "Codex output size is invalid.");
        try
        {
            using var parsed = JsonDocument.Parse(
                await File.ReadAllBytesAsync(output, cancellationToken),
                new JsonDocumentOptions { MaxDepth = 64 });
            if (parsed.RootElement.ValueKind != JsonValueKind.Object)
                throw new JsonException();
        }
        catch (JsonException error)
        {
            throw Failure("CODEX_OUTPUT_INVALID", "Codex output is not a JSON object.", error);
        }
        await using var outputStream = File.OpenRead(output);
        var checksum = Convert.ToHexString(await SHA256.HashDataAsync(outputStream, cancellationToken));
        return new CodexStageResult(
            parser.ThreadId,
            parser.Usage,
            output,
            checksum,
            eventsPath,
            usageRegistry.Read(CliVersion, parser.UsageCandidates),
            ReadProcessMetrics(process),
            CliVersion,
            request.Model,
            request.ReasoningEffort);
    }

    private static void AddArguments(
        ProcessStartInfo start,
        CodexStageRequest request,
        string workspace,
        string schema,
        string output,
        IReadOnlyList<string> images)
    {
        start.ArgumentList.Add("--ask-for-approval");
        start.ArgumentList.Add("never");
        start.ArgumentList.Add("exec");
        start.ArgumentList.Add("--ignore-user-config");
        start.ArgumentList.Add("--ephemeral");
        start.ArgumentList.Add("--json");
        start.ArgumentList.Add("--color");
        start.ArgumentList.Add("never");
        start.ArgumentList.Add("--skip-git-repo-check");
        start.ArgumentList.Add("--cd");
        start.ArgumentList.Add(workspace);
        start.ArgumentList.Add("--output-schema");
        start.ArgumentList.Add(schema);
        start.ArgumentList.Add("--output-last-message");
        start.ArgumentList.Add(output);
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add("default_permissions=\"cad-runtime\"");
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add(
            "permissions.cad-runtime.filesystem={ \":minimal\" = \"read\", \":workspace_roots\" = { \".\" = \"read\" } }");
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add("web_search=\"disabled\"");
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add("shell_environment_policy.inherit=\"none\"");
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add($"model_reasoning_effort=\"{request.ReasoningEffort}\"");
        if (request.Model is not null)
        {
            start.ArgumentList.Add("--model");
            start.ArgumentList.Add(request.Model);
        }
        // --image accepts one or more values and would otherwise consume the
        // positional prompt. Put the prompt before the variadic option.
        start.ArgumentList.Add(request.Prompt);
        foreach (var image in images)
        {
            start.ArgumentList.Add("--image");
            start.ArgumentList.Add(image);
        }
    }

    private static async Task CaptureEventsAsync(
        StreamReader reader,
        string path,
        CodexEventParser parser,
        Action onToolUse,
        CancellationToken cancellationToken)
    {
        await using var output = new StreamWriter(path, append: false, new UTF8Encoding(false));
        long bytes = 0;
        while (await reader.ReadLineAsync(cancellationToken) is { } line)
        {
            bytes += Encoding.UTF8.GetByteCount(line) + 1;
            if (bytes > MaxEventsBytes)
                throw Failure("CODEX_OUTPUT_LIMIT", "Codex event stream exceeded its size limit.");
            await output.WriteLineAsync(line.AsMemory(), cancellationToken);
            parser.Accept(line);
            if (parser.ToolUseDetected)
            {
                onToolUse();
                return;
            }
        }
    }

    private static async Task CaptureStderrAsync(
        StreamReader reader,
        string path,
        CancellationToken cancellationToken)
    {
        var text = await reader.ReadToEndAsync(cancellationToken);
        if (text.Length > MaxStderrChars) text = text[..MaxStderrChars];
        await File.WriteAllTextAsync(path, text, new UTF8Encoding(false), cancellationToken);
    }

    private static string RequireContainedFile(string root, string path, string label)
    {
        var result = RequireContainedPath(root, path, label);
        if (!File.Exists(result))
            throw Failure("CODEX_INPUT_INVALID", $"Codex {label} does not exist.");
        return result;
    }

    private static string RequireContainedPath(string root, string path, string label)
    {
        var result = Path.GetFullPath(path);
        if (!result.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw Failure("CODEX_INPUT_INVALID", $"Codex {label} must stay inside the stage workspace.");
        return result;
    }

    private static string DiscoverExecutable()
    {
        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "OpenAI", "Codex", "bin", "codex.exe");
        if (File.Exists(local)) return local;
        throw Failure("CODEX_NOT_INSTALLED", "Standalone Codex CLI was not found.");
    }

    private static string MapExit(CodexEventParser parser) =>
        parser.ErrorText.Contains("rate", StringComparison.OrdinalIgnoreCase) ||
        parser.ErrorText.Contains("limit", StringComparison.OrdinalIgnoreCase)
            ? "CODEX_CAPACITY_LIMIT"
            : "CODEX_RUN_FAILED";

    private static void TryKill(Process process)
    {
        try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { }
    }

    private static CodexRunnerException Failure(string code, string message, Exception? inner = null) =>
        new(code, message, inner);
}

public sealed class CodexEventParser
{
    private const int TailLines = 20;
    private readonly List<string> completions = [];
    private readonly Queue<string> tail = new();

    public string? ThreadId { get; private set; }
    public CodexUsage? Usage { get; private set; }
    public bool Failed { get; private set; }
    public bool ToolUseDetected { get; private set; }
    public string ErrorText { get; private set; } = "";

    /// <summary>
    /// Lines a usage parser may inspect: every turn completion plus a bounded
    /// tail. The full event stream can reach megabytes and must not be held in
    /// memory just to read a token count from its end.
    /// </summary>
    public IReadOnlyList<string> UsageCandidates => [.. completions, .. tail];

    public void Accept(string line)
    {
        tail.Enqueue(line);
        if (tail.Count > TailLines) tail.Dequeue();
        JsonDocument document;
        try { document = JsonDocument.Parse(line); }
        catch (JsonException error)
        {
            throw new CodexRunnerException("CODEX_PROTOCOL_INVALID", "Codex emitted invalid JSONL.", error);
        }
        using (document)
        {
            var root = document.RootElement;
            var type = root.TryGetProperty("type", out var typeValue) ? typeValue.GetString() : null;
            if (type == "thread.started" && root.TryGetProperty("thread_id", out var thread))
                ThreadId = thread.GetString();
            if (type is "turn.failed" or "error")
            {
                Failed = true;
                ErrorText += line;
            }
            if (type == "turn.completed")
                completions.Add(line);
            if (type == "turn.completed" && root.TryGetProperty("usage", out var usage))
            {
                Usage = new CodexUsage(
                    Number(usage, "input_tokens"),
                    Number(usage, "cached_input_tokens"),
                    Number(usage, "output_tokens"),
                    Number(usage, "reasoning_output_tokens"));
            }
            if (type is "item.started" or "item.completed" &&
                root.TryGetProperty("item", out var item) &&
                item.TryGetProperty("type", out var itemType) &&
                itemType.GetString() is "command_execution" or "file_change" or "mcp_tool_call" or "web_search")
                ToolUseDetected = true;
        }
    }

    // TryGetInt64 throws when the element is not a number, so the kind is
    // checked first: a CLI emitting "many" instead of 12 must not fail a job.
    private static long Number(JsonElement owner, string name) =>
        owner.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Number &&
        value.TryGetInt64(out var number)
            ? number
            : 0;
}
