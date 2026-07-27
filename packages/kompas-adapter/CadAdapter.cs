using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CadAi.KompasAdapter;

public sealed record RectangleExtrusionPlan(
    double CenterX,
    double CenterY,
    double Width,
    double Height,
    double Depth,
    IReadOnlyList<CircularCutPlan>? CircularCuts = null);

public sealed record CircularCutPlan(double CenterX, double CenterY, double Radius);

public sealed record CadBuildRequest(RectangleExtrusionPlan Plan, string OutputDirectory);

public sealed record CadArtifact(string Kind, string Path, long SizeBytes, string Sha256);

public sealed record CadBuildResult(IReadOnlyList<CadArtifact> Artifacts);

public interface ICadAdapter
{
    Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken);
}

public sealed class CadAdapterException(string code, string stage, string safeMessage, Exception? inner = null)
    : Exception(safeMessage, inner)
{
    public string Code { get; } = code;
    public string Stage { get; } = stage;
    public string SafeMessage { get; } = safeMessage;
}

public sealed class FakeCadAdapter : ICadAdapter
{
    public async Task<CadBuildResult> BuildAsync(CadBuildRequest request, CancellationToken cancellationToken)
    {
        var output = SafeOutputDirectory(request.OutputDirectory);
        Directory.CreateDirectory(output);
        var path = Path.Combine(output, "model.fake-cad.json");
        var payload = JsonSerializer.Serialize(new
        {
            adapter = "fake",
            geometry = "rectangle_extrusion",
            request.Plan.CenterX,
            request.Plan.CenterY,
            request.Plan.Width,
            request.Plan.Height,
            request.Plan.Depth
        });
        await File.WriteAllTextAsync(path, payload, Encoding.UTF8, cancellationToken);
        return new CadBuildResult([CreateArtifact("FAKE_CAD", path)]);
    }

    internal static string SafeOutputDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new CadAdapterException("OUTPUT_PATH_INVALID", "prepare", "CAD output directory is required.");
        return Path.GetFullPath(path);
    }

    internal static CadArtifact CreateArtifact(string kind, string path)
    {
        var info = new FileInfo(path);
        using var stream = File.OpenRead(path);
        return new CadArtifact(kind, path, info.Length, Convert.ToHexString(SHA256.HashData(stream)));
    }
}
