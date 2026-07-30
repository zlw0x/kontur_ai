using System.Text.Json;
using CadAi.KompasAdapter;

namespace CadAi.LocalWorker;

/// <summary>
/// Runs the selector stability acceptance on real KOMPAS geometry.
/// </summary>
/// <remarks>
/// A diagnostic rather than a unit test, because what it checks needs a real
/// modelling kernel: the resolver is only worth having if a selector survives
/// a rebuild that renumbers faces and a reopen in a new process, and neither
/// can be simulated.
///
/// It also emits the ledger events selector resolution will produce once a
/// feature consumes selectors. Nothing in the build pipeline resolves one yet,
/// so wiring the measurement into the pipeline now would add code no job
/// reaches; measuring it here keeps the event shape exercised by something
/// real until fillets arrive.
/// </remarks>
public static class SelectorDiagnostic
{
    public static async Task<int> RunAsync(string[] arguments, WorkerPaths paths)
    {
        var output = arguments.FirstOrDefault(value => !value.StartsWith("--", StringComparison.Ordinal))
            ?? Path.Combine(paths.WorkspaceRoot, "selector-stability");
        var jobId = $"selector-diagnostic-{DateTimeOffset.UtcNow:yyyyMMddHHmmss}";
        var ledger = new ResourceLedger(jobId);

        SelectorStabilityReport report;
        using (var scope = ledger.Begin(
                   ledger.Key("selector", "stability", "run"),
                   ResourceEventType.CAD_SESSION,
                   ResourceStage.SELECTOR_RESOLUTION))
        {
            try
            {
                report = await SelectorStabilityRun.RunAsync(output, CancellationToken.None);
            }
            catch (CadAdapterException error)
            {
                scope.Failed(error.Code);
                throw new WorkerException(error.Code, error.SafeMessage);
            }
            scope.Meta("phases", report.Phases.Count.ToString());
            if (report.Passed) scope.Succeeded();
            else scope.Failed("SELECTOR_STABILITY_FAILED");
        }

        foreach (var phase in report.Phases)
            Record(ledger, phase);

        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                status = report.Passed ? "SELECTORS_STABLE" : "SELECTORS_UNSTABLE",
                report,
                resource_events = ledger.Events
            },
            new JsonSerializerOptions { WriteIndented = true }));
        return report.Passed ? 0 : 1;
    }

    /// <summary>
    /// One event per phase, carrying what a cost engine would need: how long
    /// resolution took, how many candidates it started from, and how many
    /// selectors did not resolve.
    /// </summary>
    private static void Record(ResourceLedger ledger, SelectorPhase phase)
    {
        var unresolved = phase.Selectors.Count(outcome => !outcome.Resolution.Satisfied);
        var now = DateTimeOffset.UtcNow;
        ledger.Add(new ResourceEventPayload(
            ledger.Key("selector", "resolve", phase.Phase),
            nameof(ResourceEventType.CAD_OPERATION),
            nameof(ResourceStage.SELECTOR_RESOLUTION),
            AttemptNo: 1,
            AgentRole: null,
            StartedAt: now.AddMilliseconds(-(phase.ReadMs + phase.ResolveMs)),
            FinishedAt: now,
            WallMs: phase.ReadMs + phase.ResolveMs,
            // An unresolved selector is an expected outcome here: the
            // catalogue deliberately contains one that must stay ambiguous.
            // Success means the phase measured what it set out to measure.
            Success: phase.Selectors.All(outcome => outcome.AsExpected),
            FailureCode: phase.Selectors.All(outcome => outcome.AsExpected)
                ? null
                : "SELECTOR_UNEXPECTED_RESULT",
            Ai: null,
            Process: null,
            Cad: new CadUsagePayload(
                OperationCode: $"selector_resolution_{phase.Phase}",
                OperationCount: phase.Selectors.Count,
                FailedFeatureCount: unresolved,
                SessionReuseCount: null,
                ForcedTermination: false,
                ResultBytes: null),
            Metadata: new Dictionary<string, string>
            {
                ["phase"] = phase.Phase,
                ["face_candidates"] = phase.FaceCount.ToString(),
                ["edge_candidates"] = phase.EdgeCount.ToString(),
                ["topology_read_ms"] = phase.ReadMs.ToString(),
                ["resolve_ms"] = phase.ResolveMs.ToString()
            }));
    }
}
