using System.Text.Json.Nodes;
using Masar.Domain;
using Npgsql;

namespace Masar.Api;

public sealed record Release(Guid Id, string ReleaseId, string Title, string Status, int Version, JsonObject Bundle);
public sealed record ReleaseRequest(JsonObject? Bundle);
public sealed record TransitionRequest(string? Status, int ExpectedVersion);
public sealed record ActivateReleaseRequest(int ExpectedVersion);

public static class Content
{
    // Take the selection lock before any release row lock, including during initial import.
    private const long ActiveReleaseLock = 632793228503L;

    public static async Task<Release> Find(NpgsqlConnection conn, string releaseId, CancellationToken ct,
        NpgsqlTransaction? tx = null, bool requirePublished = true)
    {
        var releases = await Db.Query(conn, tx, """
            SELECT id,release_id,title,status,version,bundle::text FROM public.content_releases
            WHERE release_id=@release AND (NOT @published OR status='published')
            """, Read, ct, ("release", Input.Id(releaseId)), ("published", requirePublished));
        return releases.FirstOrDefault() ?? throw ApiError.Missing();
    }

    public static Release Read(NpgsqlDataReader reader) => new(reader.GetGuid(0), reader.GetString(1), reader.GetString(2),
        reader.GetString(3), reader.GetInt32(4), JsonNode.Parse(reader.GetString(5))!.AsObject());

    public static void Validate(JsonObject bundle)
    {
        var errors = CurriculumEngine.Validate(bundle);
        if (errors.Count > 0) throw new ApiError(400, "invalid_content", "المحتوى غير صالح: " + string.Join("؛ ", errors.Take(8)));
        // API/database identifiers have explicit storage and routing bounds in addition to graph validation.
        Input.Id(Input.String(bundle["sample"]?["releaseId"]));
        Input.Text(Input.String(bundle["sample"]?["title"]), 1, 300);
        foreach (var lesson in Lessons(bundle))
        {
            Input.Id(Input.String(lesson["id"]));
            foreach (var exercise in Exercises(lesson)) Input.Id(Input.String(exercise["id"]));
        }
        CodeLabCatalog.Validate(bundle);
        CurriculumPresentation.Validate(bundle);
    }

    public static IEnumerable<JsonObject> Lessons(JsonObject bundle) =>
        (bundle["sample"]?["lessons"] as JsonArray ?? []).OfType<JsonObject>();
    public static IEnumerable<JsonObject> Exercises(JsonObject lesson) =>
        (lesson["exercises"] as JsonArray ?? []).OfType<JsonObject>();

    public static JsonObject Lesson(Release release, string id) =>
        Lessons(release.Bundle).FirstOrDefault(l => Input.String(l["id"]) == id) ?? throw ApiError.Missing();
    public static JsonObject Exercise(Release release, string exerciseId, string? lessonId = null)
    {
        var lessons = lessonId is null ? Lessons(release.Bundle) : [Lesson(release, lessonId)];
        return lessons.SelectMany(Exercises).FirstOrDefault(x => Input.String(x["id"]) == exerciseId) ?? throw ApiError.Missing();
    }

    public static JsonObject PublicBundle(JsonObject bundle)
    {
        var clone = bundle.DeepClone().AsObject();
        clone.Remove("codeLab");
        ScrubAnswers(clone);
        foreach (var lesson in Lessons(clone))
            foreach (var exercise in Exercises(lesson)) exercise.Remove("explanation");
        return clone;
    }
    private static void ScrubAnswers(JsonNode? node)
    {
        if (node is JsonObject obj)
        {
            obj.Remove("acceptedAnswers");
            foreach (var value in obj.ToArray()) ScrubAnswers(value.Value);
        }
        else if (node is JsonArray array) foreach (var value in array) ScrubAnswers(value);
    }

    public static void MapContent(this WebApplication app)
    {
        app.MapGet("/api/v1/catalog", async (Db db, CommercialOptions commercial, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            // Read selection and published releases in one snapshot so a concurrent retirement cannot cause a 404.
            var rows = await Db.Query(conn, null, """
                SELECT r.id,r.release_id,r.title,r.status,s.key IS NOT NULL,
                       CASE WHEN s.key IS NOT NULL THEN (r.bundle #> '{graph,goals}')::text END
                FROM public.content_releases r
                LEFT JOIN public.settings s ON s.key='active_release_id' AND s.value=r.release_id
                WHERE r.status='published'
                ORDER BY r.created_at,r.release_id
                """, r => (
                    Release: new { id = r.GetGuid(0), releaseId = r.GetString(1), title = r.GetString(2), status = r.GetString(3) },
                    Active: r.GetBoolean(4),
                    Goals: r.IsDBNull(5) ? null : JsonNode.Parse(r.GetString(5)) as JsonArray), ct);
            var active = rows.FirstOrDefault(row => row.Active);
            var goals = (active.Goals ?? []).OfType<JsonObject>().Select(goal => new
            {
                id = Input.String(goal["id"]),
                title = Input.String(goal["title"]),
                description = Input.String(goal["description"]),
                status = Input.String(goal["status"]),
                skillIds = (goal["skillIds"] as JsonArray ?? []).Select(Input.String).ToArray()
            });
            var catalog = new Dictionary<string, object?>
            {
                ["releases"] = rows.Select(row => row.Release), ["goals"] = goals,
                ["activeReleaseId"] = active.Release?.releaseId, ["accessRequired"] = commercial.Required
            };
            if (commercial.ContactUrl is not null) catalog["contactUrl"] = commercial.ContactUrl;
            return Results.Ok(catalog);
        });

        app.MapGet("/api/v1/content/{releaseId}", async (string releaseId, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Find(conn, releaseId, ct);
            var clean = PublicBundle(release.Bundle);
            return Results.Ok(new { release.Id, release.ReleaseId, release.Title, release.Status, sample = clean["sample"], graph = clean["graph"] });
        });
        app.MapGet("/api/v1/content/{releaseId}/lessons/{lessonId}", async (string releaseId, string lessonId, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Find(conn, releaseId, ct);
            var safe = release with { Bundle = PublicBundle(release.Bundle) };
            return Results.Ok(Lesson(safe, Input.Id(lessonId)));
        });
        app.MapGet("/api/v1/admin/releases", async (Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var rows = await Db.Query(conn, null, """
                SELECT r.id,r.release_id,r.title,r.status,r.version,r.created_at,s.key IS NOT NULL
                FROM public.content_releases r
                LEFT JOIN public.settings s ON s.key='active_release_id' AND s.value=r.release_id AND r.status='published'
                ORDER BY r.created_at DESC
                """, r => (
                    Release: new { id = r.GetGuid(0), releaseId = r.GetString(1), title = r.GetString(2), status = r.GetString(3), version = r.GetInt32(4), createdAt = r.GetDateTime(5) },
                    Active: r.GetBoolean(6)), ct);
            return Results.Ok(new { releases = rows.Select(row => row.Release), activeReleaseId = rows.FirstOrDefault(row => row.Active).Release?.releaseId });
        }).RequireAuthorization("ContentStaff");

        app.MapPost("/api/v1/admin/releases", async (ReleaseRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            var bundle = request.Bundle ?? throw ApiError.Invalid();
            Validate(bundle);
            var id = Guid.NewGuid();
            var releaseId = Input.String(bundle["sample"]?["releaseId"]);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            try
            {
                await Db.Execute(conn, tx, """
                    INSERT INTO public.content_releases(id,release_id,title,bundle,created_by)
                    VALUES (@id,@release,@title,@bundle::jsonb,@actor)
                    """, ct, ("id", id), ("release", releaseId), ("title", Input.String(bundle["sample"]?["title"])),
                    ("bundle", bundle.ToJsonString()), ("actor", Input.UserId(ctx)));
            }
            catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
            { throw ApiError.Conflict("release_exists"); }
            await Db.Audit(conn, tx, Input.UserId(ctx), "release.create", id.ToString(), ct: ct);
            await tx.CommitAsync(ct);
            return Results.Json(new { id, releaseId, status = "draft", version = 1 }, statusCode: 201);
        }).RequireAuthorization("ContentAuthor");

        app.MapPost("/api/v1/admin/releases/{id:guid}/transition", async (Guid id, TransitionRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            if (request.ExpectedVersion < 1) throw ApiError.Invalid();
            var target = Input.Text(request.Status, 1, 30);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            if (target == "retired") await LockActiveRelease(conn, tx, ct);
            var releases = await Db.Query(conn, tx, """
                SELECT id,release_id,title,status,version,bundle::text FROM public.content_releases WHERE id=@id FOR UPDATE
                """, Read, ct, ("id", id));
            var release = releases.FirstOrDefault() ?? throw ApiError.Missing();
            if (release.Version != request.ExpectedVersion) throw ApiError.Conflict();
            var next = release.Status switch
            {
                "draft" => "technical_review", "technical_review" => "learning_review",
                "learning_review" => "published", "published" => "retired", _ => ""
            };
            if (target != next) throw new ApiError(400, "invalid_transition", "هذا الانتقال غير مسموح من الحالة الحالية.");
            var isAdmin = ctx.User.IsInRole("Admin");
            var permitted = release.Status == "draft"
                ? ctx.User.IsInRole("Author") || isAdmin
                : ctx.User.IsInRole("Reviewer") || isAdmin;
            if (!permitted) throw new ApiError(403, "forbidden", "ليست لديك صلاحية هذه العملية.");
            Validate(release.Bundle);
            await Db.Execute(conn, tx, """
                UPDATE public.content_releases SET status=@status,version=version+1,
                published_at=CASE WHEN @status='published' THEN now() ELSE published_at END WHERE id=@id
                """, ct, ("status", target), ("id", id));
            if (target == "retired")
            {
                var cleared = await Db.Execute(conn, tx, """
                    DELETE FROM public.settings WHERE key='active_release_id' AND value=@release
                    """, ct, ("release", release.ReleaseId));
                if (cleared == 1)
                    await Db.Audit(conn, tx, Input.UserId(ctx), "release.deactivate", id.ToString(),
                        new JsonObject { ["from"] = release.ReleaseId, ["to"] = null, ["reason"] = "retired" }, ct);
            }
            await Db.Audit(conn, tx, Input.UserId(ctx), "release.transition", id.ToString(),
                new JsonObject { ["from"] = release.Status, ["to"] = target, ["version"] = release.Version + 1 }, ct);
            await tx.CommitAsync(ct);
            return Results.Ok(new { id, release.ReleaseId, status = target, version = release.Version + 1 });
        }).RequireAuthorization("ContentStaff");

        app.MapPost("/api/v1/admin/releases/{id:guid}/activate", async (Guid id, ActivateReleaseRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            if (request.ExpectedVersion < 1) throw ApiError.Invalid();
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            await LockActiveRelease(conn, tx, ct);
            var releases = await Db.Query(conn, tx, """
                SELECT release_id,status,version FROM public.content_releases WHERE id=@id FOR UPDATE
                """, r => (ReleaseId: r.GetString(0), Status: r.GetString(1), Version: r.GetInt32(2)), ct, ("id", id));
            if (releases.Count == 0) throw ApiError.Missing();
            var release = releases[0];
            if (release.Version != request.ExpectedVersion) throw ApiError.Conflict();
            if (release.Status != "published")
                throw new ApiError(400, "release_not_published", "يمكن تفعيل إصدار منشور فقط.");

            var previous = await Db.Scalar<string>(conn, tx, "SELECT value FROM public.settings WHERE key='active_release_id'", ct);
            var version = release.Version + 1;
            await Db.Execute(conn, tx, "UPDATE public.content_releases SET version=@version WHERE id=@id", ct, ("version", version), ("id", id));
            await Db.Execute(conn, tx, """
                INSERT INTO public.settings(key,value) VALUES ('active_release_id',@release)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
                """, ct, ("release", release.ReleaseId));
            await Db.Audit(conn, tx, Input.UserId(ctx), "release.activate", id.ToString(),
                new JsonObject { ["from"] = previous, ["to"] = release.ReleaseId, ["version"] = version }, ct);
            await tx.CommitAsync(ct);
            return Results.Ok(new { id, release.ReleaseId, release.Status, version, activeReleaseId = release.ReleaseId });
        }).RequireAuthorization("ContentReviewer");
    }

    internal static Task LockActiveRelease(NpgsqlConnection conn, NpgsqlTransaction tx, CancellationToken ct = default) =>
        Db.Scalar<bool>(conn, tx, "SELECT pg_advisory_xact_lock(@key) IS NULL", ct, ("key", ActiveReleaseLock));
}
