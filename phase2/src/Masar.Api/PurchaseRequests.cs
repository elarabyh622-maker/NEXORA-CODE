using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Http.Features;
using Npgsql;

namespace Masar.Api;

internal static partial class PurchaseRequests
{
    private sealed record Purchase(Guid Id, string GoalId, decimal Price, string Currency,
        string Status, string? CheckoutUrl, DateTime RequestedAt);
    private sealed record LockedPurchase(string GoalId, string Status, string? CheckoutUrl, string? PaymentReference);

    internal sealed record SubmitRequest(string? GoalId);
    internal sealed record LinkRequest(string? CheckoutUrl);
    internal sealed record ConfirmRequest(string? PaymentReference);
    internal sealed record CloseRequest(bool ConfirmedUnpaidAndDisabled);

    [GeneratedRegex(@"\Ahttps://paymob\.link/[A-Za-z0-9]{1,64}\z", RegexOptions.CultureInvariant)]
    private static partial Regex QuickLinkPattern();

    [GeneratedRegex(@"\A[1-9][0-9]{0,19}\z", RegexOptions.CultureInvariant)]
    private static partial Regex TransactionIdPattern();

    internal static void MapPurchaseRequests(this WebApplication app)
    {
        if (!app.Services.GetRequiredService<CommercialOptions>().Required) return;
        var learner = app.MapGroup("/api/v1/me/purchases")
            .RequireAuthorization(policy => policy.RequireRole("Learner"));
        learner.MapGet("", Read);
        learner.MapPost("", Submit);

        var admin = app.MapGroup("/api/v1/admin/purchases")
            .RequireAuthorization(policy => policy.RequireRole("Admin"));
        admin.MapGet("", Queue);
        admin.MapPut("/{id:guid}/link", Link);
        admin.MapPost("/{id:guid}/confirm", Confirm);
        admin.MapPost("/{id:guid}/close", Close);
    }

    private static Purchase ReadPurchase(NpgsqlDataReader row) => new(row.GetGuid(0), row.GetString(1),
        row.GetDecimal(2), row.GetString(3), row.GetString(4), row.IsDBNull(5) ? null : row.GetString(5), row.GetDateTime(6));

    private static async Task<IResult> Read(HttpContext ctx, Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        var requests = await Db.Query(conn, null, """
            SELECT id,goal_id,price,currency,status,CASE WHEN status='link-ready' THEN checkout_url END,requested_at
            FROM public.purchase_requests WHERE user_id=@user
            ORDER BY (status IN ('pending','link-ready')) DESC,requested_at DESC,id DESC LIMIT 100
            """, ReadPurchase, ct, ("user", Input.UserId(ctx)));
        return Results.Ok(requests);
    }

    private static async Task<IResult> Submit(SubmitRequest request, HttpContext ctx, Db db, CancellationToken ct)
    {
        var goal = Input.Id(request.GoalId);
        var user = Input.UserId(ctx);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await LockLearner(conn, tx, user, ct);
        await RequireUnownedGoal(conn, tx, user, goal, ct);
        var open = await Db.Query(conn, tx, """
            SELECT id,goal_id,price,currency,status,checkout_url,requested_at FROM public.purchase_requests
            WHERE user_id=@user AND goal_id=@goal AND status IN ('pending','link-ready')
            """, ReadPurchase, ct, ("user", user), ("goal", goal));
        if (open.Count != 0)
        {
            await tx.CommitAsync(ct);
            return Results.Ok(open.Single());
        }

        var id = Guid.NewGuid();
        var created = await Db.Query(conn, tx, """
            INSERT INTO public.purchase_requests(id,user_id,goal_id,price,currency)
            SELECT @id,@user,o.goal_id,o.price,o.currency FROM public.commercial_offers o
            WHERE o.goal_id=@goal AND o.price > 0 AND o.currency='EGP' AND EXISTS (
                SELECT 1 FROM public.content_releases r
                JOIN public.settings s ON s.key='active_release_id' AND s.value=r.release_id
                CROSS JOIN LATERAL jsonb_array_elements(r.bundle #> '{graph,goals}') AS goals(goal)
                WHERE r.status='published' AND goal->>'id'=o.goal_id AND goal->>'status'='sample'
            )
            RETURNING id,goal_id,price,currency,status,checkout_url,requested_at
            """, ReadPurchase, ct, ("id", id), ("user", user), ("goal", goal));
        var purchase = created.SingleOrDefault() ?? throw new ApiError(404, "offer_unavailable", "لا يوجد عرض متاح لهذا المسار بالجنيه المصري.");
        await Audit(conn, tx, user, "purchase.request", purchase.Id, goal, ct);
        await tx.CommitAsync(ct);
        return Results.Ok(purchase);
    }

    private static async Task<IResult> Queue(Db db, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        var requests = await Db.Query(conn, null, """
            SELECT p.id,p.goal_id,p.price,p.currency,p.status,p.checkout_url,p.requested_at,u.user_name
            FROM public.purchase_requests p JOIN public.users u ON u.id=p.user_id
            WHERE p.status IN ('pending','link-ready') ORDER BY p.requested_at,p.id LIMIT 100
            """, row =>
        {
            var purchase = ReadPurchase(row);
            return new { purchase.Id, purchase.GoalId, purchase.Price, purchase.Currency, purchase.Status,
                purchase.CheckoutUrl, purchase.RequestedAt, UserName = row.GetString(7) };
        }, ct);
        return Results.Ok(requests);
    }

    private static async Task<IResult> Link(Guid id, LinkRequest request, HttpContext ctx, Db db, CancellationToken ct)
    {
        var url = request.CheckoutUrl?.Trim();
        if (url is null || url.Length > 84 || !QuickLinkPattern().IsMatch(url))
            throw ApiError.Invalid("أدخل رابط Paymob القصير من لوحة التاجر.");

        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var user = await LockRequestOwner(conn, tx, id, ct);
        var purchase = await LockPurchase(conn, tx, id, ct);
        if (purchase.Status != "closed" && purchase.CheckoutUrl == url) return Results.NoContent();
        if (purchase.Status != "pending")
            throw new ApiError(409, "purchase_link_locked", "تم حفظ رابط الدفع بالفعل أو أُغلق الطلب.");
        await RequireUnownedGoal(conn, tx, user, purchase.GoalId, ct);

        try
        {
            await Db.Execute(conn, tx, "UPDATE public.purchase_requests SET status='link-ready',checkout_url=@url WHERE id=@id",
                ct, ("url", url), ("id", id));
        }
        catch (PostgresException error) when (error.SqlState == PostgresErrorCodes.UniqueViolation &&
                                              error.ConstraintName == "purchase_requests_checkout_url")
        {
            throw new ApiError(409, "purchase_link_used", "رابط الدفع مرتبط بطلب آخر.");
        }
        await Audit(conn, tx, Input.UserId(ctx), "purchase.link", id, purchase.GoalId, ct);
        await tx.CommitAsync(ct);
        return Results.NoContent();
    }

    private static async Task<IResult> Confirm(Guid id, ConfirmRequest request, HttpContext ctx, Db db, CancellationToken ct)
    {
        var reference = request.PaymentReference?.Trim();
        if (reference is null || reference.Length > 20 || !TransactionIdPattern().IsMatch(reference))
            throw ApiError.Invalid("أدخل الرقم التعريفي لعملية السداد من لوحة Paymob.");

        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var user = await LockRequestOwner(conn, tx, id, ct);
        var purchase = await LockPurchase(conn, tx, id, ct);
        if (purchase.Status == "confirmed" && purchase.PaymentReference == reference) return Results.NoContent();
        if (purchase.Status != "link-ready")
            throw new ApiError(409, "purchase_not_confirmable", "يلزم وجود رابط لهذا الطلب قبل تسجيل تأكيد السداد.");

        try
        {
            await Db.Execute(conn, tx, """
                UPDATE public.purchase_requests SET status='confirmed',payment_reference=@reference WHERE id=@id
                """, ct, ("reference", reference), ("id", id));
        }
        catch (PostgresException error) when (error.SqlState == PostgresErrorCodes.UniqueViolation &&
                                              error.ConstraintName == "purchase_requests_payment_reference")
        {
            throw new ApiError(409, "purchase_reference_used", "عملية السداد مسجلة بالفعل لطلب آخر.");
        }
        await Db.Execute(conn, tx, """
            INSERT INTO public.commercial_scope_access(user_id,scope_type,scope_id) VALUES (@user,'goal',@goal)
            ON CONFLICT (user_id,scope_type,scope_id) DO NOTHING
            """, ct, ("user", user), ("goal", purchase.GoalId));
        await Audit(conn, tx, Input.UserId(ctx), "purchase.confirm", id, purchase.GoalId, ct);
        await tx.CommitAsync(ct);
        return Results.NoContent();
    }

    private static async Task<IResult> Close(Guid id, HttpContext ctx, Db db, CancellationToken ct)
    {
        // Binding an optional JSON parameter also adds routing metadata that excludes bodyless requests.
        CloseRequest? request = null;
        if (ctx.Features.Get<IHttpRequestBodyDetectionFeature>()?.CanHaveBody == true)
        {
            if (!ctx.Request.HasJsonContentType()) throw ApiError.Invalid("استخدم JSON لبيانات إغلاق الطلب.");
            try
            {
                request = await ctx.Request.ReadFromJsonAsync<CloseRequest>(ct);
            }
            catch (JsonException)
            {
                throw ApiError.Invalid("بيانات إغلاق الطلب غير صالحة.");
            }
        }
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var purchase = await LockPurchase(conn, tx, id, ct);
        if (purchase.Status == "closed") return Results.NoContent();
        if (purchase.Status == "confirmed")
            throw new ApiError(409, "purchase_already_confirmed", "تم تسجيل سداد هذا الطلب.");
        var hasLink = purchase.Status == "link-ready";
        if (hasLink && request?.ConfirmedUnpaidAndDisabled != true)
            throw new ApiError(409, "purchase_close_requires_verification", "تحقق في Paymob أن الطلب غير مدفوع وأن الرابط معطّل أو منتهي.");
        await Db.Execute(conn, tx, "UPDATE public.purchase_requests SET status='closed' WHERE id=@id", ct, ("id", id));
        await Db.Audit(conn, tx, Input.UserId(ctx), "purchase.close", id.ToString(), new JsonObject
        {
            ["goalId"] = purchase.GoalId,
            ["confirmedUnpaidAndDisabled"] = hasLink
        }, ct);
        await tx.CommitAsync(ct);
        return Results.NoContent();
    }

    private static async Task<Guid> LockRequestOwner(NpgsqlConnection conn, NpgsqlTransaction tx, Guid id, CancellationToken ct)
    {
        var owners = await Db.Query(conn, tx, "SELECT user_id FROM public.purchase_requests WHERE id=@id",
            row => row.GetGuid(0), ct, ("id", id));
        if (owners.Count == 0) throw ApiError.Missing();
        var user = owners.Single();
        await LockLearner(conn, tx, user, ct);
        return user;
    }

    private static async Task LockLearner(NpgsqlConnection conn, NpgsqlTransaction tx, Guid user, CancellationToken ct)
    {
        var role = await Db.Scalar<string>(conn, tx, "SELECT role FROM public.users WHERE id=@user FOR UPDATE", ct, ("user", user));
        if (role != "Learner") throw new ApiError(409, "account_role_changed", "الطلب متاح لحساب متعلم فقط.");
    }

    private static async Task<LockedPurchase> LockPurchase(NpgsqlConnection conn, NpgsqlTransaction tx, Guid id, CancellationToken ct)
    {
        var rows = await Db.Query(conn, tx, """
            SELECT goal_id,status,checkout_url,payment_reference FROM public.purchase_requests WHERE id=@id FOR UPDATE
            """, row => new LockedPurchase(row.GetString(0), row.GetString(1), row.IsDBNull(2) ? null : row.GetString(2),
            row.IsDBNull(3) ? null : row.GetString(3)), ct, ("id", id));
        return rows.SingleOrDefault() ?? throw ApiError.Missing();
    }

    private static async Task RequireUnownedGoal(NpgsqlConnection conn, NpgsqlTransaction tx, Guid user, string goal, CancellationToken ct)
    {
        var access = await CommercialAccess.ReadAccountEntitlements(conn, tx, user, ct);
        if (access.FullAccess || access.GoalIds.Contains(goal))
            throw new ApiError(409, "purchase_already_entitled", "المسار متاح لهذا الحساب بالفعل.");
    }

    private static Task Audit(NpgsqlConnection conn, NpgsqlTransaction tx, Guid actor, string action,
        Guid id, string goal, CancellationToken ct) =>
        Db.Audit(conn, tx, actor, action, id.ToString(), new JsonObject { ["goalId"] = goal }, ct);
}
