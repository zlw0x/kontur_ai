using CadAi.CodexRunner;
using Xunit;

namespace CadAi.CodexRunner.Tests;

public sealed class CodexRoutingTests
{
    [Fact]
    public void EveryStageIsRoutedToANamedModel()
    {
        var profile = new CodexRoutingProfile();

        foreach (CodexStage stage in Enum.GetValues<CodexStage>())
        {
            var decision = profile.Route(stage, "role");
            // An unrouted stage would inherit whatever the CLI defaults to,
            // which is the unattributable cost this whole step removes.
            Assert.False(string.IsNullOrWhiteSpace(decision.RequestedModel));
            Assert.False(string.IsNullOrWhiteSpace(decision.RequestedReasoningEffort));
            Assert.False(string.IsNullOrWhiteSpace(decision.RuleId));
            Assert.Equal(CodexRoutingProfile.CurrentVersion, decision.ProfileVersion);
        }
    }

    [Fact]
    public void ADecisionCarriesTheRuleThatProducedIt()
    {
        var decision = new CodexRoutingProfile().Route(CodexStage.DrawingExtraction, "drawing_analyzer");

        Assert.Equal("drawing.standard-analysis", decision.RuleId);
        Assert.Equal("gpt-5.6-terra", decision.RequestedModel);
        Assert.Equal("medium", decision.RequestedReasoningEffort);
        Assert.Equal("drawing_analyzer", decision.AgentRole);
        Assert.Equal("standard_single_part_drawing", decision.SelectionReason);
        Assert.Equal(0, decision.EscalationLevel);
    }

    [Fact]
    public void AStageWithNoRuleIsAnErrorRatherThanASilentDefault()
    {
        var sparse = new CodexRoutingProfile(
            new Dictionary<CodexStage, CodexRoutingRule>
            {
                [CodexStage.DrawingExtraction] = new("r", "m", "low", "why")
            },
            version: "test.1");

        var error = Assert.Throws<CodexRunnerException>(
            () => sparse.Route(CodexStage.Repair, "role"));
        Assert.Equal("CODEX_ROUTE_MISSING", error.Code);
    }

    [Fact]
    public void ModelIdentifiersComeFromTheProfileNotFromBusinessLogic()
    {
        var overridden = new CodexRoutingProfile(
            new Dictionary<CodexStage, CodexRoutingRule>
            {
                [CodexStage.Repair] = new("repair.escalated", "gpt-5.6-sol", "high", "hard_case", 1)
            },
            version: "2099-01-01.9");

        var decision = overridden.Route(CodexStage.Repair, "cad_ir_repairer");
        Assert.Equal("gpt-5.6-sol", decision.RequestedModel);
        Assert.Equal("2099-01-01.9", decision.ProfileVersion);
        Assert.Equal(1, decision.EscalationLevel);
    }

    [Fact]
    public void ObservationIsVerifiedOnlyWhenTheCliConfirmsTheModel()
    {
        var verified = CodexModelObservation.Compare("gpt-5.6-terra", "gpt-5.6-terra", "medium", "medium");
        Assert.Equal(CodexModelObservationStatus.Verified, verified.Status);
        Assert.True(verified.IsTrustworthy);
    }

    [Fact]
    public void AnExplicitRequestTheCliDoesNotEchoIsStillTrustworthy()
    {
        // codex-cli 0.145.0 reports no model at all, so this is where every
        // run lands today. The model was still chosen by us, on the command
        // line, above every config layer — that is enough to charge by.
        var explicitOnly = CodexModelObservation.Compare("gpt-5.6-terra", null, "medium", null);

        Assert.Equal(CodexModelObservationStatus.ExplicitNotReported, explicitOnly.Status);
        Assert.Equal("EXPLICIT_NOT_REPORTED", explicitOnly.StatusCode);
        Assert.True(explicitOnly.IsTrustworthy);
    }

    [Fact]
    public void ADisagreementIsNeverResolvedInFavourOfEitherModel()
    {
        var mismatch = CodexModelObservation.Compare("gpt-5.6-terra", "gpt-5.6-luna", "medium", "low");

        Assert.Equal(CodexModelObservationStatus.Mismatch, mismatch.Status);
        Assert.False(mismatch.IsTrustworthy);
        Assert.Equal("gpt-5.6-terra", mismatch.RequestedModel);
        Assert.Equal("gpt-5.6-luna", mismatch.ObservedModel);
    }

    [Fact]
    public void NeitherRequestedNorObservedIsUnknown()
    {
        var unknown = CodexModelObservation.Compare(null, null, null, null);

        Assert.Equal(CodexModelObservationStatus.Unknown, unknown.Status);
        Assert.False(unknown.IsTrustworthy);
    }

    [Fact]
    public void TheProvenanceFingerprintChangesWithEveryInputThatChangesTheAnswer()
    {
        var profile = new CodexRoutingProfile();
        var decision = profile.Route(CodexStage.DrawingExtraction, "drawing_analyzer");
        var baseline = CodexProvenance.Fingerprint("INPUT", "PROMPT", decision, "codex-cli 0.145.0");

        Assert.Equal(baseline, CodexProvenance.Fingerprint("INPUT", "PROMPT", decision, "codex-cli 0.145.0"));
        Assert.NotEqual(baseline, CodexProvenance.Fingerprint("OTHER", "PROMPT", decision, "codex-cli 0.145.0"));
        Assert.NotEqual(baseline, CodexProvenance.Fingerprint("INPUT", "OTHER", decision, "codex-cli 0.145.0"));
        Assert.NotEqual(baseline, CodexProvenance.Fingerprint("INPUT", "PROMPT", decision, "codex-cli 0.200.0"));
        Assert.NotEqual(
            baseline,
            CodexProvenance.Fingerprint(
                "INPUT", "PROMPT", decision with { RequestedModel = "gpt-5.6-sol" }, "codex-cli 0.145.0"));
        Assert.NotEqual(
            baseline,
            CodexProvenance.Fingerprint(
                "INPUT", "PROMPT", decision with { RequestedReasoningEffort = "high" }, "codex-cli 0.145.0"));
    }

    [Fact]
    public void TheRoutedModelIsPassedOnTheCommandLineAndTheUserConfigIsIgnored()
    {
        var decision = new CodexRoutingProfile().Route(CodexStage.DrawingExtraction, "drawing_analyzer");
        var request = new CodexStageRequest(
            "C:\\work", "C:\\work\\schema.json", "C:\\work\\out.json", "prompt",
            Model: decision.RequestedModel,
            ReasoningEffort: decision.RequestedReasoningEffort,
            Routing: decision);

        var arguments = LocalCodexRunner.BuildArguments(
            request, "C:\\work", "C:\\work\\schema.json", "C:\\work\\out.json", []);

        // Whatever the user has in ~/.codex/config.toml, this run cannot see
        // it, and the model it uses is the one the routing profile named.
        Assert.Contains("--ignore-user-config", arguments);
        var modelIndex = arguments.ToList().IndexOf("--model");
        Assert.True(modelIndex >= 0, "the model must always be named explicitly");
        Assert.Equal(decision.RequestedModel, arguments[modelIndex + 1]);
        Assert.Contains("model_reasoning_effort=\"medium\"", arguments);
    }

    [Fact]
    public void ChangingTheRoutingProfileChangesTheModelOnTheCommandLine()
    {
        var escalated = new CodexRoutingProfile(
            new Dictionary<CodexStage, CodexRoutingRule>
            {
                [CodexStage.DrawingExtraction] = new("d.escalated", "gpt-5.6-sol", "high", "hard", 1)
            },
            version: "test.1").Route(CodexStage.DrawingExtraction, "drawing_analyzer");

        var arguments = LocalCodexRunner.BuildArguments(
            new CodexStageRequest(
                "C:\\work", "C:\\work\\schema.json", "C:\\work\\out.json", "prompt",
                Model: escalated.RequestedModel,
                ReasoningEffort: escalated.RequestedReasoningEffort,
                Routing: escalated),
            "C:\\work", "C:\\work\\schema.json", "C:\\work\\out.json", []);

        var modelIndex = arguments.ToList().IndexOf("--model");
        Assert.Equal("gpt-5.6-sol", arguments[modelIndex + 1]);
        Assert.Contains("model_reasoning_effort=\"high\"", arguments);
    }

    [Fact]
    public void TheExecutionDescriptorCarriesNoLocalPaths()
    {
        var decision = new CodexRoutingProfile().Route(CodexStage.CadIrCompilation, "cad_ir_generator");

        var descriptor = CodexProvenance.ExecutionDescriptor(decision, "codex-cli 0.145.0");

        Assert.Contains("gpt-5.6-terra", descriptor);
        Assert.Contains("\"user_config\":\"ignored\"", descriptor);
        // The raw argument list would carry workspace paths and file names —
        // local detail with no business meaning in an exportable record.
        Assert.DoesNotContain("C:\\\\", descriptor);
        Assert.DoesNotContain("/jobs/", descriptor);
    }
}
