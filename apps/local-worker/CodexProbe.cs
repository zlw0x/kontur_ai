using System.Text.Json;
using CadAi.CodexRunner;

namespace CadAi.LocalWorker;

public static class CodexProbe
{
    private const string Schema =
        """
        {
          "$schema":"https://json-schema.org/draft/2020-12/schema",
          "type":"object",
          "required":["schema_version","stage","status","confidence","warnings","result"],
          "properties":{
            "schema_version":{"type":"string","const":"0.1.0"},
            "stage":{"type":"string","const":"runtime_probe"},
            "status":{"type":"string","const":"success"},
            "confidence":{"type":"number","minimum":0,"maximum":1},
            "warnings":{"type":"array","items":{"type":"string"}},
            "result":{
              "type":"object",
              "required":["message"],
              "properties":{"message":{"type":"string","const":"codex-local-auth-ok"}},
              "additionalProperties":false
            }
          },
          "additionalProperties":false
        }
        """;

    public static async Task<int> RunAsync(WorkerPaths paths)
    {
        var workspace = Path.Combine(paths.WorkspaceRoot, $"codex-probe-{Guid.NewGuid():N}");
        Directory.CreateDirectory(workspace);
        var schema = Path.Combine(workspace, "output.schema.json");
        var output = Path.Combine(workspace, "output", "result.json");
        await File.WriteAllTextAsync(schema, Schema);
        try
        {
            var runner = new LocalCodexRunner();
            var result = await runner.RunAsync(
                new CodexStageRequest(
                    workspace,
                    schema,
                    output,
                    """
                    This is a fixed local runtime health probe.
                    Do not use tools, do not execute commands, do not read files, and do not use the network.
                    Return only the JSON object required by the provided output schema.
                    """,
                    Timeout: TimeSpan.FromMinutes(3)));
            using var parsed = JsonDocument.Parse(await File.ReadAllBytesAsync(output));
            var message = parsed.RootElement.GetProperty("result").GetProperty("message").GetString();
            if (message != "codex-local-auth-ok")
                throw new WorkerException("CODEX_OUTPUT_INVALID", "Codex probe returned an unexpected result.");
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                status = "CODEX_OK",
                auth = "local-chatgpt",
                sandbox = "cad-runtime-read-only",
                result.ThreadId,
                result.Usage,
                result.OutputSha256,
                workspace
            }));
            return 0;
        }
        catch (CodexRunnerException error)
        {
            throw new WorkerException(error.Code, error.SafeMessage);
        }
    }
}
