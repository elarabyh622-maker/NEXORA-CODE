using System.Collections.Frozen;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Npgsql;

namespace Masar.Api;

public sealed record CommercialOptions(bool Required, string? ContactUrl, int DailyExecutionLimit, string? SessionNamespace)
{
    public string CookieName(string suffix) =>
        SessionNamespace is null ? $"Masar.{suffix}" : $"Masar.{SessionNamespace}.{suffix}";
}
public sealed record AccessRequest(string? UserName, string? GoalId = null, string? LessonId = null);
public sealed record OfferRequest(decimal? Price, string? Currency);

internal sealed class ScopedCommercialEndpoint;

internal sealed record CommercialOffer(string GoalId, decimal Price, string Currency);

internal sealed record CommercialEntitlements(bool FullAccess, IReadOnlySet<string> GoalIds, IReadOnlySet<string> LessonIds)
{
    private static readonly FrozenSet<string> EmptyIds = Array.Empty<string>().ToFrozenSet(StringComparer.Ordinal);
    internal static readonly CommercialEntitlements None = new(false, EmptyIds, EmptyIds);
    internal static readonly CommercialEntitlements Full = new(true, EmptyIds, EmptyIds);
    internal bool HasAccess => FullAccess || GoalIds.Count != 0 || LessonIds.Count != 0;
}

public static class CommercialAccess
{
    private static readonly object EntitlementsKey = new();

    // An explicit allowlist keeps newly added API routes protected by default.
    public static async Task Gate(HttpContext ctx, RequestDelegate next)
    {
        var commercial = ctx.RequestServices.GetRequiredService<CommercialOptions>().Required;
        if (commercial) RequireCanonicalPath(ctx);
        var path = ctx.Request.Path;
        var project = path.StartsWithSegments("/projects");
        var api = path.StartsWithSegments("/api");
        var exempt = path.StartsWithSegments("/api/v1/auth") ||
                     path.StartsWithSegments("/api/v1/admin") ||
                     path.Equals(new PathString("/api/v1/health")) ||
                     path.Equals(new PathString("/api/v1/catalog")) ||
                     path.Equals(new PathString("/api/v1/me/access"));
        if (project) ctx.Response.Headers.CacheControl = "no-store";
        if (commercial && (project || (api && !exempt)))
        {
            if (ctx.User.Identity?.IsAuthenticated != true)
                throw new ApiError(401, "unauthorized", "يلزم تسجيل الدخول.");
            var access = await ReadEntitlements(ctx, ctx.RequestServices.GetRequiredService<Db>(), ctx.RequestAborted);
            if (!access.FullAccess)
            {
                var allowedProject = path.Equals(new PathString("/projects/web-starter-v1.zip")) &&
                    (access.GoalIds.Contains("web") || access.GoalIds.Contains("web-data") || access.LessonIds.Contains("web-12"));
                var scopedEndpoint = api && ctx.GetEndpoint()?.Metadata.GetMetadata<ScopedCommercialEndpoint>() is not null;
                if (!allowedProject && (!access.HasAccess || !scopedEndpoint)) throw AccessRequired();
            }
        }
        await next(ctx);
    }

    private static void RequireCanonicalPath(HttpContext ctx)
    {
        // A disk lookup can interpret URL separators and trailing dots differently from route matching on Windows.
        var path = ctx.Request.Path.Value.AsSpan();
        var rawTarget = ctx.Features.Get<IHttpRequestFeature>()?.RawTarget;
        var rawPath = rawTarget.AsSpan();
        var query = rawPath.IndexOf('?');
        if (query >= 0) rawPath = rawPath[..query];
        if (path.Contains('\\') || path.Contains(':') || path.Contains("//", StringComparison.Ordinal) ||
            rawPath.Contains('\\') || rawPath.Contains("%5c", StringComparison.OrdinalIgnoreCase) ||
            rawPath.Contains("%2f", StringComparison.OrdinalIgnoreCase))
            throw ApiError.Invalid("مسار الطلب غير صالح.");
        for (var index = 0; index < path.Length; index++)
            if (path[index] is '.' or ' ' && (index + 1 == path.Length || path[index + 1] == '/'))
                throw ApiError.Invalid("مسار الطلب غير صالح.");
    }

    internal static ApiError AccessRequired() => new(403, "access_required", "يلزم تفعيل الوصول إلى المحتوى.");

    internal static async Task<CommercialEntitlements> ReadEntitlements(HttpContext ctx, Db db, CancellationToken ct)
    {
        if (!ctx.RequestServices.GetRequiredService<CommercialOptions>().Required) return CommercialEntitlements.Full;
        if (ctx.User.Identity?.IsAuthenticated != true) return CommercialEntitlements.None;
        if (ctx.User.IsInRole("Author") || ctx.User.IsInRole("Reviewer") || ctx.User.IsInRole("Admin"))
            return CommercialEntitlements.Full;
        if (ctx.Items.TryGetValue(EntitlementsKey, out var cached) && cached is CommercialEntitlements found)
            return found;
        await using var conn = await db.Open(ct);
        var access = await ReadAccountEntitlements(conn, null, Input.UserId(ctx), ct);
        ctx.Items[EntitlementsKey] = access;
        return access;
    }

    internal static async Task<CommercialEntitlements> ReadAccountEntitlements(
        NpgsqlConnection conn, NpgsqlTransaction? tx, Guid userId, CancellationToken ct)
    {
        var result = await Db.Query(conn, tx, """
            SELECT EXISTS(SELECT 1 FROM public.commercial_access WHERE user_id=@user AND active),
                   ARRAY(SELECT scope_id FROM public.commercial_scope_access WHERE user_id=@user AND scope_type='goal'),
                   ARRAY(SELECT scope_id FROM public.commercial_scope_access WHERE user_id=@user AND scope_type='lesson')
            """, row => new CommercialEntitlements(row.GetBoolean(0),
                row.GetFieldValue<string[]>(1).ToFrozenSet(StringComparer.Ordinal),
                row.GetFieldValue<string[]>(2).ToFrozenSet(StringComparer.Ordinal)), ct, ("user", userId));
        return result.Single();
    }

    internal static async Task<CommercialOffer[]> ReadOffers(Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        return await ReadOffers(conn, ct);
    }

    internal static async Task<CommercialOffer[]> ReadOffers(NpgsqlConnection conn, CancellationToken ct)
    {
        var offers = await Db.Query(conn, null, """
            SELECT goal_id,price,currency FROM public.commercial_offers ORDER BY goal_id
            """, row => new CommercialOffer(row.GetString(0), row.GetDecimal(1), row.GetString(2)), ct);
        return offers.ToArray();
    }

    public static void MapCommercialAccess(this WebApplication app)
    {
        app.MapGet("/api/v1/me/access", ReadAccess).RequireAuthorization();
        if (!app.Services.GetRequiredService<CommercialOptions>().Required) return;

        var admin = app.MapGroup("/api/v1/admin/access").RequireAuthorization(policy => policy.RequireRole("Admin"));
        admin.MapPost("/grant", (AccessRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
            Change(request, ctx, db, true, ct));
        admin.MapPost("/revoke", (AccessRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
            Change(request, ctx, db, false, ct));
        admin.MapGet("/accounts", FindAccounts);
        admin.MapGet("/targets", ReadTargets);
        admin.MapGet("/offers", async (Db db, CancellationToken ct) => Results.Ok(await ReadOffers(db, ct)));
        admin.MapPut("/offers/{goalId}", ChangeOffer);
    }

    private static async Task<IResult> ReadAccess(HttpContext ctx, Db db, CommercialOptions options, CancellationToken ct)
    {
        var access = await ReadEntitlements(ctx, db, ct);
        if (!access.HasAccess || access.FullAccess)
            return Results.Ok(new { required = options.Required, active = access.HasAccess });
        return Results.Ok(new
        {
            required = options.Required,
            active = true,
            goalIds = access.GoalIds.Order(StringComparer.Ordinal).ToArray(),
            lessonIds = access.LessonIds.Order(StringComparer.Ordinal).ToArray()
        });
    }

    private static async Task<IResult> Change(AccessRequest request, HttpContext ctx, Db db, bool active, CancellationToken ct)
    {
        var name = Input.UserName(request.UserName);
        if (request.GoalId is not null && request.LessonId is not null)
            throw ApiError.Invalid("اختر تخصصًا أو درسًا واحدًا لكل عملية.");
        var scopeType = request.GoalId is not null ? "goal" : request.LessonId is not null ? "lesson" : null;
        var scopeId = scopeType is null ? null : Input.Id(request.GoalId ?? request.LessonId);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        if (active && scopeType is not null)
        {
            await Content.LockActiveRelease(conn, tx, ct);
            var release = await ActiveRelease(conn, tx, ct);
            var targets = scopeType == "goal" ? PublishedGoals(release) : Content.Lessons(release.Bundle);
            if (!targets.Any(target => Input.String(target["id"]) == scopeId)) throw ApiError.Missing();
        }
        var users = await Db.Query(conn, tx,
            "SELECT id FROM public.users WHERE normalized_user_name=@name FOR UPDATE", r => r.GetGuid(0), ct, ("name", name));
        if (users.Count == 0) throw ApiError.Missing();
        var user = users[0];
        var auditAction = active ? "access.grant" : "access.revoke";
        if (scopeType is null)
        {
            await Db.Execute(conn, tx, """
                INSERT INTO public.commercial_access(user_id,active,updated_at)
                VALUES (@user,@active,now())
                ON CONFLICT(user_id) DO UPDATE SET active=EXCLUDED.active,updated_at=now()
                WHERE public.commercial_access.active IS DISTINCT FROM EXCLUDED.active
                """, ct, ("user", user), ("active", active));
            await Db.Audit(conn, tx, Input.UserId(ctx), auditAction, user.ToString(), ct: ct);
        }
        else
        {
            var sql = active ? """
                INSERT INTO public.commercial_scope_access(user_id,scope_type,scope_id) VALUES (@user,@type,@id)
                ON CONFLICT (user_id,scope_type,scope_id) DO NOTHING
                """ : """
                DELETE FROM public.commercial_scope_access WHERE user_id=@user AND scope_type=@type AND scope_id=@id
                """;
            var changed = await Db.Execute(conn, tx, sql, ct, ("user", user), ("type", scopeType), ("id", scopeId));
            if (changed != 0)
                await Db.Audit(conn, tx, Input.UserId(ctx), auditAction, user.ToString(),
                    new JsonObject { ["scopeType"] = scopeType, ["scopeId"] = scopeId }, ct);
        }
        await tx.CommitAsync(ct);
        return Results.Ok(new { active });
    }

    private static async Task<IResult> FindAccounts(string? query, Db db, CancellationToken ct)
    {
        var search = string.IsNullOrWhiteSpace(query) ? "" : Input.Text(query, 2, 80);
        await using var conn = await db.Open(ct);
        var accounts = await Db.Query(conn, null, """
            SELECT u.user_name,u.display_name,
                   EXISTS(SELECT 1 FROM public.commercial_access a WHERE a.user_id=u.id AND a.active),
                   ARRAY(SELECT scope_id FROM public.commercial_scope_access s WHERE s.user_id=u.id AND s.scope_type='goal' ORDER BY scope_id),
                   ARRAY(SELECT scope_id FROM public.commercial_scope_access s WHERE s.user_id=u.id AND s.scope_type='lesson' ORDER BY scope_id)
            FROM public.users u
            WHERE u.role='Learner' AND (@query='' OR strpos(lower(u.user_name),lower(@query))>0 OR strpos(lower(u.display_name),lower(@query))>0)
            ORDER BY (u.normalized_user_name=lower(@query)) DESC,u.normalized_user_name,u.id
            LIMIT 20
            """, row => new
        {
            userName = row.GetString(0), displayName = row.GetString(1), fullAccess = row.GetBoolean(2),
            goalIds = row.GetFieldValue<string[]>(3), lessonIds = row.GetFieldValue<string[]>(4)
        }, ct, ("query", search));
        return Results.Ok(accounts);
    }

    private static async Task<IResult> ReadTargets(Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        var release = await ActiveRelease(conn, null, ct);
        return Results.Ok(new
        {
            goals = PublishedGoals(release).Select(Target).ToArray(),
            lessons = Content.Lessons(release.Bundle).Select(Target).ToArray()
        });
    }

    private static async Task<IResult> ChangeOffer(string goalId, OfferRequest request, HttpContext ctx, Db db, CancellationToken ct)
    {
        goalId = Input.Id(goalId);
        var currency = request.Currency?.Trim().ToUpperInvariant();
        if (request.Price is decimal amount)
        {
            if (amount < 0 || amount > 99_999_999.99m || decimal.Round(amount, 2) != amount ||
                currency is null || currency.Length != 3 || currency.Any(character => character is < 'A' or > 'Z'))
                throw ApiError.Invalid("اكتب سعرًا صحيحًا بمنزلتين عشريتين على الأكثر ورمز عملة من ثلاثة أحرف.");
        }
        else if (currency is not null)
        {
            throw ApiError.Invalid("اترك السعر والعملة فارغين لإزالة السعر.");
        }

        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        int changed;
        if (request.Price is decimal price)
        {
            await Content.LockActiveRelease(conn, tx, ct);
            var release = await ActiveRelease(conn, tx, ct);
            if (!PublishedGoals(release).Any(goal => Input.String(goal["id"]) == goalId)) throw ApiError.Missing();
            changed = await Db.Execute(conn, tx, """
                INSERT INTO public.commercial_offers(goal_id,price,currency) VALUES (@goal,@price,@currency)
                ON CONFLICT (goal_id) DO UPDATE SET price=EXCLUDED.price,currency=EXCLUDED.currency
                WHERE (public.commercial_offers.price,public.commercial_offers.currency) IS DISTINCT FROM (EXCLUDED.price,EXCLUDED.currency)
                """, ct, ("goal", goalId), ("price", price), ("currency", currency));
        }
        else
        {
            changed = await Db.Execute(conn, tx, "DELETE FROM public.commercial_offers WHERE goal_id=@goal", ct, ("goal", goalId));
        }
        if (changed != 0)
            await Db.Audit(conn, tx, Input.UserId(ctx), request.Price is null ? "offer.remove" : "offer.update", goalId,
                new JsonObject { ["price"] = request.Price, ["currency"] = currency }, ct);
        await tx.CommitAsync(ct);
        return Results.Ok(new { goalId, price = request.Price, currency });
    }

    private static async Task<Release> ActiveRelease(NpgsqlConnection conn, NpgsqlTransaction? tx, CancellationToken ct)
    {
        var releases = await Db.Query(conn, tx, """
            SELECT r.id,r.release_id,r.title,r.status,r.version,r.bundle::text
            FROM public.content_releases r JOIN public.settings s ON s.key='active_release_id' AND s.value=r.release_id
            WHERE r.status='published'
            """, Content.Read, ct);
        return releases.FirstOrDefault() ?? throw ApiError.Missing();
    }

    private static IEnumerable<JsonObject> PublishedGoals(Release release) =>
        (release.Bundle["graph"]?["goals"] as JsonArray ?? []).OfType<JsonObject>()
            .Where(goal => Input.String(goal["status"]) == "sample");

    private static object Target(JsonObject node) => new { id = Input.String(node["id"]), title = Input.String(node["title"]) };
}
