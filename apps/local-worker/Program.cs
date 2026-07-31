using CadAi.CadEngine;
using System.Text.Json;
using CadAi.LocalWorker;

try
{
    var paths = WorkerPaths.CreateDefault();
    var configStore = new WorkerConfigStore(paths);
    var credentialStore = CredentialStore.CreateDefault(paths);
    var command = args.FirstOrDefault()?.ToLowerInvariant() ?? "doctor";

    switch (command)
    {
        case "doctor":
            return await WorkerDoctor.RunAsync(configStore, credentialStore, paths);
        case "enroll":
            return await EnrollmentCommand.RunAsync(args.Skip(1).ToArray(), configStore, credentialStore);
        case "run":
            return await ClaimLoop.RunAsync(
                configStore,
                credentialStore,
                paths,
                CancellationToken.None,
                runOnce: args.Contains("--once", StringComparer.OrdinalIgnoreCase));
        case "run-job":
            return await LocalCadJobHandler.RunAsync(
                args.Skip(1).FirstOrDefault(value => !value.StartsWith("--", StringComparison.Ordinal)),
                paths,
                // The same engine `run` would use, so a job reproduced by hand
                // is built by the thing that built it in production.
                WorkerEngine.Select(
                    configStore.Load()?.CadEngine,
                    fake: args.Contains("--fake-cad", StringComparer.OrdinalIgnoreCase)));
        case "analyze-drawing":
            // --inject-cad-ir-fault is an acceptance affordance and is offered
            // here only. `run` serves real orders and must never reach it.
            return await DrawingJobHandler.RunAsync(
                args.Skip(1).FirstOrDefault(value => !value.StartsWith("--", StringComparison.Ordinal)),
                args.Contains("--inject-cad-ir-fault", StringComparer.OrdinalIgnoreCase));
        case "flags":
            return await FlagsCommand.RunAsync(args.Skip(1).ToArray(), paths, configStore);
        case "describe-engine":
            // What `probe-kompas` was for, without a desktop application to
            // probe: the engine says what it is and what it can build, and a
            // failure to answer is the thing an operator needed to find out.
            return await EngineDescribeCommand.RunAsync(paths, configStore);
        case "probe-codex":
            return await CodexProbe.RunAsync(paths);
        case "logout":
            credentialStore.Delete();
            Console.WriteLine(JsonSerializer.Serialize(new { status = "LOGGED_OUT" }));
            return 0;
        default:
            Console.Error.WriteLine("Usage: cad-worker doctor | enroll --server URL --token TOKEN | run [--once] | run-job PATH [--fake-cad] | analyze-drawing PATH [--inject-cad-ir-fault] | describe-engine | probe-codex | flags [--disable KEY] [--enable KEY] | logout");
            return 2;
    }
}
catch (WorkerException error)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new { status = "FAILED", code = error.Code, message = error.SafeMessage }));
    return error.ExitCode;
}
catch (Exception)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new { status = "FAILED", code = "INTERNAL_ERROR", message = "Worker operation failed." }));
    return 1;
}
