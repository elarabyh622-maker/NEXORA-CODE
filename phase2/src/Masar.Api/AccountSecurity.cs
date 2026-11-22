using System.Security.Cryptography;
using Microsoft.AspNetCore.Identity;
using Npgsql;

namespace Masar.Api;

public sealed record ChangePasswordRequest(string? CurrentPassword, string? NewPassword);
public sealed record RecoveryCodeRequest(string? CurrentPassword);
public sealed record ResetPasswordRequest(string? UserName, string? RecoveryCode, string? NewPassword);
public sealed record AdminRecoveryCodeRequest(string? UserName, string? CurrentPassword);

public static class AccountSecurity
{
    private sealed record Credentials(Account User, string Hash);

    public static void MapAccountSecurity(this WebApplication app)
    {
        app.MapPost("/api/v1/auth/change-password", ChangePassword)
            .RequireAuthorization().RequireRateLimiting("auth");
        app.MapPost("/api/v1/auth/recovery-code", IssueRecoveryCode)
            .RequireAuthorization().RequireRateLimiting("auth");
        app.MapPost("/api/v1/auth/reset-password", ResetPassword).RequireRateLimiting("auth");
        app.MapPost("/api/v1/admin/accounts/recovery-code", IssueAdminRecoveryCode)
            .RequireAuthorization(policy => policy.RequireRole("Admin")).RequireRateLimiting("auth");
    }

    private static async Task<IResult> ChangePassword(ChangePasswordRequest request, HttpContext ctx,
        Db db, Accounts passwords, CancellationToken ct)
    {
        var password = Input.Text(request.NewPassword, 12, 128, false);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var account = await Reauthenticate(request.CurrentPassword, ctx, conn, tx, passwords, ct);
        await ReplacePassword(conn, tx, account.User, password, passwords, ct);
        await Db.Audit(conn, tx, account.User.Id, "account.password_change", account.User.Id.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        DeleteSessionCookie(ctx);
        return Results.NoContent();
    }

    private static async Task<IResult> IssueRecoveryCode(RecoveryCodeRequest request, HttpContext ctx,
        Db db, Accounts passwords, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var account = await Reauthenticate(request.CurrentPassword, ctx, conn, tx, passwords, ct);
        var recoveryCode = await StoreRecoveryCode(conn, tx, account.User.Id, account.User.Id, false, ct);
        await Db.Audit(conn, tx, account.User.Id, "account.recovery_code_replace", account.User.Id.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        ctx.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new { recoveryCode });
    }

    private static async Task<IResult> IssueAdminRecoveryCode(AdminRecoveryCodeRequest request, HttpContext ctx,
        Db db, Accounts passwords, CancellationToken ct)
    {
        var name = Input.UserName(request.UserName);
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var admin = await Reauthenticate(request.CurrentPassword, ctx, conn, tx, passwords, ct);
        // Authorization is rechecked under the user lock, rather than trusting an earlier middleware snapshot.
        if (admin.User.Role != "Admin") throw new ApiError(403, "forbidden", "ليست لديك صلاحية هذه العملية.");
        // Admins always lock their own row before a learner row. Staff accounts cannot be reset through this route.
        var matches = await Db.Query(conn, tx, """
            SELECT id FROM public.users WHERE normalized_user_name=@name AND role='Learner' FOR UPDATE
            """, row => row.GetGuid(0), ct, ("name", name));
        if (matches.Count == 0) throw ApiError.Missing();
        var userId = matches[0];
        var recoveryCode = await StoreRecoveryCode(conn, tx, userId, admin.User.Id, true, ct);
        var expiresAt = await Db.Scalar<DateTime>(conn, tx,
            "SELECT expires_at FROM public.account_recovery_codes WHERE user_id=@user", ct, ("user", userId));
        await Db.Audit(conn, tx, admin.User.Id, "account.admin_recovery_code_replace", userId.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        ctx.Response.Headers.CacheControl = "no-store";
        return Results.Ok(new { recoveryCode, expiresAt });
    }

    private static async Task<IResult> ResetPassword(ResetPasswordRequest request, HttpContext ctx,
        Db db, Accounts passwords, CancellationToken ct)
    {
        var password = Input.Text(request.NewPassword, 12, 128, false);
        var name = NormalizeRecoveryName(request.UserName);
        var code = request.RecoveryCode ?? "";
        // Bound untrusted input; all unknown names and invalid codes share the same public error.
        if (code.Length > 128) throw RecoveryFailed();
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var key = Input.Hash(name);
        var locked = await LockFailures(conn, tx, key, ct);
        var matches = await Db.Query(conn, tx, """
            SELECT id,user_name,display_name,role,password_hash FROM public.users
            WHERE normalized_user_name=@name FOR UPDATE
            """, Read, ct, ("name", name));
        var account = matches.FirstOrDefault();
        var codeHash = Input.Hash(code);
        // Read the code only after locking the user; issue, consume and password replacement share this lock.
        var expected = account is null ? null : await Db.Scalar<string>(conn, tx, """
            SELECT code_hash FROM public.account_recovery_codes
            WHERE user_id=@user AND (expires_at IS NULL OR expires_at>clock_timestamp())
            """, ct, ("user", account.User.Id));
        var matchesCode = CryptographicOperations.FixedTimeEquals(
            System.Text.Encoding.ASCII.GetBytes(codeHash), System.Text.Encoding.ASCII.GetBytes(expected ?? new string('0', 64)));
        if (locked || account is null || expected is null || code.Length != 64 || !code.All(Uri.IsHexDigit) || !matchesCode)
        {
            if (!locked) await RecordFailure(conn, tx, key, ct);
            await tx.CommitAsync(ct);
            throw RecoveryFailed();
        }
        await ReplacePassword(conn, tx, account.User, password, passwords, ct);
        await Db.Execute(conn, tx, "DELETE FROM public.login_failures WHERE key_hash=@key", ct, ("key", key));
        await Db.Audit(conn, tx, account.User.Id, "account.password_reset", account.User.Id.ToString(), ct: ct);
        await tx.CommitAsync(ct);
        // A reset never signs in. Remove this browser's stale cookie and refresh anonymous CSRF on the client.
        DeleteSessionCookie(ctx);
        return Results.NoContent();
    }

    private static Credentials Read(NpgsqlDataReader row) =>
        new(new Account(row.GetGuid(0), row.GetString(1), row.GetString(2), row.GetString(3)), row.GetString(4));

    private static async Task<Credentials> Reauthenticate(string? password, HttpContext ctx,
        NpgsqlConnection conn, NpgsqlTransaction tx, Accounts passwords, CancellationToken ct)
    {
        var snapshot = (Account)ctx.Items["Masar.Account"]!;
        var key = Input.Hash(snapshot.UserName);
        // Every password verifier takes the failure lock before the user lock, including login/reset.
        var locked = await LockFailures(conn, tx, key, ct);
        var rows = await Db.Query(conn, tx, """
            SELECT id,user_name,display_name,role,password_hash FROM public.users WHERE id=@user FOR UPDATE
            """, Read, ct, ("user", snapshot.Id));
        var account = rows.FirstOrDefault();
        var session = ctx.Request.Cookies[AuthEndpoints.SessionCookie(ctx)] ?? "";
        var activeSession = await Db.Scalar<bool>(conn, tx, """
            SELECT EXISTS(SELECT 1 FROM public.sessions
            WHERE token_hash=@hash AND user_id=@user AND revoked_at IS NULL AND expires_at>clock_timestamp())
            """, ct, ("hash", Input.Hash(session)), ("user", snapshot.Id));
        if (!activeSession || account is null)
            throw new ApiError(401, "unauthorized", "يلزم تسجيل الدخول.");
        var candidate = password is { Length: <= 128 } ? password : "";
        var result = passwords.Verify(locked ? null : account.User, locked ? null : account.Hash, candidate);
        if (locked || candidate.Length < 12 || result == PasswordVerificationResult.Failed)
        {
            if (!locked) await RecordFailure(conn, tx, key, ct);
            // Persist lockout failures even though the requested security mutation is rejected.
            await tx.CommitAsync(ct);
            throw new ApiError(400, "current_password_invalid", "كلمة المرور الحالية غير صحيحة. حاول لاحقًا إذا تكررت المحاولات.");
        }
        await Db.Execute(conn, tx, "DELETE FROM public.login_failures WHERE key_hash=@key", ct, ("key", key));
        return account;
    }

    private static async Task<bool> LockFailures(NpgsqlConnection conn, NpgsqlTransaction tx, string key, CancellationToken ct)
    {
        await Db.Execute(conn, tx,
            "INSERT INTO public.login_failures(key_hash) VALUES (@key) ON CONFLICT DO NOTHING", ct, ("key", key));
        return await Db.Scalar<bool>(conn, tx, """
            SELECT COALESCE(blocked_until>now(),false) FROM public.login_failures WHERE key_hash=@key FOR UPDATE
            """, ct, ("key", key));
    }

    private static Task<int> RecordFailure(NpgsqlConnection conn, NpgsqlTransaction tx, string key, CancellationToken ct) =>
        Db.Execute(conn, tx, """
            UPDATE public.login_failures SET
                failures=CASE WHEN window_started_at<now()-interval '15 minutes' THEN 1 ELSE failures+1 END,
                blocked_until=CASE WHEN window_started_at>=now()-interval '15 minutes' AND failures+1>=5
                    THEN now()+interval '15 minutes' ELSE NULL END,
                window_started_at=CASE WHEN window_started_at<now()-interval '15 minutes' THEN now() ELSE window_started_at END
            WHERE key_hash=@key
            """, ct, ("key", key));

    private static async Task<string> StoreRecoveryCode(NpgsqlConnection conn, NpgsqlTransaction tx,
        Guid userId, Guid actorId, bool temporary, CancellationToken ct)
    {
        var code = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
        await Db.Execute(conn, tx, """
            INSERT INTO public.account_recovery_codes(user_id,code_hash,issued_by,expires_at)
            VALUES (@user,@hash,@actor,CASE WHEN @temporary THEN now()+interval '30 minutes' ELSE NULL END)
            ON CONFLICT(user_id) DO UPDATE SET code_hash=EXCLUDED.code_hash,issued_by=EXCLUDED.issued_by,
                created_at=now(),expires_at=EXCLUDED.expires_at
            """, ct, ("user", userId), ("hash", Input.Hash(code)), ("actor", actorId), ("temporary", temporary));
        return code;
    }

    private static async Task ReplacePassword(NpgsqlConnection conn, NpgsqlTransaction tx, Account account,
        string password, Accounts passwords, CancellationToken ct)
    {
        await Db.Execute(conn, tx, "UPDATE public.users SET password_hash=@hash WHERE id=@user", ct,
            ("hash", passwords.Hash(account, password)), ("user", account.Id));
        await Db.Execute(conn, tx,
            "UPDATE public.sessions SET revoked_at=now() WHERE user_id=@user AND revoked_at IS NULL", ct, ("user", account.Id));
        await Db.Execute(conn, tx, "DELETE FROM public.account_recovery_codes WHERE user_id=@user", ct, ("user", account.Id));
    }

    private static string NormalizeRecoveryName(string? value)
    {
        var raw = value ?? "";
        if (raw.Length > 160) return "!invalid-name";
        try { return Input.UserName(raw); }
        catch (ApiError) { return "!invalid-" + Input.Hash(raw); }
    }

    private static ApiError RecoveryFailed() => new(400, "invalid_recovery_code",
        "اسم المستخدم أو رمز الاسترداد غير صحيح أو انتهت صلاحيته. حاول لاحقًا إذا تكررت المحاولات.");

    private static void DeleteSessionCookie(HttpContext ctx)
    {
        ctx.Response.Cookies.Delete(AuthEndpoints.SessionCookie(ctx), AuthEndpoints.CookieOptions(ctx));
        ctx.Response.Headers.CacheControl = "no-store";
    }
}
