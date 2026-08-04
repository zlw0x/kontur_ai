using CadAi.CodexRunner;
using System.Text.Json;
using Xunit;

namespace CadAi.CodexRunner.Tests;

public sealed class CodexEventParserTests
{
    [Fact]
    public void ParsesThreadAndUsage()
    {
        var parser = new CodexEventParser();
        parser.Accept("""{"type":"thread.started","thread_id":"thread-1"}""");
        parser.Accept(
            """
            {"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":2}}
            """);
        Assert.Equal("thread-1", parser.ThreadId);
        Assert.Equal(new CodexUsage(10, 4, 3, 2), parser.Usage);
        Assert.False(parser.Failed);
    }

    [Theory]
    [InlineData("command_execution")]
    [InlineData("file_change")]
    [InlineData("mcp_tool_call")]
    [InlineData("web_search")]
    public void DetectsForbiddenRuntimeToolUse(string itemType)
    {
        var parser = new CodexEventParser();
        parser.Accept(JsonSerializer.Serialize(new { type = "item.started", item = new { type = itemType } }));
        Assert.True(parser.ToolUseDetected);
    }

    [Fact]
    public void RejectsMalformedJsonl()
    {
        var parser = new CodexEventParser();
        var error = Assert.Throws<CodexRunnerException>(() => parser.Accept("not-json"));
        Assert.Equal("CODEX_PROTOCOL_INVALID", error.Code);
    }

    [Fact]
    public void CapturesFailureForCapacityMapping()
    {
        var parser = new CodexEventParser();
        parser.Accept("""{"type":"error","message":"rate limit reached"}""");
        Assert.True(parser.Failed);
        Assert.Contains("rate limit", parser.ErrorText);
    }

    /// <summary>
    /// An exhausted account quota, exactly as the CLI reported one.
    /// </summary>
    /// <remarks>
    /// Recorded verbatim from a real run, because the code it maps to is what the
    /// worker decides from and it is not the code the failure looks like:
    /// `CODEX_BUDGET_EXHAUSTED` is this worker's own per-order run counter and never
    /// comes from the CLI. The quota arrives as `CODEX_CAPACITY_LIMIT`, and a worker
    /// classifying only the other one would retry the quota exactly as before.
    /// </remarks>
    [Fact]
    public void AnExhaustedQuotaIsACapacityLimitAndNotABudget()
    {
        var parser = new CodexEventParser();
        parser.Accept(
            """{"type":"error","message":"You've hit your usage limit. Try again at Aug 8th, 2026 8:44 AM."}""");
        parser.Accept("""{"type":"turn.failed"}""");

        Assert.True(parser.Failed);
        Assert.Equal("CODEX_CAPACITY_LIMIT", LocalCodexRunner.MapExit(parser));
    }

    /// <remarks>
    /// The other side of the same mapping, and the reason the retry stays the default:
    /// a failure whose text says nothing about limits is one another attempt may get
    /// past.
    /// </remarks>
    [Fact]
    public void AFailureThatSaysNothingAboutLimitsIsWorthAnotherAttempt()
    {
        var parser = new CodexEventParser();
        parser.Accept("""{"type":"error","message":"connection reset by peer"}""");

        Assert.Equal("CODEX_RUN_FAILED", LocalCodexRunner.MapExit(parser));
    }

    [Fact]
    public void BudgetRejectsRunsBeforeStartingAnotherProcess()
    {
        var state = new CodexBudgetState();
        var policy = new CodexBudgetPolicy(MaxRunsPerOrder: 2, MaxRepairRuns: 1);
        state.Reserve(CodexStage.Repair, policy);
        var repair = Assert.Throws<CodexRunnerException>(
            () => state.Reserve(CodexStage.Repair, policy));
        Assert.Equal("CODEX_BUDGET_EXHAUSTED", repair.Code);
        state.Reserve(CodexStage.FinalAudit, policy);
        Assert.Throws<CodexRunnerException>(() => state.Reserve(CodexStage.InputTriage, policy));
    }
}
