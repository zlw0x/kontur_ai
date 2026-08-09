namespace CadAi.LocalWorker;

/// <summary>
/// What this worker last saw of its own Codex CLI, as the API is told it.
/// </summary>
/// <remarks>
/// A different fact from `codex_cli_version`, which the capability manifest already
/// carries: that says which version is *installed*, and says nothing about whether
/// it can answer. The difference was measured rather than imagined — the account's
/// quota ran out until a stated date, and orders went on being handed to workers
/// that returned `CODEX_CAPACITY_LIMIT` the moment they read the manifest. Three
/// leases and three failures per order, every one predictable from the first, and
/// the customer's page said "no worker has capacity", which was true and was not the
/// reason.
///
/// An **observation**, not a promise. It says what happened the last time this worker
/// asked Codex for something, and the API believes it until the next heartbeat.
///
/// Two shapes of "cannot", and the split matters:
///
///   paused       comes back on a date, and this says which. An exhausted quota.
///   unavailable  comes back when somebody installs or signs in. No date, because a
///                date on that would be a promise nobody made.
///
/// The starting value is <see cref="Available"/> rather than "unknown", and that is
/// a fix for a deadlock rather than optimism: the API withholds drawing work from a
/// worker that says it cannot do it, and the only thing that clears such a state is
/// a run that succeeds. A worker that started silent would leave a stored
/// `unavailable` behind with no way to contradict it — a machine somebody has just
/// fixed, still refused.
/// </remarks>
internal sealed record CodexHealth(string State, DateTimeOffset? RetryAfter, string? Detail)
{
    internal static readonly CodexHealth Available = new("available", null, null);

    /// <summary>
    /// What a failed run says about the CLI, for the codes that say anything.
    /// </summary>
    /// <remarks>
    /// Called only for codes <see cref="BuildFeedback.ModelCouldNotBeReached"/>
    /// admits. Everything else — a document that will not compile, a claim that
    /// disagrees, a kernel that refused — is the model answering, and answering badly
    /// is not the same as being unreachable.
    ///
    /// The horizon is `BuildFeedback.PauseFor`, the same hour a paused job waits, and
    /// for the same reason it was chosen there: the CLI states its reset time only as
    /// prose, and parsing prose is a weakness `MapExit` already has in a place where
    /// being wrong means an order sleeps until a date nobody meant.
    /// </remarks>
    internal static CodexHealth From(string code, string message) =>
        BuildFeedback.ModelNeedsAPerson(code)
            ? new CodexHealth("unavailable", null, Safe(code, message))
            : new CodexHealth("paused", DateTimeOffset.UtcNow + BuildFeedback.PauseFor, Safe(code, message));

    /// <summary>The shape the API's `CodexAvailability` expects.</summary>
    internal object AsPayload() => new
    {
        state = State,
        retry_after = RetryAfter,
        detail = Detail,
    };

    /// <summary>
    /// Text a status page may show, bounded and stripped of anything local.
    /// </summary>
    /// <remarks>
    /// The same rule a failure message already follows: everything sent here can
    /// reach a browser, so it carries no path, no host and no stack. The code is
    /// included because it is the one part an operator can search for.
    /// </remarks>
    private static string Safe(string code, string message)
    {
        var text = $"{code}: {message}".ReplaceLineEndings(" ").Trim();
        return text.Length > 300 ? text[..300] : text;
    }
}
