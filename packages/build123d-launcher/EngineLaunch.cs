namespace CadAi.Build123dLauncher;

using CadAi.CadEngine;

/// <summary>How the engine process is started, and what it is given.</summary>
/// <remarks>
/// Two modes, both with the argument list built here rather than templated from
/// configuration. That is deliberate and it is a security property, not a
/// convenience: a configurable argv is a place for a string to become an
/// argument, and this process exists to run a fixed program on an untrusted
/// document. Configuration says <em>where</em> the engine is; it never says what
/// to pass it.
///
/// <see cref="EngineRuntime.Container"/> is the shape ADR-023 describes and the
/// one production uses — a read-only root, no network, one bind mount for the
/// job. <see cref="EngineRuntime.Process"/> runs the same entry point through a
/// local interpreter, which is what a developer machine and the acceptance runs
/// use, and it is the mode with fewer guarantees rather than the default.
/// </remarks>
public enum EngineRuntime
{
    Container,
    Process
}

public sealed record EngineLaunchOptions
{
    /// <summary>Container by default: the mode with the isolation.</summary>
    public EngineRuntime Runtime { get; init; } = EngineRuntime.Container;

    /// <summary>The container runtime binary. `podman` works as well as `docker`.</summary>
    public string ContainerCommand { get; init; } = "docker";

    /// <summary>The image tag to run. Pinned by whoever deploys, not by this code.</summary>
    public string Image { get; init; } = "cad-ai/cad-worker:latest";

    /// <summary>The interpreter, for <see cref="EngineRuntime.Process"/>.</summary>
    public string PythonCommand { get; init; } = "python";

    /// <summary>
    /// Where the interpreter is run from, so `python -m cad_worker` resolves.
    /// Ignored in container mode, where the image already knows.
    /// </summary>
    public string? WorkingDirectory { get; init; }

    /// <summary>
    /// Environment the child is given on top of this process's own.
    /// </summary>
    /// <remarks>
    /// For <see cref="EngineRuntime.Process"/>, where something has to tell the
    /// interpreter where the packages are; the image bakes that in. Deliberately
    /// not a way to pass anything about a job: the document's contents never
    /// reach an argument, and they do not reach the environment either.
    /// </remarks>
    public IReadOnlyDictionary<string, string> Environment { get; init; } =
        new Dictionary<string, string>();

    /// <summary>
    /// How long one build may take before the process is killed.
    /// </summary>
    /// <remarks>
    /// A wall-clock limit belongs on this side rather than inside the engine: a
    /// process wedged in the kernel cannot time itself out, which is the case the
    /// limit exists for.
    /// </remarks>
    public TimeSpan BuildTimeout { get; init; } = TimeSpan.FromMinutes(15);

    /// <summary>Describing is a version lookup, not a build.</summary>
    public TimeSpan DescribeTimeout { get; init; } = TimeSpan.FromSeconds(60);
}

/// <summary>The command line for one invocation of the engine.</summary>
public sealed record EngineInvocation(string FileName, IReadOnlyList<string> Arguments);

internal static class EngineCommandLine
{
    /// <summary>Where the job directory is mounted inside the container.</summary>
    internal const string ContainerJobPath = "/work";

    internal static EngineInvocation Describe(
        EngineLaunchOptions options,
        IReadOnlyCollection<string> disabled) =>
        options.Runtime == EngineRuntime.Container
            ? new EngineInvocation(
                options.ContainerCommand,
                [.. ContainerPrefix(options, jobDirectory: null), "describe", .. Flags(disabled)])
            : new EngineInvocation(
                options.PythonCommand,
                ["-m", "cad_worker", "describe", .. Flags(disabled)]);

    internal static EngineInvocation Build(
        EngineLaunchOptions options,
        string jobDirectory,
        IReadOnlyCollection<string> disabled)
    {
        var job = RequireRootedPath(jobDirectory);
        return options.Runtime == EngineRuntime.Container
            ? new EngineInvocation(
                options.ContainerCommand,
                [
                    .. ContainerPrefix(options, job),
                    "build", "--job", ContainerJobPath,
                    .. Flags(disabled)
                ])
            : new EngineInvocation(
                options.PythonCommand,
                ["-m", "cad_worker", "build", "--job", job, .. Flags(disabled)]);
    }

    private static IReadOnlyList<string> ContainerPrefix(
        EngineLaunchOptions options,
        string? jobDirectory)
    {
        List<string> arguments =
        [
            "run", "--rm",
            // Everything ADR-023 asks for, stated on every invocation rather
            // than left to how the image happens to be run. A container that
            // could reach the network during a build would make the engine one
            // more thing with an outbound path from a trusted machine.
            "--read-only",
            "--network", "none",
            // Not root inside the container either; the image creates this user
            // and this repeats it so a rebuilt image cannot quietly drop it.
            "--user", "10001:10001",
            // The read-only root leaves nowhere to write, and the engine needs a
            // scratch directory for one dependency's cache.
            "--tmpfs", "/tmp"
        ];
        if (jobDirectory is not null)
        {
            arguments.Add("--mount");
            arguments.Add($"type=bind,src={jobDirectory},dst={ContainerJobPath}");
        }
        arguments.Add(options.Image);
        return arguments;
    }

    private static IEnumerable<string> Flags(IReadOnlyCollection<string> disabled) =>
        disabled.Order(StringComparer.Ordinal).SelectMany(key => new[] { "--disable", key });

    /// <summary>
    /// The job directory, absolute, or a typed refusal.
    /// </summary>
    /// <remarks>
    /// A relative path would resolve against whatever the child process happens
    /// to start in, which in container mode is not even the same filesystem. The
    /// check also states the rule that keeps this safe: the only value this
    /// side puts on a command line is a path the worker itself chose, and it has
    /// to look like one.
    /// </remarks>
    private static string RequireRootedPath(string jobDirectory)
    {
        if (string.IsNullOrWhiteSpace(jobDirectory) || !Path.IsPathRooted(jobDirectory))
            throw new CadAdapterException(
                "OUTPUT_PATH_INVALID",
                "prepare",
                "The job directory handed to the CAD engine must be an absolute path.");
        return Path.GetFullPath(jobDirectory);
    }
}
