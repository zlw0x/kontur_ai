namespace CadAi.CodexRunner;

public enum CodexStage
{
    InputTriage,
    DrawingExtraction,
    GeometryReasoning,
    Clarification,
    CadPlanning,
    CadIrCompilation,
    Repair,
    FinalAudit
}

public sealed record CodexRoute(string? Model, string ReasoningEffort);

public sealed record CodexBudgetPolicy(int MaxRunsPerOrder = 10, int MaxRepairRuns = 3);

public sealed class CodexBudgetState
{
    public int TotalRuns { get; private set; }
    public int RepairRuns { get; private set; }

    public void Reserve(CodexStage stage, CodexBudgetPolicy policy)
    {
        if (TotalRuns >= policy.MaxRunsPerOrder ||
            (stage == CodexStage.Repair && RepairRuns >= policy.MaxRepairRuns))
            throw new CodexRunnerException(
                "CODEX_BUDGET_EXHAUSTED",
                "Codex run budget is exhausted; the job requires capacity or manual review.");
        TotalRuns++;
        if (stage == CodexStage.Repair) RepairRuns++;
    }
}

public sealed class CodexModelRouter
{
    private readonly IReadOnlyDictionary<CodexStage, string?> models;

    public CodexModelRouter(IReadOnlyDictionary<CodexStage, string?>? models = null)
    {
        this.models = models ?? new Dictionary<CodexStage, string?>();
    }

    public CodexRoute Route(CodexStage stage) => new(
        models.GetValueOrDefault(stage),
        stage switch
        {
            CodexStage.InputTriage => "low",
            CodexStage.DrawingExtraction => "medium",
            CodexStage.GeometryReasoning => "high",
            CodexStage.Clarification => "medium",
            CodexStage.CadPlanning => "high",
            CodexStage.CadIrCompilation => "medium",
            CodexStage.Repair => "high",
            CodexStage.FinalAudit => "high",
            _ => "medium"
        });
}
