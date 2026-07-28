namespace CadAi.CodexRunner;

/// <summary>
/// How much is actually known about which model served a run.
/// </summary>
public enum CodexModelObservationStatus
{
    /// <summary>Neither requested nor reported. Not allowed for new runs.</summary>
    Unknown,

    /// <summary>Requested on the command line; the CLI reported nothing back.</summary>
    ExplicitNotReported,

    /// <summary>The CLI confirmed the model that was requested.</summary>
    Verified,

    /// <summary>The CLI reported a different model than the one requested.</summary>
    Mismatch
}

/// <summary>
/// The gap between what was asked for and what can be confirmed.
/// </summary>
/// <remarks>
/// Kept as two fields plus a status rather than one `model`. Collapsing them
/// would make "we asked for Terra" indistinguishable from "Terra is what ran",
/// and only the second justifies charging Terra's weight.
///
/// On codex-cli 0.145.0 no event carries a model, so every explicit run lands
/// on <see cref="CodexModelObservationStatus.ExplicitNotReported"/>. Verified
/// becomes reachable the moment the CLI starts reporting one.
/// </remarks>
public sealed record CodexModelObservation(
    CodexModelObservationStatus Status,
    string? RequestedModel,
    string? ObservedModel,
    string? RequestedReasoningEffort,
    string? ObservedReasoningEffort)
{
    public bool IsTrustworthy =>
        Status is CodexModelObservationStatus.Verified
            or CodexModelObservationStatus.ExplicitNotReported;

    public static CodexModelObservation Compare(
        string? requestedModel,
        string? observedModel,
        string? requestedEffort,
        string? observedEffort)
    {
        var status = (requestedModel, observedModel) switch
        {
            (null or "", null or "") => CodexModelObservationStatus.Unknown,
            (null or "", _) => CodexModelObservationStatus.Unknown,
            (_, null or "") => CodexModelObservationStatus.ExplicitNotReported,
            var (requested, observed) when
                string.Equals(requested, observed, StringComparison.OrdinalIgnoreCase) =>
                CodexModelObservationStatus.Verified,
            _ => CodexModelObservationStatus.Mismatch
        };
        return new CodexModelObservation(
            status, requestedModel, observedModel, requestedEffort, observedEffort);
    }

    public string StatusCode => Status switch
    {
        CodexModelObservationStatus.Verified => "VERIFIED",
        CodexModelObservationStatus.ExplicitNotReported => "EXPLICIT_NOT_REPORTED",
        CodexModelObservationStatus.Mismatch => "MISMATCH",
        _ => "UNKNOWN"
    };
}
