using System.Text.Json;
using System.Text.Json.Serialization;

namespace CadAi.KompasAdapter;

/// <summary>
/// One selector in the acceptance set, and what it is there to prove.
/// </summary>
/// <remarks>
/// <see cref="ExpectedErrorCode"/> is not a concession. A selector that should
/// fail is as much a requirement as one that should match: an ambiguous
/// selector quietly returning its first candidate is precisely the defect this
/// milestone exists to make impossible, so the run asserts the failure.
/// </remarks>
public sealed record SelectorExpectation(
    GeometrySelector Selector,
    string? ExpectedErrorCode,
    string Purpose);

public sealed record SelectorMatch(
    [property: JsonPropertyName("index")] int Index,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("min")] double[] Min,
    [property: JsonPropertyName("max")] double[] Max,
    [property: JsonPropertyName("normal")] double[]? Normal);

public sealed record SelectorOutcome(
    [property: JsonPropertyName("selector_id")] string SelectorId,
    [property: JsonPropertyName("purpose")] string Purpose,
    [property: JsonPropertyName("expected_error_code")] string? ExpectedErrorCode,
    [property: JsonPropertyName("resolution")] SelectorResolution Resolution,
    [property: JsonPropertyName("matches")] IReadOnlyList<SelectorMatch> Matches)
{
    /// <summary>Did this selector do what it was declared to do?</summary>
    [JsonPropertyName("as_expected")]
    public bool AsExpected => Resolution.ErrorCode == ExpectedErrorCode;
}

public sealed record SelectorPhase(
    [property: JsonPropertyName("phase")] string Phase,
    [property: JsonPropertyName("face_count")] int FaceCount,
    [property: JsonPropertyName("edge_count")] int EdgeCount,
    [property: JsonPropertyName("read_ms")] long ReadMs,
    [property: JsonPropertyName("resolve_ms")] long ResolveMs,
    [property: JsonPropertyName("selectors")] IReadOnlyList<SelectorOutcome> Selectors);

public sealed record StabilityCheck(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("passed")] bool Passed,
    [property: JsonPropertyName("detail")] string Detail);

public sealed record SelectorStabilityReport(
    [property: JsonPropertyName("m3d_path")] string M3dPath,
    [property: JsonPropertyName("phases")] IReadOnlyList<SelectorPhase> Phases,
    [property: JsonPropertyName("checks")] IReadOnlyList<StabilityCheck> Checks)
{
    [JsonPropertyName("passed")]
    public bool Passed => Checks.All(check => check.Passed);

    public string ToJson() =>
        JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true });
}

/// <summary>
/// The selector set the acceptance run resolves, on a plate with two holes.
/// </summary>
/// <remarks>
/// Written against meaning rather than the plate's numbers wherever it can be,
/// because the point of the run is that widening the plate does not disturb
/// any of these.
/// </remarks>
public static class SelectorCatalogue
{
    public static IReadOnlyList<SelectorExpectation> AcceptancePlate(
        double holeRadiusMm,
        double thicknessMm) =>
    [
        new(
            new GeometrySelector(
                "top_face", SelectorKind.Face, "base", new Cardinality(CardinalityKind.ExactlyOne),
                Face: new FacePredicates(
                    SurfaceType: SurfaceType.Planar,
                    Normal: new NormalPredicate(ParallelTo: SelectorAxis.Z, Direction: AxisDirection.Positive),
                    Position: new PositionPredicate(
                        ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum))),
            null,
            "The face a fillet or a counterbore would be applied to; must survive a width change and a reopen."),

        new(
            new GeometrySelector(
                "hole_walls", SelectorKind.Face, "base", new Cardinality(CardinalityKind.ExactlyN, 2),
                Face: new FacePredicates(
                    SurfaceType: SurfaceType.Cylindrical,
                    RadiusMm: new Measurement(holeRadiusMm, 0.01))),
            null,
            "Both hole walls by radius: a declared count catches a third hole appearing."),

        new(
            new GeometrySelector(
                "hole_walls_by_area", SelectorKind.Face, "base", new Cardinality(CardinalityKind.ExactlyN, 2),
                Face: new FacePredicates(
                    SurfaceType: SurfaceType.Cylindrical,
                    AreaMm2: new Measurement(2 * Math.PI * holeRadiusMm * thicknessMm, 0.1))),
            null,
            "The same two walls by area, which is what catches a unit mistake in the topology reader."),

        new(
            new GeometrySelector(
                "side_face_ambiguous", SelectorKind.Face, "base", new Cardinality(CardinalityKind.ExactlyOne),
                Face: new FacePredicates(
                    SurfaceType: SurfaceType.Planar,
                    Normal: new NormalPredicate(ParallelTo: SelectorAxis.X))),
            "SELECTOR_AMBIGUOUS",
            "Two symmetric side faces match; resolution must refuse rather than pick one."),

        new(
            new GeometrySelector(
                "side_face_max_x", SelectorKind.Face, "base", new Cardinality(CardinalityKind.ExactlyOne),
                Face: new FacePredicates(
                    SurfaceType: SurfaceType.Planar,
                    Normal: new NormalPredicate(ParallelTo: SelectorAxis.X),
                    Position: new PositionPredicate(
                        ExtremeAlong: SelectorAxis.X, Extreme: ExtremeKind.Maximum))),
            null,
            "The same predicates plus a position: the repair a trace of the ambiguity would suggest."),

        new(
            new GeometrySelector(
                "top_hole_rims", SelectorKind.Edge, "base", new Cardinality(CardinalityKind.ExactlyN, 2),
                Edge: new EdgePredicates(
                    CurveType: CurveType.Circle,
                    RadiusMm: new Measurement(holeRadiusMm, 0.01),
                    Position: new PositionPredicate(
                        ExtremeAlong: SelectorAxis.Z, Extreme: ExtremeKind.Maximum))),
            null,
            "The edges a chamfer would break: four rims exist, the two on top are named.")
    ];

    /// <summary>
    /// The same selectors read against a plate that has grown a third hole.
    /// </summary>
    /// <remarks>
    /// Two claims at once. The selectors that were never about holes must be
    /// undisturbed by one appearing — that is the whole promise. The ones that
    /// declared "two" must now fail, because a document that says two mounting
    /// holes and finds three has a real disagreement in it, and silently
    /// operating on all three is how a part comes back wrong.
    /// </remarks>
    public static IReadOnlyList<SelectorExpectation> WithAThirdHole(
        IReadOnlyList<SelectorExpectation> catalogue) =>
        catalogue
            .Select(expectation => expectation.Selector.Cardinality.Kind == CardinalityKind.ExactlyN
                ? expectation with { ExpectedErrorCode = "SELECTOR_CARDINALITY_MISMATCH" }
                : expectation)
            .ToList();
}

/// <summary>
/// Decides whether a stability run proved what it set out to prove.
/// </summary>
/// <remarks>
/// Pure, over the recorded phases, so the verdict is testable without KOMPAS
/// and the run itself cannot quietly grade its own homework.
/// </remarks>
public static class SelectorStabilityChecks
{
    public static IReadOnlyList<StabilityCheck> Evaluate(
        IReadOnlyList<SelectorPhase> phases,
        double expectedThicknessMm)
    {
        var checks = new List<StabilityCheck>();

        if (phases.Count < 3)
        {
            checks.Add(new StabilityCheck("phases_recorded", false,
                $"Expected initial, widened and reopened phases; got {phases.Count}."));
            return checks;
        }
        checks.Add(new StabilityCheck("phases_recorded", true,
            string.Join(", ", phases.Select(phase => phase.Phase))));

        foreach (var phase in phases)
        {
            var wrong = phase.Selectors.Where(outcome => !outcome.AsExpected).ToList();
            checks.Add(new StabilityCheck(
                $"selectors_as_declared[{phase.Phase}]",
                wrong.Count == 0,
                wrong.Count == 0
                    ? $"{phase.Selectors.Count} selectors behaved as declared."
                    : string.Join("; ", wrong.Select(outcome =>
                        $"{outcome.SelectorId}: expected {outcome.ExpectedErrorCode ?? "a match"}, got {outcome.Resolution.ErrorCode ?? "a match"}"))));
        }

        // The claim under test: the same top face, whatever the plate's width
        // became and whichever process is holding the document.
        var tops = phases
            .Select(phase => (phase.Phase, Match: Single(phase, "top_face")))
            .ToList();
        var missing = tops.Where(entry => entry.Match is null).Select(entry => entry.Phase).ToList();
        if (missing.Count > 0)
        {
            checks.Add(new StabilityCheck("top_face_identified", false,
                $"No single top face in: {string.Join(", ", missing)}."));
            return checks;
        }

        var wrongFace = tops
            .Where(entry => !IsTopFace(entry.Match!, expectedThicknessMm))
            .Select(entry => $"{entry.Phase} -> z_max {entry.Match!.Max[2]:F3}, normal ({Format(entry.Match.Normal)})")
            .ToList();
        checks.Add(new StabilityCheck(
            "top_face_is_the_same_face",
            wrongFace.Count == 0,
            wrongFace.Count == 0
                ? $"Planar, +Z, z_max {expectedThicknessMm:F3} in every phase."
                : string.Join("; ", wrongFace)));

        // Evidence rather than a requirement. If the raw index moved, the
        // selector is demonstrably carrying the meaning; if it did not, the
        // run still proves nothing was silently index-dependent.
        var indexes = tops.Select(entry => entry.Match!.Index).ToList();
        checks.Add(new StabilityCheck(
            "top_face_index_observed",
            true,
            indexes.Distinct().Count() > 1
                ? $"Raw index moved across phases ({string.Join(" -> ", indexes)}); the selector still found it."
                : $"Raw index happened to stay {indexes[0]} in every phase."));

        var widened = phases.FirstOrDefault(phase => phase.Phase == "widened");
        var initial = phases.FirstOrDefault(phase => phase.Phase == "initial");
        if (initial is not null && widened is not null)
        {
            var before = Single(initial, "top_face");
            var after = Single(widened, "top_face");
            var grew = before is not null && after is not null &&
                       Width(after) > Width(before) + 1e-6;
            checks.Add(new StabilityCheck(
                "rebuild_actually_changed_the_model",
                grew,
                before is null || after is null
                    ? "Top face missing on one side of the rebuild."
                    : $"Top face width {Width(before):F3} -> {Width(after):F3} mm."));
        }

        return checks;
    }

    private static SelectorMatch? Single(SelectorPhase phase, string selectorId)
    {
        var outcome = phase.Selectors.FirstOrDefault(item => item.SelectorId == selectorId);
        return outcome is { Matches.Count: 1 } ? outcome.Matches[0] : null;
    }

    private static bool IsTopFace(SelectorMatch match, double thicknessMm) =>
        match.Kind == "planar" &&
        match.Normal is { Length: 3 } normal &&
        normal[2] > 0.999 &&
        Math.Abs(match.Max[2] - thicknessMm) <= 1e-3;

    private static double Width(SelectorMatch match) => match.Max[0] - match.Min[0];

    private static string Format(double[]? vector) =>
        vector is null ? "unmeasured" : string.Join(", ", vector.Select(value => value.ToString("F3")));
}
