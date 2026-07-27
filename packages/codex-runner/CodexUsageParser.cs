using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CadAi.CodexRunner;

/// <summary>
/// Where a token count came from. Pricing must be able to tell a measurement
/// from a guess, so this travels with the numbers rather than beside them.
/// </summary>
public enum CodexTokenSource
{
    Unknown,
    Structured,
    Summary,
    Estimated
}

/// <summary>
/// A usage reading. Every field is nullable on purpose: a CLI that does not
/// report a metric must leave it null rather than have a zero invented for it.
/// </summary>
public sealed record CodexUsageReading(
    CodexTokenSource Source,
    long? InputTokens = null,
    long? CachedInputTokens = null,
    long? OutputTokens = null,
    long? ReasoningTokens = null,
    long? TotalTokens = null)
{
    public static readonly CodexUsageReading Unknown = new(CodexTokenSource.Unknown);

    public bool Estimated => Source == CodexTokenSource.Estimated;
    public bool HasTokens =>
        InputTokens is not null || OutputTokens is not null ||
        ReasoningTokens is not null || TotalTokens is not null;
}

/// <summary>
/// Reads usage out of one Codex CLI output format.
/// </summary>
/// <remarks>
/// The CLI is upgraded independently of this service, and its output is not a
/// stable contract. Confining every string, regex and field name to a parser
/// means a CLI upgrade changes one implementation here and nothing in the
/// pipeline that consumes the numbers.
/// </remarks>
public interface ICodexUsageParser
{
    string Name { get; }

    bool CanParse(string? cliVersion, string outputFormat);

    CodexUsageReading Parse(IReadOnlyList<string> output);
}

/// <summary>
/// `codex exec --json` emits JSONL; the final `turn.completed` carries usage.
/// </summary>
public sealed class StructuredCodexUsageParser : ICodexUsageParser
{
    public string Name => "structured-jsonl";

    public bool CanParse(string? cliVersion, string outputFormat) =>
        string.Equals(outputFormat, "jsonl", StringComparison.OrdinalIgnoreCase);

    public CodexUsageReading Parse(IReadOnlyList<string> output)
    {
        for (var index = output.Count - 1; index >= 0; index--)
        {
            JsonDocument document;
            try { document = JsonDocument.Parse(output[index]); }
            catch (JsonException) { continue; }
            using (document)
            {
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object) continue;
                if (!root.TryGetProperty("type", out var type) || type.GetString() != "turn.completed")
                    continue;
                if (!root.TryGetProperty("usage", out var usage) || usage.ValueKind != JsonValueKind.Object)
                    continue;
                return new CodexUsageReading(
                    CodexTokenSource.Structured,
                    Number(usage, "input_tokens"),
                    Number(usage, "cached_input_tokens"),
                    Number(usage, "output_tokens"),
                    Number(usage, "reasoning_output_tokens") ?? Number(usage, "reasoning_tokens"),
                    Number(usage, "total_tokens"));
            }
        }
        return CodexUsageReading.Unknown;
    }

    // An absent or non-numeric field stays null. A field the CLI stopped
    // emitting must not silently become a zero in a cost calculation, and
    // TryGetInt64 throws on a non-number, so the kind is checked first.
    private static long? Number(JsonElement owner, string name) =>
        owner.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Number &&
        value.TryGetInt64(out var number) &&
        number >= 0
            ? number
            : null;
}

/// <summary>
/// Fallback for a CLI that prints a human summary instead of structured usage.
/// </summary>
public sealed class SummaryCodexUsageParser : ICodexUsageParser
{
    private static readonly Regex TokenLine = new(
        @"(?<name>input|cached input|cached|output|reasoning|total)\s*tokens?\s*[:=]\s*(?<value>[\d_,\s]+)",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public string Name => "summary-text";

    public bool CanParse(string? cliVersion, string outputFormat) => true;

    public CodexUsageReading Parse(IReadOnlyList<string> output)
    {
        long? input = null, cached = null, result = null, reasoning = null, total = null;
        foreach (var line in output)
        {
            foreach (Match match in TokenLine.Matches(line))
            {
                if (!TryNumber(match.Groups["value"].Value, out var value)) continue;
                switch (match.Groups["name"].Value.ToLowerInvariant())
                {
                    case "input": input = value; break;
                    case "cached": case "cached input": cached = value; break;
                    case "output": result = value; break;
                    case "reasoning": reasoning = value; break;
                    case "total": total = value; break;
                }
            }
        }
        return input is null && result is null && total is null && reasoning is null
            ? CodexUsageReading.Unknown
            : new CodexUsageReading(CodexTokenSource.Summary, input, cached, result, reasoning, total);
    }

    private static bool TryNumber(string text, out long value)
    {
        var digits = new string(text.Where(char.IsDigit).ToArray());
        return long.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out value);
    }
}

/// <summary>
/// Chooses a parser for the installed CLI and reports when it recognises none.
/// </summary>
/// <remarks>
/// An unrecognised CLI version must never fail a customer's order — the model
/// still produced valid CAD-IR. It degrades to an unknown reading and raises a
/// warning so the gap is visible in the ledger and can be fixed deliberately.
/// </remarks>
public sealed class CodexUsageParserRegistry
{
    /// <summary>CLI versions whose output format this build has fixtures for.</summary>
    public const string KnownVersionPrefix = "codex-cli 0.1";

    private readonly IReadOnlyList<ICodexUsageParser> parsers;

    public CodexUsageParserRegistry(IReadOnlyList<ICodexUsageParser>? parsers = null)
    {
        this.parsers = parsers ?? [new StructuredCodexUsageParser(), new SummaryCodexUsageParser()];
    }

    public static bool IsKnownVersion(string? cliVersion) =>
        cliVersion is not null &&
        cliVersion.StartsWith(KnownVersionPrefix, StringComparison.OrdinalIgnoreCase);

    public CodexUsageResolution Read(
        string? cliVersion,
        IReadOnlyList<string> output,
        string outputFormat = "jsonl")
    {
        foreach (var parser in parsers)
        {
            if (!parser.CanParse(cliVersion, outputFormat)) continue;
            var reading = parser.Parse(output);
            if (reading.HasTokens)
                return new CodexUsageResolution(reading, parser.Name, IsKnownVersion(cliVersion));
        }
        return new CodexUsageResolution(
            CodexUsageReading.Unknown, ParserName: null, IsKnownVersion(cliVersion));
    }
}

public sealed record CodexUsageResolution(
    CodexUsageReading Reading,
    string? ParserName,
    bool KnownCliVersion)
{
    /// <summary>
    /// True when the order should carry a warning event: usage could not be
    /// read, and the CLI version is one this build has never been tested with.
    /// </summary>
    public bool RequiresWarning => !KnownCliVersion || Reading.Source == CodexTokenSource.Unknown;
}
