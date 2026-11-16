using System.Security.Claims;
using System.Security.Cryptography;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Masar.Api;

public sealed record Account(Guid Id, string UserName, string DisplayName, string Role);
public sealed record RegisterRequest(string? UserName, string? DisplayName, string? Password);
public sealed record LoginRequest(string? UserName, string? Password);

public sealed class SessionAuthenticationHandler(IOptionsMonitor<AuthenticationSchemeOptions> options,
    ILoggerFactory logger, UrlEncoder encoder, Db db, CommercialOptions commercial) : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "MasarSession";

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var token = Request.Cookies[commercial.CookieName("Session")];
        if (string.IsNullOrEmpty(token) || token.Length != 64 || !token.All(Uri.IsHexDigit))
            return AuthenticateResult.NoResult();
        await using var conn = await db.Open(Context.RequestAborted);
        var users = await Db.Query(conn, null, """
            SELECT u.id,u.user_name,u.display_name,u.role
            FROM public.sessions s JOIN public.users u ON u.id=s.user_id
            WHERE s.token_hash=@hash AND s.revoked_at IS NULL AND s.expires_at>now()
            """, r => new Account(r.GetGuid(0), r.GetString(1), r.GetString(2), r.GetString(3)),
            Context.RequestAborted, ("hash", Input.Hash(token)));
        if (users.Count == 0) return AuthenticateResult.NoResult();
        var user = users[0];
        Context.Items["Masar.Account"] = user;
        var identity = new ClaimsIdentity([
            new Claim(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new Claim(ClaimTypes.Name, user.UserName),
            new Claim(ClaimTypes.Role, user.Role)
        ], SchemeName);
        return AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName));
    }

    protected override Task HandleChallengeAsync(AuthenticationProperties properties)
    {
        Response.StatusCode = 401;
        return Response.WriteAsJsonAsync(new { code = "unauthorized", message = "يلزم تسجيل الدخول." });
    }
    protected override Task HandleForbiddenAsync(AuthenticationProperties properties)
    {
        Response.StatusCode = 403;
        return Response.WriteAsJsonAsync(new { code = "forbidden", message = "ليست لديك صلاحية هذه العملية." });
    }
}

public sealed class Accounts(PasswordHasher<Account> hasher)
{
    // Random, process-local dummy hash equalizes unknown-user verification; this is never an account credential.
    private readonly string dummyHash = hasher.HashPassword(new Account(Guid.Empty, "", "", "Learner"),
        Convert.ToHexString(RandomNumberGenerator.GetBytes(32)));

    public string Hash(Account account, string password) => hasher.HashPassword(account, password);
    public PasswordVerificationResult Verify(Account? account, string? hash, string password) =>
        hasher.VerifyHashedPassword(account ?? new Account(Guid.Empty, "", "", "Learner"), hash ?? dummyHash, password);
}

public static class AuthEndpoints
{
    public static void MapAuth(this WebApplication app)
    {
        app.MapGet("/api/v1/auth/csrf", (HttpContext ctx, IAntiforgery anti) =>
        {
            ctx.Response.Headers.CacheControl = "no-store";
            Guid? userId = ctx.User.Identity?.IsAuthenticated == true ? Input.UserId(ctx) : null;
            return Results.Ok(new { token = anti.GetAndStoreTokens(ctx).RequestToken, userId });
        });

        app.MapPost("/api/v1/auth/register", async (RegisterRequest request, HttpContext ctx, Db db, Accounts passwords, CancellationToken ct) =>
        {
            var name = Input.UserName(request.UserName);
            var display = Input.Text(request.DisplayName, 2, 80);
            var password = Input.Text(request.Password, 12, 128, false);
            var user = new Account(Guid.NewGuid(), name, display, "Learner");
            var hash = passwords.Hash(user, password);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            try
            {
                await Db.Execute(conn, tx, """
                    INSERT INTO public.users(id,user_name,normalized_user_name,display_name,password_hash,role)
                    VALUES (@id,@name,@name,@display,@hash,'Learner')
                    """, ct, ("id", user.Id), ("name", name), ("display", display), ("hash", hash));
            }
            catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
            { throw ApiError.Conflict("user_name_unavailable"); }
            await RevokeCurrent(ctx, conn, tx, ct);
            var token = await CreateSession(conn, tx, user.Id, ct);
            await Db.Audit(conn, tx, user.Id, "account.register", user.Id.ToString(), ct: ct);
            await tx.CommitAsync(ct);
            WriteSession(ctx, token);
            return Results.Json(new { user }, statusCode: 201);
        }).RequireRateLimiting("auth");

        app.MapPost("/api/v1/auth/login", async (LoginRequest request, HttpContext ctx, Db db, Accounts passwords, CancellationToken ct) =>
        {
            // Even malformed names receive the same response and a standard hash verification.
            var rawName = request.UserName ?? "";
            var password = request.Password ?? "";
            if (rawName.Length > 160 || password.Length > 128)
                throw LoginFailed();
            string name;
            try { name = Input.UserName(rawName); }
            catch (ApiError) { name = "!invalid-" + Input.Hash(rawName); }
            var key = Input.Hash(name);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            await Db.Execute(conn, tx, "INSERT INTO public.login_failures(key_hash) VALUES (@key) ON CONFLICT DO NOTHING", ct, ("key", key));
            var locked = await Db.Scalar<bool>(conn, tx, """
                SELECT COALESCE(blocked_until>now(),false) FROM public.login_failures WHERE key_hash=@key FOR UPDATE
                """, ct, ("key", key));
            if (locked)
            {
                passwords.Verify(null, null, password);
                await tx.CommitAsync(ct);
                throw LoginFailed();
            }
            var matches = await Db.Query(conn, tx, """
                SELECT id,user_name,display_name,role,password_hash FROM public.users WHERE normalized_user_name=@name
                """, r => (User: new Account(r.GetGuid(0), r.GetString(1), r.GetString(2), r.GetString(3)), Hash: r.GetString(4)), ct, ("name", name));
            var match = matches.FirstOrDefault();
            var verified = passwords.Verify(match.User, match.Hash, password);
            if (match.User is null || verified == PasswordVerificationResult.Failed || password.Length < 12)
            {
                await Db.Execute(conn, tx, """
                    UPDATE public.login_failures SET
                      failures=CASE WHEN window_started_at<now()-interval '15 minutes' THEN 1 ELSE failures+1 END,
                      blocked_until=CASE WHEN window_started_at>=now()-interval '15 minutes' AND failures+1>=5
                                         THEN now()+interval '15 minutes' ELSE NULL END,
                      window_started_at=CASE WHEN window_started_at<now()-interval '15 minutes' THEN now() ELSE window_started_at END
                    WHERE key_hash=@key
                    """, ct, ("key", key));
                await tx.CommitAsync(ct);
                throw LoginFailed();
            }
            if (verified == PasswordVerificationResult.SuccessRehashNeeded)
                await Db.Execute(conn, tx, "UPDATE public.users SET password_hash=@hash WHERE id=@id", ct,
                    ("hash", passwords.Hash(match.User, password)), ("id", match.User.Id));
            await Db.Execute(conn, tx, "DELETE FROM public.login_failures WHERE key_hash=@key", ct, ("key", key));
            // Rotate any existing browser session without trusting client-supplied identity.
            await RevokeCurrent(ctx, conn, tx, ct);
            var token = await CreateSession(conn, tx, match.User.Id, ct);
            await tx.CommitAsync(ct);
            WriteSession(ctx, token);
            return Results.Ok(new { user = match.User });
        }).RequireRateLimiting("auth");

        app.MapGet("/api/v1/auth/me", (HttpContext ctx) => Results.Ok(new { user = (Account)ctx.Items["Masar.Account"]! }))
            .RequireAuthorization();
        app.MapPost("/api/v1/auth/logout", async (HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            await RevokeCurrent(ctx, conn, null, ct);
            ctx.Response.Cookies.Delete(SessionCookie(ctx), CookieOptions(ctx));
            return Results.NoContent();
        }).RequireAuthorization();
    }

    private static ApiError LoginFailed() => new(401, "invalid_credentials", "تعذر تسجيل الدخول بهذه البيانات. حاول لاحقًا إذا تكررت المحاولات.");

    private static async Task<string> CreateSession(NpgsqlConnection conn, NpgsqlTransaction tx, Guid userId, CancellationToken ct)
    {
        var token = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
        await Db.Execute(conn, tx, """
            INSERT INTO public.sessions(token_hash,user_id,expires_at) VALUES (@hash,@user,now()+interval '8 hours')
            """, ct, ("hash", Input.Hash(token)), ("user", userId));
        return token;
    }

    private static Task<int> RevokeCurrent(HttpContext ctx, NpgsqlConnection conn, NpgsqlTransaction? tx, CancellationToken ct)
    {
        var token = ctx.Request.Cookies[SessionCookie(ctx)];
        return string.IsNullOrEmpty(token) ? Task.FromResult(0) : Db.Execute(conn, tx,
            "UPDATE public.sessions SET revoked_at=now() WHERE token_hash=@hash AND revoked_at IS NULL", ct, ("hash", Input.Hash(token)));
    }

    private static string SessionCookie(HttpContext ctx) =>
        ctx.RequestServices.GetRequiredService<CommercialOptions>().CookieName("Session");

    private static CookieOptions CookieOptions(HttpContext ctx) => new()
    {
        HttpOnly = true, Secure = ctx.Request.IsHttps, SameSite = SameSiteMode.Strict,
        Path = ctx.Request.PathBase.HasValue ? ctx.Request.PathBase.Value : "/", IsEssential = true
    };
    private static void WriteSession(HttpContext ctx, string token)
    {
        var options = CookieOptions(ctx);
        options.MaxAge = TimeSpan.FromHours(8);
        ctx.Response.Cookies.Append(SessionCookie(ctx), token, options);
        ctx.Response.Headers.CacheControl = "no-store";
    }
}
