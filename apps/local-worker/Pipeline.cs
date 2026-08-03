using CadAi.CadEngine;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;

namespace CadAi.LocalWorker;

public static class FakeJobHandler
{
    public static async Task<int> RunAsync(string? path, WorkerPaths paths)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new WorkerException("JOB_PATH_REQUIRED", "run-job requires a job directory.", 2);
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(fullPath);
        var workspaceRoot = Path.GetFullPath(paths.WorkspaceRoot);
        Directory.CreateDirectory(workspaceRoot);
        var output = Path.Combine(fullPath, "output");
        Directory.CreateDirectory(output);
        var state = Path.Combine(fullPath, "state.json");
        await AtomicWriteAsync(state, JsonSerializer.Serialize(new { status = "COMPLETED", handler = "fake", completed_at = DateTimeOffset.UtcNow }));
        await AtomicWriteAsync(Path.Combine(output, "validation-report.json"), JsonSerializer.Serialize(new { valid = true, fake = true }));
        Console.WriteLine(JsonSerializer.Serialize(new { status = "COMPLETED", path = fullPath }));
        return 0;
    }

    internal static async Task AtomicWriteAsync(string path, string content)
    {
        var temp = path + ".tmp";
        await File.WriteAllTextAsync(temp, content);
        File.Move(temp, path, true);
    }
}

public static class LocalCadJobHandler
{
    public static async Task<int> RunAsync(
        string? path,
        WorkerPaths paths,
        ICadDocumentEngine engine,
        CancellationToken cancellationToken = default,
        ResourceLedger? ledger = null)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new WorkerException("JOB_PATH_REQUIRED", "run-job requires a job directory.", 2);
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetFullPath(paths.WorkspaceRoot));
        Directory.CreateDirectory(fullPath);
        if (!File.Exists(Path.Combine(fullPath, "cad-ir.json")))
            return await FakeJobHandler.RunAsync(fullPath, paths);

        var output = Path.Combine(fullPath, "output");
        var state = Path.Combine(fullPath, "state.json");
        await FakeJobHandler.AtomicWriteAsync(
            state,
            JsonSerializer.Serialize(new { status = "BUILDING", started_at = DateTimeOffset.UtcNow }));
        try
        {
            // Nothing is created before the build is attempted. The engine writes
            // its own `output/`, and an empty one left behind by a refusal reads
            // like a build that ran.
            return await RunWithDocumentEngineAsync(
                engine, fullPath, output, state,
                FeatureFlags.Load(paths), cancellationToken, ledger);
        }
        catch (CadAdapterException error)
        {
            await FakeJobHandler.AtomicWriteAsync(
                state,
                JsonSerializer.Serialize(new
                {
                    status = "FAILED",
                    code = error.Code,
                    stage = error.Stage,
                    failed_at = DateTimeOffset.UtcNow
                }));
            throw new WorkerException(error.Code, error.SafeMessage);
        }
    }

    /// <summary>
    /// One job, built by the engine that reads the document itself.
    /// </summary>
    /// <remarks>
    /// Shorter than the plan-based path, and the difference is where the work
    /// moved rather than work that stopped happening. There is no parse here
    /// because the engine parses with the same validator the API uses; there is
    /// no geometry validation here because the engine reopened both files and
    /// measured them before it answered (ENGINE-MIG-005); and there is no gate
    /// here because the flags travelled with the request and the engine echoed
    /// back which ones it applied.
    ///
    /// What this side still owns is what it always owned: the lease, the state
    /// file, the ledger, and the envelope the rest of the service reads.
    /// </remarks>
    private static async Task<int> RunWithDocumentEngineAsync(
        ICadDocumentEngine engine,
        string jobPath,
        string output,
        string state,
        FeatureFlags flags,
        CancellationToken cancellationToken,
        ResourceLedger? ledger)
    {
        CadBuildResult result;
        using (var session = ledger?.Begin(
            ledger.Key("cad", "session", "1"),
            ResourceEventType.CAD_SESSION,
            ResourceStage.CAD_STARTUP))
        {
            try
            {
                result = await engine.BuildAsync(
                    new CadDocumentBuildRequest(jobPath, [.. flags.Disabled]), cancellationToken);
                session?.WithCad(new CadUsagePayload(
                    "document_build",
                    result.Operations?.Count,
                    FailedFeatureCount: 0,
                    SessionReuseCount: 0,
                    ForcedTermination: false,
                    ResultBytes: result.Artifacts.Sum(artifact => artifact.SizeBytes)));
                session?.Succeeded();
                RecordOperations(ledger, result.Operations);
            }
            catch (CadAdapterException error)
            {
                session?.Failed(error.Code);
                RecordOperations(ledger, error.Operations);
                throw;
            }
        }

        await FakeJobHandler.AtomicWriteAsync(
            Path.Combine(output, "validation-report.json"),
            JsonSerializer.Serialize(new
            {
                valid = true,
                adapter = result.Engine?.EngineId,
                engine = result.Engine is { } identity
                    ? new
                    {
                        engine_id = identity.EngineId,
                        engine_version = identity.EngineVersion,
                        kernel_id = identity.KernelId,
                        kernel_version = identity.KernelVersion,
                        cad_ir_version = identity.CadIrVersion
                    }
                    : null,
                // The engine's own report, kept whole rather than summarised.
                // It measured a reopened STEP and a parsed STL; restating that
                // as a boolean here would throw away the only evidence anyone
                // has that the model is right.
                geometry = ReadEngineReport(output),
                artifacts = result.Artifacts.Select(artifact => new
                {
                    artifact.Kind,
                    file = Path.GetFileName(artifact.Path),
                    artifact.SizeBytes,
                    artifact.Sha256
                })
            }));

        await FakeJobHandler.AtomicWriteAsync(
            state,
            JsonSerializer.Serialize(new { status = "COMPLETED", completed_at = DateTimeOffset.UtcNow }));
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            status = "COMPLETED",
            adapter = result.Engine?.EngineId,
            artifacts = result.Artifacts.Count,
            path = jobPath
        }));
        return 0;
    }

    /// <summary>
    /// The engine's validation report, as JSON, or nothing.
    /// </summary>
    /// <remarks>
    /// Read back rather than kept in memory because the engine writes it into
    /// the job directory itself, and in container mode this side never saw the
    /// object it came from. Nothing rather than a failure if it is unreadable:
    /// the build already succeeded and the engine already refused to report
    /// success without verifying, so an absent report is a worse envelope rather
    /// than an unbuilt part.
    /// </remarks>
    private static JsonElement? ReadEngineReport(string output)
    {
        var path = Path.Combine(output, "validation-report.json");
        if (!File.Exists(path)) return null;
        try
        {
            return JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone();
        }
        catch (Exception error) when (error is JsonException or IOException)
        {
            return null;
        }
    }

    /// <summary>
    /// Turn adapter step timings into one ledger event each.
    /// </summary>
    /// <remarks>
    /// Recorded per operation rather than as a single CAD duration so a slow
    /// startup, a slow hole and a slow export stay distinguishable when the
    /// feature vocabulary grows.
    /// </remarks>
    private static void RecordOperations(
        ResourceLedger? ledger,
        IReadOnlyList<CadOperationRecord>? operations)
    {
        if (ledger is null || operations is null || operations.Count == 0) return;

        // The adapter measures consecutive steps, so they are laid end to end
        // finishing when the build finished. Giving every step the same finish
        // time made long steps look like they started first, which put the
        // ledger in an order the build never ran in.
        var total = operations.Sum(operation => operation.WallMs);
        var cursor = DateTimeOffset.UtcNow.AddMilliseconds(-total);
        foreach (var operation in operations)
        {
            var startedAt = cursor;
            cursor = cursor.AddMilliseconds(operation.WallMs);
            var stage = LedgerStageFor(operation.Stage);
            ledger.Add(new ResourceEventPayload(
                ledger.Key("cad", "operation", operation.OperationCode),
                stage == ResourceStage.EXPORT
                    ? nameof(ResourceEventType.EXPORT)
                    : nameof(ResourceEventType.CAD_OPERATION),
                stage.ToString(),
                1,
                null,
                startedAt,
                cursor,
                operation.WallMs,
                operation.Success,
                operation.FailureCode,
                null,
                null,
                new CadUsagePayload(operation.OperationCode, 1, operation.Success ? 0 : 1, 0, false, null),
                new Dictionary<string, string> { ["adapter_stage"] = operation.Stage }));
        }
    }

    /// <summary>
    /// Map an adapter step onto the ledger's stage vocabulary.
    /// </summary>
    /// <remarks>
    /// Recording every step as FEATURE_BUILD made startup, save and export
    /// indistinguishable from actual feature work, so export attempts were
    /// never counted and a slow engine launch looked like slow modelling.
    /// </remarks>
    private static ResourceStage LedgerStageFor(string adapterStage) => adapterStage switch
    {
        "activation" => ResourceStage.CAD_STARTUP,
        "document" => ResourceStage.DOCUMENT_BUILD,
        "sketch" or "feature" => ResourceStage.FEATURE_BUILD,
        "save" or "export" => ResourceStage.EXPORT,
        _ => ResourceStage.FEATURE_BUILD
    };
}

public static class ClaimLoop
{
    public static async Task<int> RunAsync(
        WorkerConfigStore configs,
        ICredentialStore credentials,
        WorkerPaths paths,
        CancellationToken cancellation,
        bool runOnce = false)
    {
        var config = configs.Load() ?? throw new WorkerException("AUTH_REQUIRED", "Worker enrollment is required.", 3);
        var credential = credentials.Load();
        // Resolved once for the life of the loop. Which engine a worker builds
        // with is a property of the deployment, not of a job: a worker that
        // could change engine between two jobs would produce results nobody
        // could compare.
        var selected = WorkerEngine.EngineSelection.For(config.CadEngine);
        using var client = new HttpClient { BaseAddress = new Uri(config.ServerUrl), Timeout = TimeSpan.FromSeconds(35) };
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", credential);
        var failures = 0;
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                var response = await client.PostAsJsonAsync("/api/v1/workers/claim", new
                {
                    protocol_version = "1.0", worker_id = config.WorkerId,
                    capabilities = new[] { "AI_DRAWING", "CAD_BUILD" },
                    supported_cad_ir = new[] { WorkerCapabilities.CadIrVersion },
                    available_slots = 1,
                    // Declaring what this build can construct is what makes the
                    // API willing to schedule those operations here.
                    capability_manifest = await selected.ManifestAsync(
                        FeatureFlags.Load(paths), cancellationToken: cancellation)
                }, cancellation);
                if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                    throw new WorkerException("AUTH_REQUIRED", "Worker credential was rejected.", 3);
                response.EnsureSuccessStatusCode();
                var claim = await response.Content.ReadFromJsonAsync<ClaimResponse>(cancellationToken: cancellation);
                failures = 0;
                if (claim?.job is not null)
                {
                    await RunClaimedJobAsync(client, claim.job, paths, selected, cancellation);
                    if (runOnce) return 0;
                }
                else if (runOnce) return 0;
                await Task.Delay(TimeSpan.FromSeconds(claim?.retry_after_seconds ?? config.PollSeconds), cancellation);
            }
            catch (WorkerException) { throw; }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { break; }
            catch
            {
                failures++;
                var delay = Math.Min(60, Math.Pow(2, Math.Min(failures, 6)));
                await Task.Delay(TimeSpan.FromSeconds(delay), cancellation);
            }
        }
        return 0;
    }

    /// <summary>
    /// Run a claimed job, and if it will not be tried again, say so.
    /// </summary>
    /// <remarks>
    /// **A retry is the first answer, not this.** Most failures are worth another
    /// attempt: a container that would not start, an interpreter missing for a
    /// moment, a machine under load. Those raise, the lease lapses, and the API
    /// hands the job to whoever claims next. That is working as intended and this
    /// method leaves it alone.
    ///
    /// What was missing is the end of it. When retrying stopped helping, nothing
    /// said so — the job returned to PENDING for the last time and stayed there.
    /// The customer's page reads that as "waiting to start", and it is
    /// indistinguishable, forever, from a queue with no worker on it. A build that
    /// failed and a build that has not begun looked exactly alike.
    ///
    /// Two cases end it, and both are decided from what is already known:
    ///
    /// **The failure is about the document.** `BuildFeedback` classifies those,
    /// and by the time one reaches here the build-repair loop has already rewritten
    /// the document twice and been refused twice. A fresh attempt re-runs the same
    /// model calls on the same drawing and arrives at the same place, on somebody's
    /// order. Reporting it is both truer and cheaper.
    ///
    /// **It was the last permitted attempt.** `max_attempts` now travels with the
    /// claim precisely so this does not have to be a number written down twice.
    ///
    /// Anything else is left to lapse, unchanged.
    ///
    /// Reporting is itself allowed to fail, and quietly: the lease is the fallback
    /// and it still works. Turning "the build failed and so did telling you about
    /// it" into a crash would take out the claim loop for every later job.
    ///
    /// **A failed job is not a failed worker**, and it used to be. The claim loop
    /// rethrows `WorkerException`, so a build that refused a document did not go
    /// into the backoff — it ended `cad-worker run`, and the machine stopped taking
    /// orders until somebody noticed. One customer's bad drawing took the queue
    /// down. Handled here, so the loop goes on to the next job. Failures that are
    /// about the *worker* rather than the job — a rejected credential — are raised
    /// before a job is ever claimed and still stop it.
    /// </remarks>
    private static async Task RunClaimedJobAsync(
        HttpClient client,
        ClaimedJob job,
        WorkerPaths paths,
        WorkerEngine.EngineSelection selected,
        CancellationToken cancellation)
    {
        try
        {
            await ExecuteClaimedJobAsync(client, job, paths, selected, cancellation);
        }
        catch (WorkerException error)
        {
            if (BuildFeedback.IsRepairable(error.Code) || job.attempt >= job.max_attempts)
                await TryReportFailureAsync(client, job, error.Code, error.SafeMessage, cancellation);
            Console.Error.WriteLine(
                $"job {job.job_id} attempt {job.attempt}/{job.max_attempts} failed: {error.Code}");
        }
    }

    /// <summary>Tell the API the job is over, or fail silently trying.</summary>
    private static async Task TryReportFailureAsync(
        HttpClient client,
        ClaimedJob job,
        string code,
        string message,
        CancellationToken cancellation)
    {
        try
        {
            using var response = await client.PostAsJsonAsync(
                $"/api/v1/workers/jobs/{job.job_id}/fail",
                new { job_id = job.job_id, code, message },
                cancellation);
            response.EnsureSuccessStatusCode();
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch
        {
            // The lease still expires and the job still stops being ours. Losing
            // the reason is worse than not having it; losing the claim loop is
            // worse than both.
        }
    }

    /// <summary>
    /// The pipeline a claimed drawing job runs, with everything that checks it.
    /// </summary>
    /// <remarks>
    /// Split out because leaving it inline is how it went wrong. The claim loop
    /// built a <see cref="DrawingPipeline"/> with no engine and no feature flags,
    /// and <c>ValidateAsync</c> opens with `if (engine is null) return;` — whose
    /// own comment says a missing engine "is only ever the case in a test: every
    /// real path passes one in". The claim loop is a real path, and it was the
    /// one that did not.
    ///
    /// Silently, and for every online order: no trusted semantic gate over the
    /// generated document, **no shape claim check at all** — the whole of
    /// POSTMVP-015, twelve holes against six, a solid block against a housing —
    /// no compile-stage repair loop, and operator feature flags not applied. All
    /// of it worked when the same drawing went through `analyze-drawing` by hand,
    /// which is why nine acceptance runs never saw it.
    ///
    /// The engine was already at the call site: the line below passes
    /// `selected.Engine` to the build. Only the check was missing it.
    ///
    /// Assembled here rather than inline so a test can assert what an online job
    /// is given, which is the thing no test could see before — every existing one
    /// hands the pipeline a stub engine of its own and is therefore blind to the
    /// wiring.
    /// </remarks>
    internal static DrawingPipeline CreateDrawingPipeline(
        WorkerPaths paths,
        WorkerEngine.EngineSelection selected,
        ResourceLedger ledger) =>
        new(new CadAi.CodexRunner.LocalCodexRunner(),
            ledger: ledger,
            engine: selected.Engine,
            disabledCapabilities: [.. FeatureFlags.Load(paths).Disabled]);

    private static async Task ExecuteClaimedJobAsync(
        HttpClient client,
        ClaimedJob job,
        WorkerPaths paths,
        WorkerEngine.EngineSelection selected,
        CancellationToken cancellation)
    {
        var jobPath = Path.Combine(paths.WorkspaceRoot, job.job_id);
        Directory.CreateDirectory(jobPath);
        var ledger = new ResourceLedger(job.job_id, job.attempt);
        var manifest = await client.GetFromJsonAsync<JobManifest>(job.manifest_url, cancellation)
            ?? throw new WorkerException("MANIFEST_INVALID", "Job manifest was empty.");
        if (manifest.manifest_version != "1.0" || manifest.job_id != job.job_id)
            throw new WorkerException("MANIFEST_INVALID", "Job manifest version or identity is invalid.");
        if (manifest.inputs.Length is < 1 or > 11)
            throw new WorkerException("MANIFEST_INVALID", "Job manifest input count is invalid.");
        foreach (var input in manifest.inputs)
        {
            var maxSize = input.kind == "drawing" ? 25L * 1024 * 1024 : 1_048_576;
            if (input.size_bytes <= 0 || input.size_bytes > maxSize)
                throw new WorkerException("MANIFEST_INVALID", "Job input metadata is invalid.");
            using var download = ledger.Begin(
                ledger.Key("transfer", "input", input.kind),
                ResourceEventType.TRANSFER,
                ResourceStage.IMAGE_PREPROCESSING);
            var payload = await client.GetByteArrayAsync(input.download_url, cancellation);
            if (payload.LongLength != input.size_bytes || !ChecksumMatches(payload, input.sha256))
            {
                download.Failed("INPUT_INTEGRITY_FAILED");
                throw new WorkerException("INPUT_INTEGRITY_FAILED", "Input checksum or size does not match manifest.");
            }
            download.WithProcess(new ProcessUsagePayload(
                null, null, null, payload.LongLength, null, null, null, 0));
            download.Succeeded();
            var destination = input.kind switch
            {
                "cad_ir" when input.local_name == "cad-ir.json" => Path.Combine(jobPath, "cad-ir.json"),
                "drawing" when input.local_name is "page-001.png" or "page-001.jpg" =>
                    Path.Combine(jobPath, "input", input.local_name),
                "user_answers" when input.local_name == "user-answers.json" =>
                    Path.Combine(jobPath, "context", input.local_name),
                _ => throw new WorkerException("MANIFEST_INVALID", "Job input kind or local name is invalid.")
            };
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            await File.WriteAllBytesAsync(destination, payload, cancellation);
        }

        using var leaseCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        var heartbeat = MaintainLeaseAsync(client, job.job_id, leaseCancellation.Token);
        try
        {
            var waitingForAnswers = false;
            if (job.job_type == "ANALYZE_DRAWING")
            {
                var images = Directory.EnumerateFiles(Path.Combine(jobPath, "input"))
                    .Where(file => Path.GetExtension(file).ToLowerInvariant() is ".png" or ".jpg" or ".jpeg")
                    .OrderBy(file => file, StringComparer.OrdinalIgnoreCase)
                    .ToArray();
                var answersPath = Path.Combine(jobPath, "context", "user-answers.json");
                var pipeline = CreateDrawingPipeline(paths, selected, ledger);
                var drawing = await pipeline.RunAsync(
                    jobPath,
                    images,
                    File.Exists(answersPath) ? answersPath : null,
                    cancellation);
                waitingForAnswers = drawing.Status == "WAITING_FOR_USER_ANSWERS";
                if (!waitingForAnswers)
                {
                    await BuildWithRepairsAsync(
                        pipeline, drawing.CadIrPath!, jobPath, paths, selected.Engine,
                        ledger, cancellation);
                }
            }
            else
            {
                await LocalCadJobHandler.RunAsync(
                    jobPath, paths, selected.Engine, cancellation, ledger);
            }
            // ^ see BuildWithRepairsAsync below.
            //
            // What the engine says it produces, plus what the pipeline itself
            // writes. The engine half used to be a literal `M3D, STEP, STL` here,
            // which put an engine-native format into the definition of a finished
            // job and left no way to express an engine that does not make one.
            var engine = await selected.DescribeAsync(FeatureFlags.Load(paths), cancellation);
            var uploaded = new List<UploadedArtifact>();
            foreach (var (type, fileName) in engine.Artifacts
                         .Select(artifact => (artifact.Kind, artifact.FileName))
                         .Concat(WorkerEngine.PipelineArtifacts))
            {
                var artifactPath = Path.Combine(jobPath, "output", fileName);
                if (!File.Exists(artifactPath)) continue;
                using var upload = ledger.Begin(
                    ledger.Key("transfer", "artifact", type),
                    ResourceEventType.TRANSFER,
                    ResourceStage.ARTIFACT_UPLOAD);
                var artifactBytes = await File.ReadAllBytesAsync(artifactPath, cancellation);
                var checksum = Convert.ToHexString(SHA256.HashData(artifactBytes));
                using var content = new ByteArrayContent(artifactBytes);
                content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
                content.Headers.Add("x-content-sha256", checksum);
                var uploadUrl = manifest.artifact_upload_url_template.Replace(
                    "{artifact_type}",
                    Uri.EscapeDataString(type),
                    StringComparison.Ordinal);
                var response = await client.PutAsync(uploadUrl, content, cancellation);
                response.EnsureSuccessStatusCode();
                var item = await response.Content.ReadFromJsonAsync<UploadedArtifact>(
                    cancellationToken: cancellation)
                    ?? throw new WorkerException("ARTIFACT_UPLOAD_FAILED", "Artifact upload returned no metadata.");
                upload.WithProcess(new ProcessUsagePayload(
                    null, null, null, null, artifactBytes.LongLength, null, null, 0));
                upload.Succeeded();
                uploaded.Add(item);
            }
            // Every kind the engine promised, rather than one format named here.
            // A build that did not produce something its own engine declared is a
            // failed build whatever the engine is.
            if (!waitingForAnswers)
                foreach (var required in engine.RequiredArtifacts)
                    if (uploaded.All(artifact => artifact.type != required.Kind))
                        throw new WorkerException(
                            "ARTIFACT_UPLOAD_FAILED",
                            $"{required.Kind} was not uploaded, and {engine.EngineId} declares it.");
            if (waitingForAnswers && uploaded.All(artifact => artifact.type != "CLARIFICATION_QUESTIONS"))
                throw new WorkerException("ARTIFACT_UPLOAD_FAILED", "Clarification questions were not uploaded.");
            // Shipped while the lease is still held, and deliberately before
            // completion: the ingestion endpoint is lease-scoped, and a job
            // must never fail because its measurements could not be filed.
            await ResourceLedgerShipper.ShipAsync(client, job.job_id, ledger, cancellation);
            var complete = await client.PostAsJsonAsync(
                $"/api/v1/workers/jobs/{job.job_id}/complete",
                new
                {
                    job_id = job.job_id,
                    idempotency_key = job.idempotency_key,
                    result = new
                    {
                        status = waitingForAnswers ? "need_user_input" : "success",
                        cad_attempts = waitingForAnswers ? 0 : 1
                    },
                    artifacts = uploaded
                },
                cancellation);
            complete.EnsureSuccessStatusCode();
        }
        finally
        {
            leaseCancellation.Cancel();
            try { await heartbeat; } catch (OperationCanceledException) { }
        }
    }

    private static async Task MaintainLeaseAsync(HttpClient client, string jobId, CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            await Task.Delay(TimeSpan.FromSeconds(20), cancellation);
            var response = await client.PostAsJsonAsync(
                $"/api/v1/workers/jobs/{jobId}/heartbeat",
                new
                {
                    job_id = jobId,
                    stage = "CAD_BUILDING",
                    progress = 0.5,
                    message_code = "CAD_BUILDING",
                    safe_details = new { }
                },
                cancellation);
            response.EnsureSuccessStatusCode();
        }
    }

    private static bool ChecksumMatches(byte[] payload, string expected)
    {
        var normalized = expected.StartsWith("sha256:", StringComparison.OrdinalIgnoreCase)
            ? expected[7..]
            : expected;
        try
        {
            return CryptographicOperations.FixedTimeEquals(
                SHA256.HashData(payload),
                Convert.FromHexString(normalized));
        }
        catch (FormatException) { return false; }
    }

    private sealed record ClaimResponse(ClaimedJob? job, int? retry_after_seconds);
    private sealed record ClaimedJob(
        string job_id,
        string job_type,
        int attempt,
        int max_attempts,
        string idempotency_key,
        string manifest_url);
    private sealed record JobManifest(
        string manifest_version,
        string job_id,
        ManifestInput[] inputs,
        string artifact_upload_url_template);
    /// <summary>
    /// Build the compiled document, and let the agent answer a build that refused it.
    /// </summary>
    /// <remarks>
    /// The compile loop repairs what the validators refuse. This closes the other
    /// half: a build failure that describes the *document* goes back to be
    /// rewritten, and the rewrite is built. Until now those ended the job, which
    /// meant the one class of failure the service can only learn by building was
    /// also the one class it never learned from.
    ///
    /// Bounded, and only for codes that name something the document asked for.
    /// <see cref="BuildFeedback"/> holds that judgement and the reasoning for it;
    /// a failure about the machine is rethrown on the spot, because asking a model
    /// to repair a missing container image spends a call to be told the same thing.
    ///
    /// The last failure is the one that surfaces. A job that failed three times
    /// should report why it finally failed, not why it first did.
    /// </remarks>
    private static async Task BuildWithRepairsAsync(
        DrawingPipeline pipeline,
        string compiledPath,
        string jobPath,
        WorkerPaths paths,
        ICadDocumentEngine engine,
        ResourceLedger? ledger,
        CancellationToken cancellation)
    {
        var documentPath = compiledPath;
        for (var attempt = 0; ; attempt++)
        {
            File.Copy(documentPath, Path.Combine(jobPath, "cad-ir.json"), overwrite: true);
            try
            {
                await LocalCadJobHandler.RunAsync(jobPath, paths, engine, cancellation, ledger);
                return;
            }
            // A WorkerException, not a CadAdapterException: the job handler has
            // already turned the engine's refusal into one, and catching the
            // original here would catch nothing at all.
            catch (WorkerException error)
                when (attempt < BuildFeedback.MaxBuildRepairs && BuildFeedback.IsRepairable(error))
            {
                ledger?.Warn(
                    ledger.Key("repair", "build_trigger", (attempt + 1).ToString()),
                    ResourceStage.GEOMETRY_VALIDATION,
                    error.Code,
                    error.SafeMessage);
                documentPath = await pipeline.RepairAfterBuildAsync(
                    jobPath, documentPath, attempt + 1, error.Code, error.SafeMessage, cancellation);
            }
        }
    }

    private sealed record ManifestInput(
        string kind,
        string download_url,
        string sha256,
        long size_bytes,
        string local_name);
    private sealed record UploadedArtifact(
        string type,
        string object_key,
        string sha256,
        long size_bytes);
}
