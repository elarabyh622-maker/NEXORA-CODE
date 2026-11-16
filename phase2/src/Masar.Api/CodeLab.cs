using System.Text;

namespace Masar.Api;

internal sealed record CodeLabDraftRequest(string? Code, int? ExpectedVersion);

internal sealed record CodeLabRunRequest(
    string? ReleaseId, string? LessonId, string? ExerciseId, string? Code, string? Mode,
    string? IdempotencyKey, string? Input);

internal static class CodeLab
{
    private const int CodeBytes = 16 * 1024;
    private const int InputBytes = 4 * 1024;

    public static void AddCodeLab(this IServiceCollection services)
    {
        services.AddSingleton<CodeLabRunner>();
        services.AddSingleton<CodeLabQueue>();
        services.AddHostedService<CodeLabWorker>();
    }

    public static void MapCodeLab(this WebApplication app)
    {
        var lab = app.MapGroup("/api/v1/lab");
        lab.MapGet("/exercises/{releaseId}/{lessonId}", async (
            string releaseId, string lessonId, Db db, CodeLabRunner runner, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Content.Find(conn, releaseId, ct);
            lessonId = Input.Id(lessonId);
            Content.Lesson(release, lessonId);
            var exercises = CodeLabCatalog.ForRelease(release).Where(definition => definition.LessonId == lessonId)
                .Select(definition => definition.Exercise).ToArray();
            return Results.Ok(new { available = runner.Available, exercises });
        });

        lab.MapGet("/drafts/{releaseId}/{exerciseId}", async (
            string releaseId, string exerciseId, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var drafts = await Db.Query(conn, null, """
                SELECT code,version FROM public.code_lab_drafts
                WHERE user_id=@user AND release_id=@release AND exercise_id=@exercise
                """, row => new { code = row.GetString(0), version = row.GetInt32(1) }, ct,
                ("user", Input.UserId(ctx)), ("release", Input.Id(releaseId)), ("exercise", Input.Id(exerciseId)));
            return Results.Ok(drafts.FirstOrDefault() ?? throw ApiError.Missing());
        }).RequireAuthorization();

        lab.MapPut("/drafts/{releaseId}/{exerciseId}", async (
            string releaseId, string exerciseId, CodeLabDraftRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            var code = BoundedText(request.Code, 0, CodeBytes);
            var expectedVersion = request.ExpectedVersion;
            if (expectedVersion is null or < 0 or int.MaxValue) throw ApiError.Invalid();
            exerciseId = Input.Id(exerciseId);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            var release = await CodeLabQueue.RequirePublished(conn, tx, Input.Id(releaseId), ct);
            if (!CodeLabCatalog.ForRelease(release).Any(definition => definition.Exercise.Id == exerciseId))
                throw ApiError.Missing();

            var userId = Input.UserId(ctx);
            var changed = expectedVersion == 0
                ? await Db.Execute(conn, tx, """
                    INSERT INTO public.code_lab_drafts(user_id,release_id,exercise_id,code,version)
                    VALUES (@user,@release,@exercise,@code,1) ON CONFLICT DO NOTHING
                    """, ct, ("user", userId), ("release", release.ReleaseId), ("exercise", exerciseId), ("code", code))
                : await Db.Execute(conn, tx, """
                    UPDATE public.code_lab_drafts SET code=@code,version=version+1,updated_at=now()
                    WHERE user_id=@user AND release_id=@release AND exercise_id=@exercise AND version=@version
                    """, ct, ("user", userId), ("release", release.ReleaseId), ("exercise", exerciseId),
                    ("code", code), ("version", expectedVersion.Value));
            if (changed != 1) throw ApiError.Conflict("draft_version_conflict");
            await tx.CommitAsync(ct);
            return Results.Ok(new { code, version = expectedVersion.Value + 1 });
        }).RequireAuthorization();

        lab.MapPost("/runs", async (
            CodeLabRunRequest request, HttpContext ctx, CodeLabQueue queue, CodeLabRunner runner, CancellationToken ct) =>
        {
            if (!runner.Available) throw new ApiError(503, "lab_unavailable", "تشغيل الكود غير متاح حاليًا.");
            if (request.Mode is not ("run" or "assess")) throw ApiError.Invalid();
            var input = request.Input is null ? null : BoundedText(request.Input, 0, InputBytes);
            var submission = new CodeLabSubmission(Input.Id(request.ReleaseId), Input.Id(request.LessonId),
                Input.Id(request.ExerciseId), BoundedText(request.Code, 1, CodeBytes), request.Mode,
                request.Mode == "run" ? input : null);
            var key = Input.Text(request.IdempotencyKey, 1, 128, false);
            var result = await queue.Submit(Input.UserId(ctx), submission, key, ct);
            return Results.Json(result, statusCode: result.Status == "running" ? 202 : 200);
        }).RequireAuthorization();

        lab.MapGet("/runs/{id:guid}", async (Guid id, HttpContext ctx, CodeLabQueue queue, CancellationToken ct) =>
            Results.Ok(await queue.Find(Input.UserId(ctx), id, ct))).RequireAuthorization();

        lab.MapGet("/evidence", async (string releaseId, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Content.Find(conn, releaseId, ct, requirePublished: false);
            if (release.Status is not ("published" or "retired")) throw ApiError.Missing();
            var evidence = await Db.Query(conn, null, """
                SELECT skill_id,exercise_id,awarded_at FROM public.code_lab_evidence
                WHERE user_id=@user AND release_id=@release ORDER BY awarded_at,exercise_id
                """, row => new { skillId = row.GetString(0), exerciseId = row.GetString(1), awardedAt = row.GetDateTime(2) }, ct,
                ("user", Input.UserId(ctx)), ("release", release.ReleaseId));
            return Results.Ok(evidence);
        }).RequireAuthorization();
    }

    private static string BoundedText(string? value, int minimum, int maximumBytes)
    {
        var text = Input.Text(value, minimum, maximumBytes, false);
        if (Encoding.UTF8.GetByteCount(text) > maximumBytes)
            throw ApiError.Invalid("يتجاوز النص الحجم المسموح.");
        return text;
    }
}
