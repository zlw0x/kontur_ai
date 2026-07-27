using CadAi.CodexRunner;
using Xunit;

namespace CadAi.CodexRunner.Tests;

public sealed class CodexUsageParserTests
{
    // Shape emitted by `codex exec --json` on the CLI this build was tested
    // against (codex-cli 0.145.0).
    private static readonly string[] StructuredRun =
    [
        """{"type":"thread.started","thread_id":"thread-1"}""",
        """{"type":"item.completed","item":{"type":"assistant_message"}}""",
        """{"type":"turn.completed","usage":{"input_tokens":12000,"cached_input_tokens":8000,"output_tokens":900,"reasoning_output_tokens":450,"total_tokens":12900}}"""
    ];

    [Fact]
    public void ReadsStructuredUsageFromTheTurnCompletion()
    {
        var resolution = new CodexUsageParserRegistry().Read("codex-cli 0.145.0", StructuredRun);

        Assert.Equal(CodexTokenSource.Structured, resolution.Reading.Source);
        Assert.Equal(12000, resolution.Reading.InputTokens);
        Assert.Equal(8000, resolution.Reading.CachedInputTokens);
        Assert.Equal(900, resolution.Reading.OutputTokens);
        Assert.Equal(450, resolution.Reading.ReasoningTokens);
        Assert.False(resolution.Reading.Estimated);
        Assert.False(resolution.RequiresWarning);
    }

    [Fact]
    public void FieldsTheCliDoesNotEmitStayNullInsteadOfBecomingZero()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            ["""{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}"""]);

        Assert.Equal(10, resolution.Reading.InputTokens);
        Assert.Null(resolution.Reading.CachedInputTokens);
        Assert.Null(resolution.Reading.ReasoningTokens);
        Assert.Null(resolution.Reading.TotalTokens);
    }

    [Fact]
    public void NegativeOrNonNumericCountsAreRejectedRatherThanTrusted()
    {
        // A string where a number belongs must not throw, and a negative count
        // must not be believed. With input and output both unusable the whole
        // reading degrades to unknown: reporting the leftover cached count on
        // its own would make the run look almost free.
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            ["""{"type":"turn.completed","usage":{"input_tokens":-5,"output_tokens":"many","cached_input_tokens":3}}"""]);

        Assert.Equal(CodexTokenSource.Unknown, resolution.Reading.Source);
        Assert.Null(resolution.Reading.InputTokens);
        Assert.Null(resolution.Reading.OutputTokens);
        Assert.True(resolution.RequiresWarning);
    }

    [Fact]
    public void APartiallyReadableUsageBlockKeepsTheCountsItCouldRead()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            ["""{"type":"turn.completed","usage":{"input_tokens":900,"output_tokens":"many","cached_input_tokens":300}}"""]);

        Assert.Equal(CodexTokenSource.Structured, resolution.Reading.Source);
        Assert.Equal(900, resolution.Reading.InputTokens);
        Assert.Equal(300, resolution.Reading.CachedInputTokens);
        Assert.Null(resolution.Reading.OutputTokens);
    }

    [Fact]
    public void TheLastTurnCompletionWins()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            [
                """{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}""",
                """{"type":"turn.completed","usage":{"input_tokens":50,"output_tokens":7}}"""
            ]);

        Assert.Equal(50, resolution.Reading.InputTokens);
    }

    [Fact]
    public void FallsBackToASummaryWhenNoStructuredUsageIsPresent()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            [
                "Codex finished the turn.",
                "tokens used: input tokens: 1_200, cached tokens: 400, output tokens: 88, total tokens: 1288"
            ]);

        Assert.Equal(CodexTokenSource.Summary, resolution.Reading.Source);
        Assert.Equal(1200, resolution.Reading.InputTokens);
        Assert.Equal(400, resolution.Reading.CachedInputTokens);
        Assert.Equal(88, resolution.Reading.OutputTokens);
        Assert.Equal(1288, resolution.Reading.TotalTokens);
    }

    [Fact]
    public void UsageThatCannotBeReadStaysUnknownAndAsksForAWarning()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            ["""{"type":"turn.completed"}""", "no numbers here"]);

        Assert.Equal(CodexTokenSource.Unknown, resolution.Reading.Source);
        Assert.False(resolution.Reading.HasTokens);
        Assert.True(resolution.RequiresWarning);
        Assert.Null(resolution.ParserName);
    }

    [Fact]
    public void AnUnknownCliVersionStillParsesButRaisesAWarning()
    {
        var registry = new CodexUsageParserRegistry();

        var future = registry.Read("codex-cli 9.9.9", StructuredRun);
        Assert.Equal(CodexTokenSource.Structured, future.Reading.Source);
        Assert.Equal(12000, future.Reading.InputTokens);
        // The numbers are used, but the untested version is surfaced so the
        // gap is fixed deliberately instead of being discovered in billing.
        Assert.True(future.RequiresWarning);
        Assert.False(future.KnownCliVersion);

        var absent = registry.Read(null, StructuredRun);
        Assert.True(absent.RequiresWarning);
    }

    [Fact]
    public void MalformedJsonlLinesAreSkippedRatherThanThrowing()
    {
        var resolution = new CodexUsageParserRegistry().Read(
            "codex-cli 0.145.0",
            ["not json at all", """{"type":"turn.completed","usage":{"input_tokens":4}}"""]);

        Assert.Equal(4, resolution.Reading.InputTokens);
    }

    [Fact]
    public void EventParserKeepsABoundedWindowForTheUsageRegistry()
    {
        var parser = new CodexEventParser();
        parser.Accept("""{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}""");
        for (var index = 0; index < 200; index++)
            parser.Accept(
                """{"type":"item.completed","item":{"type":"assistant_message","n":INDEX}}"""
                    .Replace("INDEX", index.ToString()));

        // The completion survives eviction even though 200 later lines arrived.
        Assert.True(parser.UsageCandidates.Count < 200);
        var resolution = new CodexUsageParserRegistry().Read("codex-cli 0.145.0", parser.UsageCandidates);
        Assert.Equal(5, resolution.Reading.InputTokens);
    }
}
