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
        CancellationToken cancellationToken = default)
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
            var plan = await CadIrBuildPlanParser.ParseFileAsync(cadIrPath, cancellationToken);
            ICadAdapter adapter = fakeCad ? new FakeCadAdapter() : new KompasApi7Adapter();
            var result = await adapter.BuildAsync(new CadBuildRequest(plan, output), cancellationToken);
            GeometryValidationResult? validation = null;
            if (!fakeCad)
            {
                validation = GeometryValidator.Validate(
                    Path.Combine(output, "model.m3d"),
                    Path.Combine(output, "model.step"),
                    Path.Combine(output, "model.stl"),
                    new ExpectedGeometry(
                        plan.Width,
                        plan.Height,
                        plan.Depth,
                        SolidBodyCount: 1,
                        ThroughHoleCount: plan.CircularCuts?.Count ?? 0));
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
                    capabilities = new[] { "AI_DRAWING", "KOMPAS_BUILD" }, supported_cad_ir = new[] { "0.1.0" }, available_slots = 1
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
            var payload = await client.GetByteArrayAsync(input.download_url, cancellation);
            if (payload.LongLength != input.size_bytes || !ChecksumMatches(payload, input.sha256))
                throw new WorkerException("INPUT_INTEGRITY_FAILED", "Input checksum or size does not match manifest.");
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
                var drawing = await new DrawingPipeline(new CadAi.CodexRunner.LocalCodexRunner()).RunAsync(
                    jobPath,
                    images,
                    File.Exists(answersPath) ? answersPath : null,
                    cancellation);
                waitingForAnswers = drawing.Status == "WAITING_FOR_USER_ANSWERS";
                if (!waitingForAnswers)
                {
                    File.Copy(drawing.CadIrPath!, Path.Combine(jobPath, "cad-ir.json"), overwrite: true);
                    await LocalCadJobHandler.RunAsync(
                        jobPath, paths, fakeCad: false, cancellationToken: cancellation);
                }
            }
            else
            {
                await LocalCadJobHandler.RunAsync(
                    jobPath, paths, fakeCad: false, cancellationToken: cancellation);
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
                uploaded.Add(item);
            }
            if (!waitingForAnswers && uploaded.All(artifact => artifact.type != "M3D"))
                throw new WorkerException("ARTIFACT_UPLOAD_FAILED", "M3D artifact was not uploaded.");
            if (waitingForAnswers && uploaded.All(artifact => artifact.type != "CLARIFICATION_QUESTIONS"))
                throw new WorkerException("ARTIFACT_UPLOAD_FAILED", "Clarification questions were not uploaded.");
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
