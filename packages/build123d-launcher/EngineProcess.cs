namespace CadAi.Build123dLauncher;

using System.Diagnostics;
using System.Text;

/// <summary>What one run of the engine produced.</summary>
public sealed record EngineProcessResult(int ExitCode, string StandardOutput, string StandardError);

/// <summary>
/// Starting the engine, behind an interface so the launcher can be tested.
/// </summary>
/// <remarks>
/// Every interesting case in the launcher is a way the child can answer: a typed
/// refusal, a crash with nothing on stdout, output that is not JSON, a manifest
/// that disagrees with the flags it was given. Reproducing those with a real
/// process would mean shipping a fake engine executable and a way to build it on
/// two operating systems; reproducing them behind this interface is a record.
/// </remarks>
public interface IEngineProcessRunner
{
    Task<EngineProcessResult> RunAsync(
        EngineInvocation invocation,
        EngineLaunchOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

/// <summary>Runs the engine as a child process.</summary>
public sealed class EngineProcessRunner : IEngineProcessRunner
{
    /// <summary>
    /// How much of a stream is kept.
    /// </summary>
    /// <remarks>
    /// An engine that failed by printing a hundred megabytes of traceback should
    /// not be able to exhaust the worker's memory on the way out.
    /// </remarks>
    private const int MaxStreamBytes = 1 << 20;

    public async Task<EngineProcessResult> RunAsync(
        EngineInvocation invocation,
        EngineLaunchOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var start = new ProcessStartInfo
        {
            FileName = invocation.FileName,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // No shell. The arguments are added one at a time to the collection
            // rather than joined into a string, so nothing is ever re-parsed by
            // anything and a space in a path is a space in a path.
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var argument in invocation.Arguments) start.ArgumentList.Add(argument);
        foreach (var (name, value) in options.Environment) start.Environment[name] = value;
        if (!string.IsNullOrWhiteSpace(options.WorkingDirectory))
            start.WorkingDirectory = options.WorkingDirectory;

        using var process = new Process { StartInfo = start };
        var output = new StringBuilder();
        var error = new StringBuilder();
        process.OutputDataReceived += (_, line) => Append(output, line.Data);
        process.ErrorDataReceived += (_, line) => Append(error, line.Data);

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(deadline.Token);
        }
        catch (OperationCanceledException)
        {
            // Killed with its children: the container runtime's client is not
            // the container, and leaving the build running would hold the job
            // directory open after the worker has given up on it.
            TryKill(process);
            throw;
        }
        return new EngineProcessResult(process.ExitCode, output.ToString(), error.ToString());

        static void Append(StringBuilder target, string? line)
        {
            if (line is null || target.Length > MaxStreamBytes) return;
            target.AppendLine(line);
        }
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
        catch (Exception error) when (error is InvalidOperationException or NotSupportedException)
        {
            // It exited between the check and the kill, or the platform will not
            // walk the tree. Either way there is nothing further to do, and
            // throwing here would replace the timeout with a worse error.
        }
    }
}
