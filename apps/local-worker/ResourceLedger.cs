using CadAi.CadEngine;
using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using CadAi.CodexRunner;

namespace CadAi.LocalWorker;

public enum ResourceEventType
{
    AI_RUN,
    PROCESS_RUN,
    CAD_SESSION,
    CAD_OPERATION,
    CAD_REBUILD,
    REPAIR_ITERATION,
    EXPORT,
    VALIDATION,
    PREVIEW_RENDER,
    TRANSFER,
    HUMAN_REVIEW,
    WARNING
}

public enum ResourceStage
{
    IMAGE_PREPROCESSING,
    DRAWING_ANALYSIS,
    CLARIFICATION,
    CAD_PLANNING,
    CAD_IR_COMPILATION,
    SCHEMA_VALIDATION,
    SEMANTIC_VALIDATION,
    KOMPAS_STARTUP,
    DOCUMENT_BUILD,
    FEATURE_BUILD,
    SELECTOR_RESOLUTION,
    REBUILD,
    EXPORT,
    GEOMETRY_VALIDATION,
    PREVIEW,
    ARTIFACT_UPLOAD,
    CLEANUP,
    HUMAN_REVIEW
}

public enum AgentRole
{
    DRAWING_EXTRACTION,
    GEOMETRY_REASONING,
    CLARIFICATION,
    CAD_PLANNING,
    CAD_IR_COMPILATION,
    REPAIR,
    FINAL_AUDIT
}

public sealed record AiUsagePayload(
    [property: JsonPropertyName("requested_model")] string? RequestedModel,
    [property: JsonPropertyName("observed_model")] string? ObservedModel,
    [property: JsonPropertyName("requested_reasoning_effort")] string? RequestedReasoningEffort,
    [property: JsonPropertyName("observed_reasoning_effort")] string? ObservedReasoningEffort,
    [property: JsonPropertyName("model_observation_status")] string ModelObservationStatus,
    [property: JsonPropertyName("routing_profile_version")] string? RoutingProfileVersion,
    [property: JsonPropertyName("routing_rule_id")] string? RoutingRuleId,
    [property: JsonPropertyName("service_tier")] string ServiceTier,
    [property: JsonPropertyName("cli_version")] string? CliVersion,
    [property: JsonPropertyName("prompt_version")] string? PromptVersion,
    [property: JsonPropertyName("prompt_bundle_sha256")] string? PromptBundleSha256,
    [property: JsonPropertyName("provenance_sha256")] string? ProvenanceSha256,
    [property: JsonPropertyName("thread_id")] string? ThreadId,
    [property: JsonPropertyName("token_source")] string TokenSource,
    [property: JsonPropertyName("input_tokens")] long? InputTokens,
    [property: JsonPropertyName("cached_input_tokens")] long? CachedInputTokens,
    [property: JsonPropertyName("output_tokens")] long? OutputTokens,
    [property: JsonPropertyName("reasoning_tokens")] long? ReasoningTokens,
    [property: JsonPropertyName("total_tokens")] long? TotalTokens);

public sealed record ProcessUsagePayload(
    [property: JsonPropertyName("cpu_user_ms")] long? CpuUserMs,
    [property: JsonPropertyName("cpu_system_ms")] long? CpuSystemMs,
    [property: JsonPropertyName("peak_memory_bytes")] long? PeakMemoryBytes,
    [property: JsonPropertyName("bytes_read")] long? BytesRead,
    [property: JsonPropertyName("bytes_written")] long? BytesWritten,
    [property: JsonPropertyName("exit_code")] int? ExitCode,
    [property: JsonPropertyName("termination_reason")] string? TerminationReason,
    [property: JsonPropertyName("retry_number")] int RetryNumber);

public sealed record CadUsagePayload(
    [property: JsonPropertyName("operation_code")] string? OperationCode,
    [property: JsonPropertyName("operation_count")] int? OperationCount,
    [property: JsonPropertyName("failed_feature_count")] int? FailedFeatureCount,
    [property: JsonPropertyName("session_reuse_count")] int? SessionReuseCount,
    [property: JsonPropertyName("forced_termination")] bool ForcedTermination,
    [property: JsonPropertyName("result_bytes")] long? ResultBytes);

public sealed record ResourceEventPayload(
    [property: JsonPropertyName("event_key")] string EventKey,
    [property: JsonPropertyName("event_type")] string EventType,
    [property: JsonPropertyName("stage")] string Stage,
    [property: JsonPropertyName("attempt_no")] int AttemptNo,
    [property: JsonPropertyName("agent_role")] string? AgentRole,
    [property: JsonPropertyName("started_at")] DateTimeOffset StartedAt,
    [property: JsonPropertyName("finished_at")] DateTimeOffset? FinishedAt,
    [property: JsonPropertyName("wall_ms")] long? WallMs,
    [property: JsonPropertyName("success")] bool Success,
    [property: JsonPropertyName("failure_code")] string? FailureCode,
    [property: JsonPropertyName("ai")] AiUsagePayload? Ai,
    [property: JsonPropertyName("process")] ProcessUsagePayload? Process,
    [property: JsonPropertyName("cad")] CadUsagePayload? Cad,
    [property: JsonPropertyName("metadata")] Dictionary<string, string> Metadata);

/// <summary>
/// Collects what a job consumed on this machine.
/// </summary>
/// <remarks>
/// The worker measures; it never prices. Events are buffered locally and
/// shipped in one authenticated batch, because a measurement is worthless if
/// pushing it can fail the job that produced it. Keys are deterministic so a
/// resend after a dropped connection is recognised as a replay rather than
/// appended a second time.
/// </remarks>
public sealed class ResourceLedger(string jobId, int attempt = 1)
{
    private readonly List<ResourceEventPayload> events = [];

    public IReadOnlyList<ResourceEventPayload> Events => events;

    /// <summary>
    /// Deterministic identity for one measurement.
    /// </summary>
    /// <remarks>
    /// The attempt is part of the key. A retried job re-measures the same
    /// stages, and without it the second attempt would resubmit the first
    /// attempt's keys carrying different timings — which the ledger correctly
    /// rejects as a collision, silently discarding the retry's measurements.
    /// </remarks>
    public string Key(params string[] parts) =>
        string.Join(':', ["job", jobId, "attempt", attempt.ToString(), .. parts]);

    /// <summary>Start measuring a stage; the returned scope records on dispose.</summary>
    public ResourceScope Begin(
        string key,
        ResourceEventType type,
        ResourceStage stage,
        AgentRole? agentRole = null) =>
        new(this, key, type, stage, agentRole, attempt);

    public void Add(ResourceEventPayload payload) => events.Add(payload);

    /// <summary>
    /// Record something that needs a human's attention but did not fail the
    /// job — an untested Codex CLI version, for instance.
    /// </summary>
    public void Warn(string key, ResourceStage stage, string code, string detail)
    {
        var now = DateTimeOffset.UtcNow;
        events.Add(new ResourceEventPayload(
            key, nameof(ResourceEventType.WARNING), stage.ToString(), attempt, null,
            now, now, 0, Success: true, FailureCode: null,
            Ai: null, Process: null, Cad: null,
            Metadata: new Dictionary<string, string> { ["code"] = code, ["detail"] = Bounded(detail) }));
    }

    internal static string Bounded(string value) =>
        value.Length <= 500 ? value : value[..500];
}

/// <summary>
/// One measured span. Disposing records it, including when the stage threw:
/// a failed operation is exactly the one whose cost needs explaining.
/// </summary>
public sealed class ResourceScope : IDisposable
{
    private readonly ResourceLedger ledger;
    private readonly string key;
    private readonly ResourceEventType type;
    private readonly ResourceStage stage;
    private readonly AgentRole? agentRole;
    private readonly int attempt;
    private readonly DateTimeOffset startedAt = DateTimeOffset.UtcNow;
    private readonly long startedTicks = Stopwatch.GetTimestamp();
    private readonly TimeSpan startCpuUser;
    private readonly TimeSpan startCpuSystem;
    private readonly Dictionary<string, string> metadata = [];

    private bool success;
    private string? failureCode;
    private AiUsagePayload? ai;
    private CadUsagePayload? cad;
    private ProcessUsagePayload? process;
    private bool recorded;

    internal ResourceScope(
        ResourceLedger ledger,
        string key,
        ResourceEventType type,
        ResourceStage stage,
        AgentRole? agentRole,
        int attempt)
    {
        (this.ledger, this.key, this.type, this.stage, this.agentRole, this.attempt) =
            (ledger, key, type, stage, agentRole, attempt);
        (startCpuUser, startCpuSystem) = CurrentCpu();
    }

    public ResourceScope Meta(string name, string value)
    {
        metadata[name] = ResourceLedger.Bounded(value);
        return this;
    }

    public ResourceScope WithAi(AiUsagePayload usage)
    {
        ai = usage;
        return this;
    }

    public ResourceScope WithCad(CadUsagePayload usage)
    {
        cad = usage;
        return this;
    }

    public ResourceScope WithProcess(ProcessUsagePayload usage)
    {
        process = usage;
        return this;
    }

    public void Succeeded() => success = true;

    public void Failed(string code)
    {
        success = false;
        failureCode = code;
    }

    public void Dispose()
    {
        if (recorded) return;
        recorded = true;
        var finishedAt = DateTimeOffset.UtcNow;
        var wallMs = (long)Stopwatch.GetElapsedTime(startedTicks).TotalMilliseconds;
        // A scope disposed without an explicit outcome unwound through an
        // exception. Recording it as a success would hide the failure whose
        // cost is most worth explaining.
        var code = success ? null : failureCode ?? "UNCAUGHT_ERROR";
        ledger.Add(new ResourceEventPayload(
            key,
            type.ToString(),
            stage.ToString(),
            attempt,
            agentRole?.ToString(),
            startedAt,
            finishedAt,
            wallMs,
            success,
            code,
            ai,
            process ?? SelfProcessUsage(),
            cad,
            metadata));
    }

    private ProcessUsagePayload? SelfProcessUsage()
    {
        // In-process work: report the CPU this worker burned during the span.
        var (user, system) = CurrentCpu();
        if (user == TimeSpan.Zero && system == TimeSpan.Zero) return null;
        long? peak = null;
        try { peak = Process.GetCurrentProcess().PeakWorkingSet64; } catch { }
        return new ProcessUsagePayload(
            (long)Math.Max((user - startCpuUser).TotalMilliseconds, 0),
            (long)Math.Max((system - startCpuSystem).TotalMilliseconds, 0),
            peak, null, null, null, null, 0);
    }

    private static (TimeSpan User, TimeSpan System) CurrentCpu()
    {
        try
        {
            using var self = Process.GetCurrentProcess();
            return (self.UserProcessorTime, self.PrivilegedProcessorTime);
        }
        catch
        {
            return (TimeSpan.Zero, TimeSpan.Zero);
        }
    }
}

/// <summary>
/// Ships buffered measurements to the API.
/// </summary>
/// <remarks>
/// Never throws. The artifacts the customer asked for are already uploaded by
/// the time this runs, and losing accounting data is a smaller failure than
/// losing a finished model. Batches are chunked and retried; the API treats a
/// resend of the same event keys as a replay, so a retry after a dropped
/// connection cannot double-count.
/// </remarks>
public static class ResourceLedgerShipper
{
    private const int BatchSize = 200;
    private const int MaxAttempts = 3;

    public static async Task<bool> ShipAsync(
        HttpClient client,
        string jobId,
        ResourceLedger ledger,
        CancellationToken cancellationToken)
    {
        if (ledger.Events.Count == 0) return true;
        var shipped = true;
        for (var offset = 0; offset < ledger.Events.Count; offset += BatchSize)
        {
            var batch = ledger.Events.Skip(offset).Take(BatchSize).ToArray();
            shipped &= await SendAsync(client, jobId, batch, cancellationToken);
        }
        return shipped;
    }

    private static async Task<bool> SendAsync(
        HttpClient client,
        string jobId,
        IReadOnlyList<ResourceEventPayload> events,
        CancellationToken cancellationToken)
    {
        for (var attempt = 1; attempt <= MaxAttempts; attempt++)
        {
            try
            {
                var response = await client.PostAsJsonAsync(
                    $"/api/v1/workers/jobs/{jobId}/resource-events",
                    new { schema_version = "1.0", job_id = jobId, events },
                    cancellationToken);
                if (response.IsSuccessStatusCode) return true;
                // A rejected batch will be rejected again: a malformed event or
                // a key collision is a defect in this build, not a transient
                // fault, and retrying it only delays the job.
                if ((int)response.StatusCode is >= 400 and < 500)
                {
                    Console.Error.WriteLine(JsonSerializer.Serialize(new
                    {
                        @event = "resource_events_rejected",
                        job_id = jobId,
                        status = (int)response.StatusCode
                    }));
                    return false;
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return false;
            }
            catch (HttpRequestException) { }
            if (attempt < MaxAttempts)
                await Task.Delay(TimeSpan.FromSeconds(attempt * 2), CancellationToken.None);
        }
        Console.Error.WriteLine(JsonSerializer.Serialize(new
        {
            @event = "resource_events_undelivered",
            job_id = jobId,
            count = events.Count
        }));
        return false;
    }
}

public static class CodexLedgerExtensions
{
    /// <summary>
    /// Translate a Codex stage result into the ledger's AI usage shape.
    /// Unavailable counts stay null, and the source records whether the
    /// numbers were measured, summarised or never obtained.
    /// </summary>
    public static AiUsagePayload ToAiUsage(
        this CodexStageResult result,
        string promptVersion,
        string? promptBundleSha256 = null)
    {
        var reading = result.UsageReading?.Reading ?? CodexUsageReading.Unknown;
        var observation = result.ModelObservation
            ?? CodexModelObservation.Compare(result.Model, null, result.ReasoningEffort, null);
        return new AiUsagePayload(
            observation.RequestedModel,
            observation.ObservedModel,
            observation.RequestedReasoningEffort,
            observation.ObservedReasoningEffort,
            observation.StatusCode,
            result.Routing?.ProfileVersion,
            result.Routing?.RuleId,
            "standard",
            result.CliVersion,
            promptVersion,
            result.ProvenanceSha256 is null ? null : promptBundleSha256,
            result.ProvenanceSha256,
            result.ThreadId,
            reading.Source switch
            {
                CodexTokenSource.Structured => "STRUCTURED",
                CodexTokenSource.Summary => "SUMMARY",
                CodexTokenSource.Estimated => "ESTIMATED",
                _ => "UNKNOWN"
            },
            reading.InputTokens,
            reading.CachedInputTokens,
            reading.OutputTokens,
            reading.ReasoningTokens,
            reading.TotalTokens);
    }

    public static ProcessUsagePayload? ToProcessUsage(this CodexStageResult result) =>
        result.Process is null
            ? null
            : new ProcessUsagePayload(
                result.Process.CpuUserMs,
                result.Process.CpuSystemMs,
                result.Process.PeakMemoryBytes,
                null,
                null,
                result.Process.ExitCode,
                null,
                0);
}
