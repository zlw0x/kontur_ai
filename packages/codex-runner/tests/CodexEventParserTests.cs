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

    [Fact]
    public void RouterUsesConfiguredModelWithoutInventingFallbacks()
    {
        var router = new CodexModelRouter(
            new Dictionary<CodexStage, string?> { [CodexStage.CadIrCompilation] = "configured-model" });
        Assert.Equal(
            new CodexRoute("configured-model", "medium"),
            router.Route(CodexStage.CadIrCompilation));
        Assert.Null(router.Route(CodexStage.InputTriage).Model);
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
