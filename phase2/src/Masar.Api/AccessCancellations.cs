using Npgsql;

namespace Masar.Api;

internal static class AccessCancellations
{
    internal sealed record Resolution(bool? Approve);
    private sealed record Entry(Guid Id, string Status, DateTime RequestedAt);

    internal static void MapAccessCancellations(this WebApplication app)
    {
        var learner = app.MapGroup("/api/v1/me/access-cancellation")
            .RequireAuthorization(policy => policy.RequireRole("Learner"));
        learner.MapGet("", Read);
        learner.MapPost("", Submit);
        var admin = app.MapGroup("/api/v1/admin/access/cancellations")
            .RequireAuthorization(policy => policy.RequireRole("Admin"));
        admin.MapGet("", Queue);
        admin.MapPost("/{id:guid}/resolve", Resolve);
    }

    private static Task<List<Entry>> Latest(NpgsqlConnection conn, NpgsqlTransaction? tx, Guid user, CancellationToken ct) =>
        Db.Query(conn, tx, """
            SELECT id,status,requested_at FROM public.access_cancellations
            WHERE user_id=@user ORDER BY requested_at DESC,id DESC LIMIT 1
            """, row => new Entry(row.GetGuid(0), row.GetString(1), row.GetDateTime(2)), ct, ("user", user));

    private static async Task<IResult> Read(HttpContext ctx, Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        return Results.Ok(new { request = (await Latest(conn, null, Input.UserId(ctx), ct)).SingleOrDefault() });
    }

    private static async Task<string> LockUser(NpgsqlConnection conn, NpgsqlTransaction tx, Guid user, CancellationToken ct) =>
        await Db.Scalar<string>(conn, tx, "SELECT role FROM public.users WHERE id=@user FOR UPDATE", ct,
            ("user", user)) ?? throw ApiError.Missing();

    private static async Task<IResult> Submit(HttpContext ctx, Db db, CancellationToken ct)
    {
        var user = Input.UserId(ctx);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        if (await LockUser(conn, tx, user, ct) != "Learner") throw CommercialAccess.AccessRequired();
        var latest = (await Latest(conn, tx, user, ct)).SingleOrDefault();
        if (latest?.Status == "pending")
        {
            await tx.CommitAsync(ct);
            return Results.Ok(new { request = latest });
        }
        if (!(await CommercialAccess.ReadAccountEntitlements(conn, tx, user, ct)).HasAccess)
            throw CommercialAccess.AccessRequired();
        var id = Guid.NewGuid();
        var created = await Db.Query(conn, tx, """
            INSERT INTO public.access_cancellations(id,user_id,status) VALUES (@id,@user,'pending')
            RETURNING id,status,requested_at
            """, row => new Entry(row.GetGuid(0), row.GetString(1), row.GetDateTime(2)), ct,
            ("id", id), ("user", user));
        await Db.Audit(conn, tx, user, "access.cancellation.request", id.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        return Results.Ok(new { request = created.Single() });
    }

    private static async Task<IResult> Queue(Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        var requests = await Db.Query(conn, null, """
            SELECT c.id,u.user_name,u.display_name,c.status,c.requested_at
            FROM public.access_cancellations c JOIN public.users u ON c.user_id=u.id
            WHERE c.status='pending' ORDER BY c.requested_at,c.id LIMIT 100
            """, row => new { id = row.GetGuid(0), userName = row.GetString(1), displayName = row.GetString(2),
                status = row.GetString(3), requestedAt = row.GetDateTime(4) }, ct);
        return Results.Ok(requests);
    }

    private static async Task<IResult> Resolve(Guid id, Resolution body, HttpContext ctx, Db db, CancellationToken ct)
    {
        if (body.Approve is not bool approve) throw ApiError.Invalid();
        var status = approve ? "approved" : "declined";
        var actor = Input.UserId(ctx);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var owners = await Db.Query(conn, tx, "SELECT user_id FROM public.access_cancellations WHERE id=@id",
            row => row.GetGuid(0), ct, ("id", id));
        if (owners.Count == 0) throw ApiError.Missing();
        var user = owners.Single();
        var role = await LockUser(conn, tx, user, ct);
        var current = await Db.Scalar<string>(conn, tx,
            "SELECT status FROM public.access_cancellations WHERE id=@id FOR UPDATE", ct, ("id", id));
        if (current == status)
        {
            await tx.CommitAsync(ct);
            return Results.NoContent();
        }
        if (current != "pending") throw ApiError.Conflict("cancellation_already_resolved");
        if (approve)
        {
            if (role != "Learner") throw ApiError.Conflict("account_role_changed");
            await Db.Execute(conn, tx, """
                UPDATE public.commercial_access SET active=false,updated_at=now() WHERE user_id=@user AND active;
                DELETE FROM public.commercial_scope_access WHERE user_id=@user
                """, ct, ("user", user));
        }
        await Db.Execute(conn, tx, """
            UPDATE public.access_cancellations SET status=@status,resolved_at=clock_timestamp(),resolved_by=@actor
            WHERE id=@id
            """, ct, ("id", id), ("status", status), ("actor", actor));
        await Db.Audit(conn, tx, actor, approve ? "access.cancellation.approve" : "access.cancellation.decline",
            id.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        return Results.NoContent();
    }
}
