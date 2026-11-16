using Microsoft.AspNetCore.Http;

namespace Masar.Api;

public sealed record CommercialOptions(bool Required, string? ContactUrl, int DailyExecutionLimit, string? SessionNamespace)
{
    public string CookieName(string suffix) =>
        SessionNamespace is null ? $"Masar.{suffix}" : $"Masar.{SessionNamespace}.{suffix}";
}
public sealed record AccessRequest(string? UserName);

public static class CommercialAccess
{
    // An explicit allowlist keeps newly added API routes protected by default.
    public static async Task Gate(HttpContext ctx, RequestDelegate next)
    {
        var path = ctx.Request.Path;
        var project = path.StartsWithSegments("/projects");
        var api = path.StartsWithSegments("/api");
        var exempt = path.StartsWithSegments("/api/v1/auth") ||
                     path.StartsWithSegments("/api/v1/admin") ||
                     path.Equals(new PathString("/api/v1/health")) ||
                     path.Equals(new PathString("/api/v1/catalog")) ||
                     path.Equals(new PathString("/api/v1/me/access"));
        if (project) ctx.Response.Headers.CacheControl = "no-store";
        if (ctx.RequestServices.GetRequiredService<CommercialOptions>().Required && (project || (api && !exempt)))
        {
            if (ctx.User.Identity?.IsAuthenticated != true)
                throw new ApiError(401, "unauthorized", "يلزم تسجيل الدخول.");
            if (!await HasAccess(ctx, ctx.RequestServices.GetRequiredService<Db>(), ctx.RequestAborted))
                throw new ApiError(403, "access_required", "يلزم تفعيل الوصول إلى المحتوى.");
        }
        await next(ctx);
    }

    private static async Task<bool> HasAccess(HttpContext ctx, Db db, CancellationToken ct)
    {
        // Staff require learning access for content management and review.
        if (ctx.User.IsInRole("Author") || ctx.User.IsInRole("Reviewer") || ctx.User.IsInRole("Admin")) return true;
        await using var conn = await db.Open(ct);
        return await Db.Scalar<bool>(conn, null,
            "SELECT EXISTS(SELECT 1 FROM public.commercial_access WHERE user_id=@user AND active)", ct,
            ("user", Input.UserId(ctx)));
    }

    public static void MapCommercialAccess(this WebApplication app)
    {
        app.MapGet("/api/v1/me/access", async (HttpContext ctx, Db db, CommercialOptions options, CancellationToken ct) =>
            Results.Ok(new { required = options.Required, active = !options.Required || await HasAccess(ctx, db, ct) }))
            .RequireAuthorization();
        if (app.Services.GetRequiredService<CommercialOptions>().Required)
        {
            app.MapPost("/api/v1/admin/access/grant", (AccessRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
                Change(request, ctx, db, true, ct)).RequireAuthorization(policy => policy.RequireRole("Admin"));
            app.MapPost("/api/v1/admin/access/revoke", (AccessRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
                Change(request, ctx, db, false, ct)).RequireAuthorization(policy => policy.RequireRole("Admin"));
        }
    }

    private static async Task<IResult> Change(AccessRequest request, HttpContext ctx, Db db, bool active, CancellationToken ct)
    {
        var name = Input.UserName(request.UserName);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var users = await Db.Query(conn, tx,
            "SELECT id FROM public.users WHERE normalized_user_name=@name FOR UPDATE", r => r.GetGuid(0), ct, ("name", name));
        if (users.Count == 0) throw ApiError.Missing();
        var user = users[0];
        await Db.Execute(conn, tx, """
            INSERT INTO public.commercial_access(user_id,active,updated_at)
            VALUES (@user,@active,now())
            ON CONFLICT(user_id) DO UPDATE SET active=EXCLUDED.active,updated_at=now()
            WHERE public.commercial_access.active IS DISTINCT FROM EXCLUDED.active
            """, ct, ("user", user), ("active", active));
        await Db.Audit(conn, tx, Input.UserId(ctx), active ? "access.grant" : "access.revoke", user.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        return Results.Ok(new { active });
    }
}
