namespace CadAi.CadEngine;

/// <summary>
/// An engine that reads CAD-IR itself instead of being handed a parsed plan.
/// </summary>
/// <remarks>
/// A second interface beside <see cref="ICadAdapter"/>, deliberately, and with a
/// deletion date: ENGINE-MIG-008 removes the plan-shaped one along with KOMPAS.
///
/// The reason there are two is that the migration moved the trust boundary.
/// Driving KOMPAS meant the last gate before COM was <see
/// cref="CadIrBuildPlanParser"/> — .NET read the document, resolved the
/// parameters, expanded the shapes and handed the adapter a plan. build123d is a
/// process that consumes the document with the *same* validator the API uses, so
/// the gate is inside it. Parsing the document again on this side to build a plan
/// would be a second opinion about what a valid document is, and two validators
/// that disagree is how a document becomes buildable on one side of a boundary
/// and refused on the other.
///
/// It also would not work: this parser cannot express a revolve and never will,
/// so a plan is no longer capable of carrying every document the contract allows.
/// </remarks>
public interface ICadDocumentEngine
{
    /// <summary>
    /// What the engine is, what it produces, and what it can build.
    /// </summary>
    /// <remarks>
    /// Asynchronous where <see cref="ICadAdapter.Describe"/> is not, because
    /// answering may mean asking the engine — and an engine that reported its
    /// own version from a constant on this side of the process boundary would be
    /// reporting what someone typed rather than what is installed.
    ///
    /// The flags are passed here as well as to a build on purpose. The manifest
    /// this produces is what the API schedules against, and the gate a build
    /// enforces has to be the same one, or the service advertises an operation it
    /// then refuses.
    /// </remarks>
    Task<CadEngineReport> DescribeAsync(
        IReadOnlyCollection<string> disabledCapabilities,
        CancellationToken cancellationToken);

    /// <summary>
    /// Would this engine accept the document? Nothing is built.
    /// </summary>
    /// <remarks>
    /// The repair loop's question. It has to know whether a document the AI just
    /// wrote is acceptable before paying for a build, and it has to be told by the
    /// thing that will do the accepting — a check on this side would be a second
    /// opinion, and two validators that disagree is how a document becomes valid
    /// on one side of a boundary and refused on the other.
    ///
    /// Returns what the document requires, which is also what makes a refusal
    /// legible: an operator reading `CAPABILITY_DISABLED` learns which operation
    /// the document wanted.
    /// </remarks>
    Task<IReadOnlyCollection<string>> ValidateAsync(
        CadDocumentValidateRequest request,
        CancellationToken cancellationToken);

    Task<CadBuildResult> BuildAsync(
        CadDocumentBuildRequest request,
        CancellationToken cancellationToken);
}

/// <summary>One job: where the document is, and what is switched off for it.</summary>
/// <remarks>
/// A directory rather than a pair of file paths. The engine's contract is a job
/// directory with `cad-ir.json` in it and an `output/` written beside it, and
/// naming the two files here would be this side deciding what the engine's
/// layout is.
/// </remarks>
public sealed record CadDocumentBuildRequest(
    string JobDirectory,
    IReadOnlyCollection<string> DisabledCapabilities);

/// <summary>A job to check, and optionally what the drawing was read as.</summary>
/// <remarks>
/// <paramref name="ShapeClaimPath"/> is what the reading stage said the part is —
/// the outline, the openings, how many solids, which parameter is the thickness.
/// The engine reports where the document contradicts it, which is the only way a
/// misread outline is ever caught: such a document is valid, builds, and measures
/// exactly what it claims to measure.
///
/// Absent for anything that did not come from a drawing. A manual document has no
/// claim and needs none.
/// </remarks>
public sealed record CadDocumentValidateRequest(
    string JobDirectory,
    IReadOnlyCollection<string> DisabledCapabilities,
    string? ShapeClaimPath = null);

/// <summary>One capability, as the engine declares it.</summary>
/// <remarks>
/// <paramref name="Status"/> is the maturity the API schedules against, and
/// `disabled` is one of its values rather than a separate field: a switched-off
/// operation must read as "no" outright and not as a low rung on the ladder.
///
/// <paramref name="Version"/> is the behaviour's version, independent of the
/// engine build, so the API can demand newer behaviour without demanding a whole
/// new worker.
/// </remarks>
public sealed record CadCapabilityDeclaration(string Status, string Version);

/// <summary>What an engine answered when asked to describe itself.</summary>
public sealed record CadEngineReport(
    CadEngineDescription Engine,
    IReadOnlyDictionary<string, CadCapabilityDeclaration> Capabilities);
