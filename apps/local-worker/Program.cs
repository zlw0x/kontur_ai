using System.Text.Json;
using CadAi.LocalWorker;

try
{
    var paths = WorkerPaths.CreateDefault();
    var configStore = new WorkerConfigStore(paths);
    var credentialStore = new DpapiCredentialStore(paths);
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
                args.Contains("--fake-cad", StringComparer.OrdinalIgnoreCase));
        case "analyze-drawing":
            // --inject-cad-ir-fault is an acceptance affordance and is offered
            // here only. `run` serves real orders and must never reach it.
            return await DrawingJobHandler.RunAsync(
                args.Skip(1).FirstOrDefault(value => !value.StartsWith("--", StringComparison.Ordinal)),
                args.Contains("--inject-cad-ir-fault", StringComparer.OrdinalIgnoreCase));
        case "probe-kompas":
            return await KompasProbe.RunAsync();
        case "flags":
            return await FlagsCommand.RunAsync(args.Skip(1).ToArray(), paths);
        case "resolve-selectors":
            return await SelectorDiagnostic.RunAsync(args.Skip(1).ToArray(), paths);
        case "probe-codex":
            return await CodexProbe.RunAsync(paths);
        case "logout":
            credentialStore.Delete();
            Console.WriteLine(JsonSerializer.Serialize(new { status = "LOGGED_OUT" }));
            return 0;
        default:
            Console.Error.WriteLine("Usage: cad-worker doctor | enroll --server URL --token TOKEN | run [--once] | run-job PATH [--fake-cad] | analyze-drawing PATH [--inject-cad-ir-fault] | probe-kompas | probe-codex | resolve-selectors [DIR] | flags [--disable KEY] [--enable KEY] | logout");
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
