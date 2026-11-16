using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Masar.Api;

internal sealed class CodeLabRunner : IDisposable
{
    private const int MaximumResponseBytes = 112 * 1024;
    private const int MaximumOutputBytes = 16 * 1024;
    private readonly Uri? endpoint;
    private readonly AuthenticationHeaderValue? authorization;
    private readonly HttpClient client = new(new SocketsHttpHandler
    {
        AllowAutoRedirect = false,
        UseCookies = false,
        UseProxy = false,
        MaxResponseHeadersLength = 16
    }) { Timeout = Timeout.InfiniteTimeSpan };

    public CodeLabRunner()
    {
        var url = Environment.GetEnvironmentVariable("MASAR_CODE_LAB_RUNNER_URL");
        var token = Environment.GetEnvironmentVariable("MASAR_CODE_LAB_RUNNER_TOKEN");
        if (!bool.TryParse(Environment.GetEnvironmentVariable("MASAR_CODE_LAB_ENABLED"), out var enabled) || !enabled ||
            !Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
            !(uri.Scheme == Uri.UriSchemeHttps || uri.Scheme == Uri.UriSchemeHttp && IsLoopback(uri)) ||
            uri.AbsolutePath != "/" || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0 ||
            token is null || token.Length is < 32 or > 128 ||
            !token.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_'))
        {
            return;
        }

        endpoint = new Uri(uri, "/v1/execute");
        authorization = new AuthenticationHeaderValue("Bearer", token);
    }

    public bool Available => endpoint is not null;

    private static bool IsLoopback(Uri uri) => uri.Host == "localhost" ||
        IPAddress.TryParse(uri.IdnHost, out var ip) && IPAddress.IsLoopback(ip);

    public async Task<ExecutionResult> Execute(string language, string code, string stdin, CancellationToken ct)
    {
        if (endpoint is null) return ExecutionResult.InfrastructureError;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(25));
        var bounded = deadline.Token;
        try
        {
            // The broker accepts a bounded, length-framed JSON body.
            var payload = JsonSerializer.SerializeToUtf8Bytes(new { language, code, stdin });
            using var request = new HttpRequestMessage(HttpMethod.Post, endpoint)
            {
                Content = new ByteArrayContent(payload)
            };
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
            request.Headers.Authorization = authorization;
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, bounded);
            if (!response.IsSuccessStatusCode || response.Content.Headers.ContentLength > MaximumResponseBytes)
                return ExecutionResult.InfrastructureError;

            await using var source = await response.Content.ReadAsStreamAsync(bounded);
            // Bound streamed responses even when Content-Length is absent or inaccurate.
            var buffer = new byte[MaximumResponseBytes + 1];
            var length = await source.ReadAtLeastAsync(buffer, buffer.Length, false, bounded);
            if (length > MaximumResponseBytes) return ExecutionResult.InfrastructureError;

            using var document = JsonDocument.Parse(buffer.AsMemory(0, length), new JsonDocumentOptions { MaxDepth = 4 });
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object ||
                !TryReadString(root, "status", out var status) ||
                !TryReadString(root, "stdout", out var stdout) ||
                !TryReadString(root, "stderr", out var stderr) ||
                Encoding.UTF8.GetByteCount(stdout) + Encoding.UTF8.GetByteCount(stderr) > MaximumOutputBytes ||
                status is not ("completed" or "timed_out" or "output_limit" or "code_error"))
            {
                return ExecutionResult.InfrastructureError;
            }

            return new ExecutionResult(status, stdout, stderr);
        }
        catch (Exception ex) when (!ct.IsCancellationRequested &&
            ex is HttpRequestException or IOException or JsonException or InvalidOperationException or OperationCanceledException)
        {
            return ExecutionResult.InfrastructureError;
        }
    }

    private static bool TryReadString(JsonElement root, string name, out string value)
    {
        value = "";
        if (!root.TryGetProperty(name, out var item) || item.ValueKind != JsonValueKind.String) return false;
        value = item.GetString()!;
        return true;
    }

    public void Dispose() => client.Dispose();
}

internal sealed record ExecutionResult(string Status, string Stdout, string Stderr)
{
    public static ExecutionResult InfrastructureError { get; } = new("infrastructure_error", "", "");
}
