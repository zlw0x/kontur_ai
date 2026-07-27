using CadAi.GeometryValidation;
using Xunit;

namespace CadAi.GeometryValidation.Tests;

public sealed class GeometryValidatorTests
{
    [Fact]
    public void ClosedAsciiTetrahedronPassesStructuralChecks()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cad-ai-validation-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var m3d = Path.Combine(root, "model.m3d");
            var step = Path.Combine(root, "model.step");
            var stl = Path.Combine(root, "model.stl");
            File.WriteAllText(m3d, "m3d");
            File.WriteAllText(step, "ISO-10303-21;\nEND-ISO-10303-21;");
            File.WriteAllText(stl,
                """
                solid tetra
                  facet normal 0 0 -1
                    outer loop
                      vertex 0 0 0
                      vertex 0 1 0
                      vertex 1 0 0
                    endloop
                  endfacet
                  facet normal 0 -1 0
                    outer loop
                      vertex 0 0 0
                      vertex 1 0 0
                      vertex 0 0 1
                    endloop
                  endfacet
                  facet normal -1 0 0
                    outer loop
                      vertex 0 0 0
                      vertex 0 0 1
                      vertex 0 1 0
                    endloop
                  endfacet
                  facet normal 1 1 1
                    outer loop
                      vertex 1 0 0
                      vertex 0 1 0
                      vertex 0 0 1
                    endloop
                  endfacet
                endsolid tetra
                """);

            var result = GeometryValidator.Validate(m3d, step, stl, new ExpectedGeometry(1, 1, 1, 1, 0));
            Assert.True(result.Valid);
            Assert.Equal(4u, result.Mesh.TriangleCount);
            Assert.Equal(0, result.Mesh.Genus);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void MissingStlFailsClosed()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cad-ai-validation-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllText(Path.Combine(root, "model.m3d"), "m3d");
            File.WriteAllText(Path.Combine(root, "model.step"), "ISO-10303-21;\nEND-ISO-10303-21;");
            Assert.Throws<InvalidDataException>(() => GeometryValidator.Validate(
                Path.Combine(root, "model.m3d"),
                Path.Combine(root, "model.step"),
                Path.Combine(root, "model.stl"),
                new ExpectedGeometry(40, 20, 10, 1, 0)));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void TruncatedBinaryStlFailsClosed()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllBytes(path, new byte[83]);
            var error = Assert.Throws<InvalidDataException>(() => GeometryValidator.Validate(
                path, path, path, new ExpectedGeometry(1, 1, 1, 1, 0)));
            Assert.Contains("shorter", error.Message);
        }
        finally
        {
            File.Delete(path);
        }
    }
}
