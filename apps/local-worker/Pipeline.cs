using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using CadAi.GeometryValidation;
using CadAi.KompasAdapter;

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
        bool fakeCad,
        CancellationToken cancellationToken = default,
        ResourceLedger? ledger = null)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new WorkerException("JOB_PATH_REQUIRED", "run-job requires a job directory.", 2);
        var fullPath = Path.GetFullPath(path);
        var workspaceRoot = Path.GetFullPath(paths.WorkspaceRoot);
        Directory.CreateDirectory(workspaceRoot);
        Directory.CreateDirectory(fullPath);
        var cadIrPath = Path.Combine(fullPath, "cad-ir.json");
        if (!File.Exists(cadIrPath))
            return await FakeJobHandler.RunAsync(fullPath, paths);

        var output = Path.Combine(fullPath, "output");
        Directory.CreateDirectory(output);
        var state = Path.Combine(fullPath, "state.json");
        await FakeJobHandler.AtomicWriteAsync(
            state,
            JsonSerializer.Serialize(new { status = "BUILDING", started_at = DateTimeOffset.UtcNow }));
        try
        {
            // The gate is checked on the document, before any COM object
            // exists: a disabled operation must cost a typed error rather
            // than a half-built model.
            var flags = FeatureFlags.Load(paths);
            var plan = await CadIrBuildPlanParser.ParseFileAsync(
                cadIrPath, cancellationToken, flags.Gate());
            ICadAdapter adapter = fakeCad ? new FakeCadAdapter() : new KompasApi7Adapter();
            CadBuildResult result;
            using (var session = ledger?.Begin(
                ledger.Key("cad", "session", "1"),
                ResourceEventType.CAD_SESSION,
                ResourceStage.KOMPAS_STARTUP))
            {
                try
                {
                    result = await adapter.BuildAsync(new CadBuildRequest(plan, output), cancellationToken);
                    session?.WithCad(new CadUsagePayload(
                        "rectangular_prism_with_holes",
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
                    // The steps that ran before the failure are on the
                    // exception; a build that died after twenty minutes still
                    // consumed them.
                    RecordOperations(ledger, error.Operations);
                    throw;
                }
            }
            GeometryValidationResult? validation = null;
            if (!fakeCad)
            {
                using var check = ledger?.Begin(
                    ledger.Key("validate", "geometry", "1"),
                    ResourceEventType.VALIDATION,
                    ResourceStage.GEOMETRY_VALIDATION);
                validation = GeometryValidator.Validate(
                    Path.Combine(output, "model.m3d"),
                    Path.Combine(output, "model.step"),
                    Path.Combine(output, "model.stl"),
                    // The document's own expectations, not numbers derived
                    // from the plan: a verifier that cannot disagree with the
                    // builder is not verifying anything.
                    new ExpectedGeometry(
                        plan.Expectations.SizeXMm,
                        plan.Expectations.SizeYMm,
                        plan.Expectations.SizeZMm,
                        plan.Expectations.BodyCount,
                        plan.Expectations.ThroughHoleCount,
                        plan.Expectations.ToleranceMm));
                if (validation.Valid) check?.Succeeded();
                else check?.Failed("GEOMETRY_VALIDATION_FAILED");
            }
            await FakeJobHandler.AtomicWriteAsync(
                Path.Combine(output, "validation-report.json"),
                JsonSerializer.Serialize(new
                {
                    valid = validation?.Valid ?? true,
                    adapter = fakeCad ? "fake" : "kompas-api7",
                    geometry = validation,
                    artifacts = result.Artifacts.Select(artifact => new
                    {
                        artifact.Kind,
                        file = Path.GetFileName(artifact.Path),
                        artifact.SizeBytes,
                        artifact.Sha256
                    })
                }));
            if (validation is { Valid: false })
                throw new CadAdapterException(
                    "GEOMETRY_VALIDATION_FAILED",
                    "validation",
                    "Generated CAD artifacts failed deterministic geometry validation.");
            await FakeJobHandler.AtomicWriteAsync(
                state,
                JsonSerializer.Serialize(new { status = "COMPLETED", completed_at = DateTimeOffset.UtcNow }));
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                status = "COMPLETED",
                adapter = fakeCad ? "fake" : "kompas-api7",
                artifacts = result.Artifacts.Count,
                path = fullPath
            }));
            return 0;
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
    /// never counted and a slow KOMPAS launch looked like slow modelling.
    /// </remarks>
    private static ResourceStage LedgerStageFor(string adapterStage) => adapterStage switch
    {
        "activation" => ResourceStage.KOMPAS_STARTUP,
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
        DpapiCredentialStore credentials,
        WorkerPaths paths,
        CancellationToken cancellation,
        bool runOnce = false)
    {
        var config = configs.Load() ?? throw new WorkerException("AUTH_REQUIRED", "Worker enrollment is required.", 3);
        var credential = credentials.Load();
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
                    capabilities = new[] { "AI_DRAWING", "KOMPAS_BUILD" },
                    supported_cad_ir = new[] { WorkerCapabilities.CadIrVersion },
                    available_slots = 1,
                    // Declaring what this build can construct is what makes the
                    // API willing to schedule those operations here.
                    capability_manifest = WorkerCapabilities.Manifest(flags: FeatureFlags.Load(paths))
                }, cancellation);
                if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                    throw new WorkerException("AUTH_REQUIRED", "Worker credential was rejected.", 3);
                response.EnsureSuccessStatusCode();
                var claim = await response.Content.ReadFromJsonAsync<ClaimResponse>(cancellationToken: cancellation);
                failures = 0;
                if (claim?.job is not null)
                {
                    await ExecuteClaimedJobAsync(client, claim.job, paths, cancellation);
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

    private static async Task ExecuteClaimedJobAsync(
        HttpClient client,
        ClaimedJob job,
        WorkerPaths paths,
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
                var drawing = await new DrawingPipeline(
                    new CadAi.CodexRunner.LocalCodexRunner(),
                    ledger: ledger).RunAsync(
                    jobPath,
                    images,
                    File.Exists(answersPath) ? answersPath : null,
                    cancellation);
                waitingForAnswers = drawing.Status == "WAITING_FOR_USER_ANSWERS";
                if (!waitingForAnswers)
                {
                    File.Copy(drawing.CadIrPath!, Path.Combine(jobPath, "cad-ir.json"), overwrite: true);
                    await LocalCadJobHandler.RunAsync(
                        jobPath, paths, fakeCad: false, cancellationToken: cancellation, ledger: ledger);
                }
            }
            else
            {
                await LocalCadJobHandler.RunAsync(
                    jobPath, paths, fakeCad: false, cancellationToken: cancellation, ledger: ledger);
            }
            var uploaded = new List<UploadedArtifact>();
            foreach (var (type, fileName) in new[]
            {
                ("M3D", "model.m3d"),
                ("STEP", "model.step"),
                ("STL", "model.stl"),
                ("VALIDATION_REPORT", "validation-report.json"),
                ("DRAWING_ANALYSIS", "drawing-analysis.json"),
                ("CLARIFICATION_QUESTIONS", "clarification-questions.json"),
                ("CAD_IR", "cad-ir.json")
            })
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
            if (!waitingForAnswers && uploaded.All(artifact => artifact.type != "M3D"))
                throw new WorkerException("ARTIFACT_UPLOAD_FAILED", "M3D artifact was not uploaded.");
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
                    message_code = "KOMPAS_BUILDING",
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
        string idempotency_key,
        string manifest_url);
    private sealed record JobManifest(
        string manifest_version,
        string job_id,
        ManifestInput[] inputs,
        string artifact_upload_url_template);
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
