using System.Net;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.RateLimiting;
using Masar.Api;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.RateLimiting;
using Npgsql;

var maintenance = args.Any(a => a is "--migrate" or "--import-bundle" or "--publish-initial" or "--promote-admin"
    or "--verify-curriculum" or "--publish-reviewed-curriculum");
var builder = WebApplication.CreateBuilder(new WebApplicationOptions { Args = maintenance ? [] : args });
// Do not log request query strings, payloads, cookies, SQL exceptions or connection strings.
builder.Logging.ClearProviders();
builder.Logging.AddSimpleConsole();
builder.Logging.AddFilter("Microsoft.AspNetCore.Hosting.Diagnostics", LogLevel.Warning);
builder.Logging.AddFilter("Microsoft.AspNetCore.Http.RequestDelegateFactory", LogLevel.Warning);
builder.Logging.AddFilter("Npgsql", LogLevel.None);

if (maintenance)
{
    Environment.ExitCode = await Maintenance.Run(args, builder.Configuration, builder.Environment.IsDevelopment());
    return;
}

var development = builder.Environment.IsDevelopment();
var pilotFunnel = development && builder.Configuration.GetValue<bool>("MASAR_PILOT_FUNNEL");
var pilotPath = new PathString("/nexora-pilot");
var commercialValue = builder.Configuration["MASAR_COMMERCIAL_ENABLED"];
if (commercialValue is not null && !bool.TryParse(commercialValue, out _))
    throw new InvalidOperationException("Masar: MASAR_COMMERCIAL_ENABLED must be true or false.");
var commercialRequired = commercialValue is not null && bool.Parse(commercialValue);
if (pilotFunnel && commercialRequired)
    throw new InvalidOperationException("Masar: the pilot and commercial profiles must use separate listeners.");
var commercialProxy = CommercialProxy.Read(builder.Configuration, commercialRequired, development);
var contactUrl = builder.Configuration["MASAR_COMMERCIAL_CONTACT_URL"];
if (contactUrl is not null && (!Uri.TryCreate(contactUrl, UriKind.Absolute, out var contactUri) ||
    contactUri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(contactUri.UserInfo)))
    throw new InvalidOperationException("Masar: MASAR_COMMERCIAL_CONTACT_URL must be an absolute HTTPS URL.");
const int defaultDailyExecutions = 300;
var dailyExecutionLimit = defaultDailyExecutions;
var configuredLimit = builder.Configuration["MASAR_COMMERCIAL_DAILY_EXECUTIONS"];
if (commercialRequired && configuredLimit is not null &&
    (!int.TryParse(configuredLimit, out dailyExecutionLimit) || dailyExecutionLimit is < 1 or > 10000))
    throw new InvalidOperationException("Masar: invalid commercial execution limit.");
var sessionNamespace = commercialRequired ? builder.Configuration["MASAR_COMMERCIAL_SESSION_NAMESPACE"] ?? "Commercial" : null;
if (sessionNamespace is not null and not ("Commercial" or "CommercialTest"))
    throw new InvalidOperationException("Masar: invalid commercial session namespace.");
var commercialOptions = new CommercialOptions(commercialRequired, contactUrl, dailyExecutionLimit, sessionNamespace);
builder.Services.AddSingleton(commercialOptions);
var urls = builder.Configuration["urls"] ?? "http://127.0.0.1:5180";
var configuredUrls = urls.Split(';', StringSplitOptions.RemoveEmptyEntries).Concat(
    builder.Configuration.GetSection("Kestrel:Endpoints").GetChildren().Select(c => c["Url"]).OfType<string>());
foreach (var value in configuredUrls)
{
    if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") ||
        !string.IsNullOrEmpty(uri.UserInfo) || uri.AbsolutePath != "/")
        throw new InvalidOperationException("Masar: invalid listening address.");
    if (!development && commercialProxy is null && uri.Scheme != "https")
        throw new InvalidOperationException("Masar: HTTPS is required outside Development.");
    if (development && uri.Host != "localhost" && !(IPAddress.TryParse(uri.Host, out var ip) && IPAddress.IsLoopback(ip)))
        throw new InvalidOperationException("Masar: Development must listen on localhost only.");
    if (commercialProxy is not null && !CommercialProxy.IsLoopbackListener(uri))
        throw new InvalidOperationException("Masar: the commercial proxy backend must listen on loopback only.");
}
builder.WebHost.UseUrls(urls);
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 1_048_576);
builder.Services.Configure<Microsoft.AspNetCore.Routing.RouteHandlerOptions>(options => options.ThrowOnBadRequest = true);
builder.Services.Configure<JsonOptions>(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
    options.SerializerOptions.DictionaryKeyPolicy = JsonNamingPolicy.CamelCase;
    options.SerializerOptions.MaxDepth = 64;
});
builder.Services.AddResponseCompression(options =>
{
    options.EnableForHttps = true;
    options.MimeTypes = ["application/javascript", "text/javascript", "text/css"];
});

var dataRoot = Environment.GetEnvironmentVariable("MASAR_DATA_ROOT");
if (string.IsNullOrWhiteSpace(dataRoot) || !Path.IsPathFullyQualified(dataRoot))
    throw new InvalidOperationException("Masar: MASAR_DATA_ROOT must be an absolute persistent local path.");
var keys = builder.Services.AddDataProtection().SetApplicationName(sessionNamespace is null ? "Masar.Phase2.Local" : $"Masar.{sessionNamespace}")
    .PersistKeysToFileSystem(new DirectoryInfo(Path.Combine(dataRoot, "data-protection-keys")));
if (OperatingSystem.IsWindows()) keys.ProtectKeysWithDpapi();
else if (!development) throw new InvalidOperationException("Masar: configure protected key storage before using this platform outside Development.");

var connectionString = builder.Configuration.GetConnectionString("Masar");
if (string.IsNullOrWhiteSpace(connectionString)) throw new InvalidOperationException("Masar: runtime connection is required.");
var connectionOptions = new NpgsqlConnectionStringBuilder(connectionString) { IncludeErrorDetail = false, LogParameters = false };
builder.Services.AddSingleton(NpgsqlDataSource.Create(connectionOptions.ConnectionString));
builder.Services.AddSingleton<Db>();
builder.Services.AddCodeLab();
builder.Services.AddSingleton(new PasswordHasher<Account>());
builder.Services.AddSingleton<Accounts>();
builder.Services.AddAuthentication(SessionAuthenticationHandler.SchemeName)
    .AddScheme<AuthenticationSchemeOptions, SessionAuthenticationHandler>(SessionAuthenticationHandler.SchemeName, _ => { });
builder.Services.AddAuthorization(options =>
{
    options.AddPolicy("ContentStaff", policy => policy.RequireRole("Author", "Reviewer", "Admin"));
    options.AddPolicy("ContentAuthor", policy => policy.RequireRole("Author", "Admin"));
    options.AddPolicy("ContentReviewer", policy => policy.RequireRole("Reviewer", "Admin"));
});
builder.Services.AddAntiforgery(options =>
{
    options.HeaderName = "X-CSRF-TOKEN";
    options.Cookie.Name = commercialOptions.CookieName("Csrf");
    options.Cookie.HttpOnly = true;
    options.Cookie.SameSite = SameSiteMode.Strict;
    options.Cookie.SecurePolicy = development ? CookieSecurePolicy.SameAsRequest : CookieSecurePolicy.Always;
    if (commercialProxy?.PathBase is { HasValue: true } publicPath)
        options.Cookie.Path = publicPath.Value;
});
builder.Services.AddRateLimiter(options =>
{
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(ctx =>
        RateLimitPartition.GetFixedWindowLimiter(ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown", _ => new FixedWindowRateLimiterOptions
        { PermitLimit = 120, Window = TimeSpan.FromMinutes(1), QueueLimit = 0, AutoReplenishment = true }));
    options.AddPolicy("auth", ctx => RateLimitPartition.GetFixedWindowLimiter(
        ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown", _ => new FixedWindowRateLimiterOptions
        { PermitLimit = 12, Window = TimeSpan.FromMinutes(1), QueueLimit = 0, AutoReplenishment = true }));
    options.OnRejected = async (context, ct) =>
    {
        context.HttpContext.Response.StatusCode = 429;
        context.HttpContext.Response.Headers.RetryAfter = "60";
        await context.HttpContext.Response.WriteAsJsonAsync(new { code = "rate_limited", message = "طلبات كثيرة؛ انتظر قليلًا ثم حاول مجددًا." }, ct);
    };
});

var app = builder.Build();
// Refuse to serve requests with an unusable key ring; never silently fall back to plaintext or ephemeral keys.
var protectionProbe = app.Services.GetRequiredService<IDataProtectionProvider>().CreateProtector("Masar.StartupProbe");
_ = protectionProbe.Unprotect(protectionProbe.Protect("key-ring-check"));
if (pilotFunnel) app.UsePathBase(pilotPath);
commercialProxy?.UseForwarding(app);
app.Use(async (ctx, next) =>
{
    ctx.Response.Headers.XContentTypeOptions = "nosniff";
    ctx.Response.Headers.XFrameOptions = "DENY";
    ctx.Response.Headers["Referrer-Policy"] = "same-origin";
    ctx.Response.Headers.ContentSecurityPolicy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
    if (ctx.Request.Path.StartsWithSegments("/api")) ctx.Response.Headers.CacheControl = "no-store";
    try
    {
        commercialProxy?.RequirePublicTarget(ctx);
        if (!development && !ctx.Request.IsHttps) throw new ApiError(400, "https_required", "يلزم اتصال HTTPS.");
        if (development && ctx.Connection.RemoteIpAddress is { } remote && !IPAddress.IsLoopback(remote))
            throw new ApiError(403, "localhost_only", "بيئة التطوير متاحة محليًا فقط.");
        await next();
        if (!ctx.Response.HasStarted && ctx.Response.StatusCode >= 400 && string.IsNullOrEmpty(ctx.Response.ContentType))
        {
            var code = ctx.Response.StatusCode switch { 401 => "unauthorized", 403 => "forbidden", 404 => "not_found", 405 => "method_not_allowed", _ => "request_failed" };
            var message = ctx.Response.StatusCode switch { 401 => "يلزم تسجيل الدخول.", 403 => "ليست لديك صلاحية هذه العملية.", 404 => "المورد غير موجود.", _ => "تعذر تنفيذ الطلب." };
            await ctx.Response.WriteAsJsonAsync(new { code, message });
        }
    }
    catch (OperationCanceledException) when (ctx.RequestAborted.IsCancellationRequested) { }
    catch (Exception ex) when (!ctx.Response.HasStarted)
    {
        var error = ex switch
        {
            ApiError known => known,
            BadHttpRequestException bad => new ApiError(bad.StatusCode, "invalid_request", "الطلب غير صالح أو يتجاوز الحد المسموح."),
            AntiforgeryValidationException => new ApiError(400, "csrf_invalid", "رمز حماية الطلب غير صالح؛ حدّث الصفحة ثم حاول مجددًا."),
            NpgsqlException failure when failure.IsTransient ||
                failure is PostgresException { SqlState: "53200" or "53300" or "57P03" } =>
                new ApiError(503, "service_unavailable", HttpMethods.IsGet(ctx.Request.Method) || HttpMethods.IsHead(ctx.Request.Method)
                    ? "الخدمة غير متاحة مؤقتًا. أعد المحاولة بعد قليل."
                    : "تعذر الاتصال بالخدمة. لم نؤكد نتيجة الطلب؛ حدّث الصفحة للتحقق قبل إعادة إرساله."),
            _ => new ApiError(500, "server_error", "تعذر إتمام العملية الآن.")
        };
        if (error.Status == 500) app.Logger.LogError("Request failed ({ExceptionType}).", ex.GetType().Name);
        if (error.Code == "service_unavailable")
            app.Logger.LogWarning("Database service temporarily unavailable ({ExceptionType}, {SqlState}).",
                ex.GetType().Name, (ex as PostgresException)?.SqlState ?? "connection");
        ctx.Response.Clear();
        ctx.Response.StatusCode = error.Status;
        ctx.Response.Headers.CacheControl = "no-store";
        await ctx.Response.WriteAsJsonAsync(new { code = error.Code, message = error.Message });
    }
});
// Limit HTTPS compression and immutable caching to Vite's public fingerprinted scripts and styles.
// Private API responses, HTML and project downloads retain their existing delivery rules.
var viteAssetPattern = new Regex(@"\A/assets/[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css)\z", RegexOptions.CultureInvariant);
app.UseWhen(ctx => (HttpMethods.IsGet(ctx.Request.Method) || HttpMethods.IsHead(ctx.Request.Method)) &&
                   viteAssetPattern.IsMatch(ctx.Request.Path.Value ?? ""),
    branch => branch.UseResponseCompression());
var staticFiles = new StaticFileOptions
{
    OnPrepareResponse = file =>
    {
        var ctx = file.Context;
        if (ctx.Response.StatusCode is 200 or 206 or 304 && viteAssetPattern.IsMatch(ctx.Request.Path.Value ?? ""))
        {
            ctx.Response.Headers.CacheControl = "public,max-age=31536000,immutable";
            ctx.Response.Headers.AppendCommaSeparatedValues("Vary", "Accept-Encoding");
        }
    }
};
if (pilotFunnel)
{
    // The transport peer has already passed the loopback check. Tailscale replaces these headers.
    app.UseForwardedHeaders(new ForwardedHeadersOptions
    {
        ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto,
        ForwardLimit = 1
    });
    app.Use(async (ctx, next) =>
    {
        if (ctx.Request.IsHttps && ctx.Request.Path.StartsWithSegments("/api") && ctx.Request.PathBase != pilotPath)
        {
            ctx.Response.StatusCode = StatusCodes.Status404NotFound;
            return;
        }
        await next();
    });
    // Keep the learner request budget for API actions instead of fonts and bundled assets.
    app.UseWhen(ctx => !ctx.Request.Path.StartsWithSegments("/projects"), branch =>
    {
        branch.UseDefaultFiles();
        branch.UseStaticFiles(staticFiles);
    });
}
if (!development) app.UseHsts();
app.UseRouting();
app.UseRateLimiter();
app.UseAuthentication();
app.Use(async (ctx, next) =>
{
    if (ctx.Request.Path.StartsWithSegments("/api") &&
        !HttpMethods.IsGet(ctx.Request.Method) && !HttpMethods.IsHead(ctx.Request.Method) && !HttpMethods.IsOptions(ctx.Request.Method))
    {
        // Includes anonymous login/register/preview and unknown unsafe API routes.
        await ctx.RequestServices.GetRequiredService<IAntiforgery>().ValidateRequestAsync(ctx);
    }
    await next();
});
app.UseAuthorization();
app.Use(CommercialAccess.Gate);
app.UseDefaultFiles();
app.UseStaticFiles(staticFiles);
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));
app.MapGet("/api/v1/health", async (Db db, CommercialOptions commercial, CancellationToken ct) =>
{
    try
    {
        await using var conn = await db.Open(ct);
        var ready = await Db.Scalar<bool>(conn, null, """
            SELECT to_regclass('public.users') IS NOT NULL AND to_regclass('public.masar_schema_migrations') IS NOT NULL
                AND (NOT @commercial OR (
                    to_regclass('public.commercial_access') IS NOT NULL
                    AND to_regclass('public.commercial_scope_access') IS NOT NULL
                    AND to_regclass('public.commercial_offers') IS NOT NULL
                    AND has_table_privilege(current_user, to_regclass('public.commercial_scope_access'), 'SELECT')
                    AND has_table_privilege(current_user, to_regclass('public.commercial_offers'), 'SELECT')
                ))
            """, ct, ("commercial", commercial.Required));
        return ready ? Results.Ok(new { status = "ok", database = "available" })
            : Results.Json(new { code = "database_not_initialized", message = "قاعدة البيانات غير مهيأة." }, statusCode: 503);
    }
    catch (Exception) when (!ct.IsCancellationRequested)
    { return Results.Json(new { code = "database_unavailable", message = "قاعدة البيانات غير متاحة الآن." }, statusCode: 503); }
});
app.MapAuth();
app.MapCommercialAccess();
app.MapPurchaseRequests();
app.MapContent();
app.MapLearning();
app.MapCodeLab();
// Reserve the entire API namespace so the SPA fallback can never turn API 404 into HTML.
app.Map("/api/{**path}", () => Results.Json(new { code = "not_found", message = "المورد غير موجود." }, statusCode: 404));
app.MapFallbackToFile("index.html");
await app.RunAsync();

public partial class Program;
