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
    TimeSpan? Timeout = null,
    CodexRoutingDecision? Routing = null,
    string? PromptBundleSha256 = null);

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
    string? ReasoningEffort = null,
    CodexRoutingDecision? Routing = null,
    CodexModelObservation? ModelObservation = null,
    string? ProvenanceSha256 = null);

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
        // A run with no model named takes whatever the CLI defaults to today,
        // which is external behaviour that can change under us and leaves the
        // run's cost unattributable. Refuse rather than inherit it.
        if (string.IsNullOrWhiteSpace(request.Model))
            throw Failure("CODEX_MODEL_UNSPECIFIED", "Codex stage did not name a model.");
        if (!ModelPattern.IsMatch(request.Model))
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

        var start = CreateStartInfo(executable, request, workspace, schema, output, images);

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

        // Close the child's stdin at once, before it can read a byte.
        //
        // `codex exec` appends whatever arrives on stdin to the prompt it was
        // given, and announces it: "Reading additional input from stdin...".
        // Inherited, that is the *parent's* stdin, and the parent is a worker
        // meant to run with nobody watching — under a service manager, a
        // supervisor, a CI runner. Two things follow, and both were observed
        // rather than reasoned about.
        //
        // If that stdin is a pipe nobody closes, the child waits on it for the
        // full ten-minute timeout and the stage fails having emitted no events
        // at all. On the outside that is indistinguishable from the model
        // failing — which is the third time in this project an environment
        // detail has worn the costume of the work.
        //
        // And if bytes do arrive, they are spliced into the prompt. Nothing
        // chose them, nothing validated them, and the whole design of this
        // service is that what reaches the model is assembled here. An open
        // inherited stdin is a way into the prompt that no one decided to open.
        //
        // EOF at once settles both: the child reads nothing and does not wait.
        try
        {
            process.StandardInput.Close();
        }
        catch (IOException)
        {
            // The child exited before the handle could be closed. Its output is
            // read below and will say so far more usefully than this would.
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
        var observation = CodexModelObservation.Compare(
            request.Model, parser.ObservedModel, request.ReasoningEffort, parser.ObservedReasoningEffort);
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
            request.ReasoningEffort,
            request.Routing,
            observation,
            request.Routing is null || request.PromptBundleSha256 is null
                ? null
                : CodexProvenance.Fingerprint(
                    checksum, request.PromptBundleSha256, request.Routing, CliVersion));
    }

    /// <summary>
    /// The exact argument list a stage will be launched with.
    /// </summary>
    /// <summary>
    /// Everything about how the Codex process is launched, in one place.
    /// </summary>
    /// <remarks>
    /// Separate from the launch for the same reason <see cref="BuildArguments"/>
    /// is: the decisions here are about what the child may reach, and they can
    /// be asserted without spending a real model call.
    ///
    /// Three of the four streams are settled here. The fourth — actually closing
    /// stdin — has to happen after the process exists, and is done at the call
    /// site with the reasoning beside it.
    /// </remarks>
    public static ProcessStartInfo CreateStartInfo(
        string executable,
        CodexStageRequest request,
        string workspace,
        string schema,
        string output,
        IReadOnlyList<string> images)
    {
        var start = new ProcessStartInfo(executable)
        {
            WorkingDirectory = workspace,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // Redirected so it can be closed the moment the process starts.
            // Inherited, the child reads the *parent's* stdin — see the comment
            // at the close for what that cost.
            RedirectStandardInput = true,
            CreateNoWindow = true,
        };
        foreach (var argument in BuildArguments(request, workspace, schema, output, images))
            start.ArgumentList.Add(argument);
        // Runtime AI must use persisted local ChatGPT auth. API/access-token
        // environment overrides are deliberately removed from the child.
        start.Environment.Remove("OPENAI_API_KEY");
        start.Environment.Remove("CODEX_API_KEY");
        start.Environment.Remove("CODEX_ACCESS_TOKEN");
        return start;
    }

    /// <remarks>
    /// Built separately from the process so it can be asserted directly. The
    /// guarantee that matters — that a run's model comes from the routing
    /// profile and not from the user's config.toml — is a property of these
    /// arguments, and testing it by launching the CLI would cost a real call.
    /// </remarks>
    public static IReadOnlyList<string> BuildArguments(
        CodexStageRequest request,
        string workspace,
        string schema,
        string output,
        IReadOnlyList<string> images)
    {
        var start = new ProcessStartInfo();
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
        // Always explicit. --ignore-user-config already detaches the run from
        // ~/.codex/config.toml; naming the model on the command line is the
        // highest-priority layer and the only one this service controls.
        start.ArgumentList.Add("--model");
        start.ArgumentList.Add(request.Model!);
        // --image accepts one or more values and would otherwise consume the
        // positional prompt. Put the prompt before the variadic option.
        start.ArgumentList.Add(request.Prompt);
        foreach (var image in images)
        {
            start.ArgumentList.Add("--image");
            start.ArgumentList.Add(image);
        }
        return start.ArgumentList;
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

    /// <summary>
    /// Model the CLI said it used, when it says so at all.
    /// </summary>
    /// <remarks>
    /// codex-cli 0.145.0 reports no model in any event, so this stays null
    /// today. The reader exists so that a CLI which starts reporting one is
    /// believed immediately rather than after someone notices.
    /// </remarks>
    public string? ObservedModel { get; private set; }

    public string? ObservedReasoningEffort { get; private set; }

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
            ObservedModel ??= Text(root, "model");
            ObservedReasoningEffort ??= Text(root, "reasoning_effort")
                ?? Text(root, "model_reasoning_effort");
            if (root.TryGetProperty("turn", out var turn) && turn.ValueKind == JsonValueKind.Object)
            {
                ObservedModel ??= Text(turn, "model");
                ObservedReasoningEffort ??= Text(turn, "reasoning_effort");
            }
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

    private static string? Text(JsonElement owner, string name) =>
        owner.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    // TryGetInt64 throws when the element is not a number, so the kind is
    // checked first: a CLI emitting "many" instead of 12 must not fail a job.
    private static long Number(JsonElement owner, string name) =>
        owner.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Number &&
        value.TryGetInt64(out var number)
            ? number
            : 0;
}
