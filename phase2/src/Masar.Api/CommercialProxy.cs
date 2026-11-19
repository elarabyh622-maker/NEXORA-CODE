using System.Net;
using Microsoft.AspNetCore.HttpOverrides;

namespace Masar.Api;

// The TLS terminator is on this machine and replaces the forwarded headers.
internal sealed class CommercialProxy(Uri origin, PathString pathBase)
{
    private readonly HostString publicHost = HostString.FromUriComponent(origin);

    public PathString PathBase { get; } = pathBase;

    public static CommercialProxy? Read(IConfiguration config, bool commercial, bool development)
    {
        var value = config["MASAR_COMMERCIAL_PUBLIC_ORIGIN"];
        var path = config["MASAR_COMMERCIAL_PUBLIC_PATH"];
        if (value is null && path is null) return null;
        if (!commercial || development)
            throw new InvalidOperationException("Masar: commercial proxy requires commercial mode outside Development.");
        if (!Uri.TryCreate(value, UriKind.Absolute, out var origin) || origin.Scheme != "https" ||
            !origin.IsWellFormedOriginalString() || !string.IsNullOrEmpty(origin.UserInfo) ||
            origin.HostNameType is not (UriHostNameType.Dns or UriHostNameType.IPv4 or UriHostNameType.IPv6) ||
            origin.Port <= 0 || !string.Equals(value, origin.GetLeftPart(UriPartial.Authority), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Masar: MASAR_COMMERCIAL_PUBLIC_ORIGIN must be an HTTPS origin without a path, query or fragment.");
        if (path is not (null or "/nexora-commercial"))
            throw new InvalidOperationException("Masar: MASAR_COMMERCIAL_PUBLIC_PATH must be /nexora-commercial when set.");
        // ASP.NET Core's broad opt-in would run a separate forwarding middleware ahead of this one.
        if (string.Equals(config["ForwardedHeaders_Enabled"], "true", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Masar: use only the commercial forwarding profile.");
        return new CommercialProxy(origin, new PathString(path));
    }

    public static bool IsLoopbackListener(Uri address) => address.Query.Length == 0 && address.Fragment.Length == 0 &&
        (address.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase) ||
         (IPAddress.TryParse(address.IdnHost, out var ip) && IPAddress.IsLoopback(ip)));

    public void UseForwarding(WebApplication app)
    {
        if (PathBase.HasValue) app.UsePathBase(PathBase);

        // The public origin is a navigation entry point; authenticated API and
        // static-file requests remain restricted to the commercial mount.
        app.Use(async (ctx, next) =>
        {
            if (PathBase.HasValue && !ctx.Request.PathBase.HasValue && ctx.Request.Path == "/" &&
                (HttpMethods.IsGet(ctx.Request.Method) || HttpMethods.IsHead(ctx.Request.Method)) &&
                MatchesHost(ctx.Request.Host) && HasSingleHttpsHop(ctx.Request.Headers) &&
                ctx.Connection.RemoteIpAddress is { } peer && IPAddress.IsLoopback(peer))
            {
                ctx.Response.StatusCode = StatusCodes.Status308PermanentRedirect;
                ctx.Response.Headers.Location = PathBase.Value + "/";
                ctx.Response.Headers.CacheControl = "no-store";
                return;
            }
            await next(ctx);
        });

        var options = new ForwardedHeadersOptions
        {
            ForwardedHeaders = ForwardedHeaders.XForwardedProto | ForwardedHeaders.XForwardedFor,
            ForwardLimit = 1,
            RequireHeaderSymmetry = true
        };
        options.KnownIPNetworks.Clear();
        options.KnownIPNetworks.Add(new System.Net.IPNetwork(IPAddress.Parse("127.0.0.0"), 8));
        options.KnownProxies.Clear();
        options.KnownProxies.Add(IPAddress.IPv6Loopback);

        app.UseWhen(ctx => MatchesHost(ctx.Request.Host) && MatchesPath(ctx.Request.PathBase) && HasSingleHttpsHop(ctx.Request.Headers),
            branch => branch.UseForwardedHeaders(options));
    }

    public void RequirePublicTarget(HttpContext ctx)
    {
        if (!MatchesHost(ctx.Request.Host))
            throw new ApiError(StatusCodes.Status421MisdirectedRequest, "invalid_public_host", "عنوان الخدمة غير صالح.");
        if (!MatchesPath(ctx.Request.PathBase))
            throw new ApiError(StatusCodes.Status404NotFound, "not_found", "المورد غير موجود.");
    }

    private bool MatchesHost(HostString host) =>
        string.Equals(host.Value, publicHost.Value, StringComparison.OrdinalIgnoreCase) ||
        (origin.IsDefaultPort && string.Equals(host.Value, publicHost.Value + ":443", StringComparison.OrdinalIgnoreCase));

    private bool MatchesPath(PathString currentPathBase) =>
        !PathBase.HasValue || string.Equals(currentPathBase.Value, PathBase.Value, StringComparison.Ordinal);

    private static bool HasSingleHttpsHop(IHeaderDictionary headers) =>
        headers.TryGetValue("X-Forwarded-Proto", out var proto) && proto.Count == 1 &&
        string.Equals(proto[0], "https", StringComparison.OrdinalIgnoreCase) &&
        headers.TryGetValue("X-Forwarded-For", out var client) && client.Count == 1 && IPAddress.TryParse(client[0], out _);
}
