using System.Text.Json;
using System.Text.Json.Nodes;
using Masar.Domain;
using Npgsql;

namespace Masar.Api;

public sealed record PlanRequest(string? ReleaseId, string? GoalId, int? ExpectedCurrentRevision);
public sealed record PreviewRequest(string? ReleaseId, string? GoalId);
public sealed record AttemptRequest(string? ReleaseId, string? LessonId, string? ExerciseId, string? Answer, int HintsUsed, string? IdempotencyKey);
public sealed record DraftRequest(string? Answer, int ExpectedVersion);
public sealed record PlanResult(Guid Id, int Revision, string ReleaseId, string GoalId, string Status, JsonObject Plan);
public sealed record AttemptResult(Guid Id, bool Correct, bool Assisted, string Explanation, bool AlreadyRecorded);
public sealed record LessonProgress(string LessonId, int Solved, int Total, bool Complete);
public sealed record SkillProgress(string SkillId, string Status);
public sealed record ProgressResult(string ReleaseId, string[] CompletedLessonIds, string[] PracticedSkillIds, string[] CorrectExerciseIds,
    int AttemptsCount, int Solved, int Total, LessonProgress[] Lessons, SkillProgress[] Skills);

public static class Learning
{
    public static async Task<ProgressResult> Progress(NpgsqlConnection conn, Release release, Guid userId,
        CancellationToken ct, NpgsqlTransaction? tx = null)
    {
        var attempts = await Db.Query(conn, tx,
            "SELECT exercise_id,correct FROM public.attempts WHERE user_id=@user AND release_id=@release",
            r => (Id: r.GetString(0), Correct: r.GetBoolean(1)), ct, ("user", userId), ("release", release.ReleaseId));
        var successful = attempts.Where(x => x.Correct).Select(x => x.Id).ToHashSet(StringComparer.Ordinal);
        var lessons = Content.Lessons(release.Bundle).ToArray();
        var progress = lessons.Select(l =>
        {
            var exercises = Content.Exercises(l).Select(e => Input.String(e["id"])).ToArray();
            var solved = exercises.Count(successful.Contains);
            return new LessonProgress(Input.String(l["id"]), solved, exercises.Length, exercises.Length > 0 && solved == exercises.Length);
        }).ToArray();
        var completed = progress.Where(l => l.Complete).Select(l => l.LessonId).ToHashSet(StringComparer.Ordinal);
        var practiced = lessons.Where(l => completed.Contains(Input.String(l["id"])))
            .SelectMany(l => (l["skillIds"] as JsonArray ?? []).Select(Input.String)).Distinct(StringComparer.Ordinal).ToArray();
        var correct = lessons.SelectMany(Content.Exercises).Select(e => Input.String(e["id"]))
            .Where(successful.Contains).Distinct(StringComparer.Ordinal).ToArray();
        var skills = (release.Bundle["graph"]?["skills"] as JsonArray ?? []).OfType<JsonObject>()
            .Select(s => Input.String(s["id"]))
            .Select(id => new SkillProgress(id, practiced.Contains(id, StringComparer.Ordinal) ? "practiced" : "unknown")).ToArray();
        return new ProgressResult(release.ReleaseId, completed.ToArray(), practiced, correct, attempts.Count,
            correct.Length, progress.Sum(p => p.Total), progress, skills);
    }

    private static async Task<JsonObject> Plan(NpgsqlConnection conn, Release release, string goalId, Guid? userId,
        CancellationToken ct, NpgsqlTransaction? tx = null)
    {
        var goals = (release.Bundle["graph"]?["goals"] as JsonArray ?? []).OfType<JsonObject>();
        if (!goals.Any(g => Input.String(g["id"]) == goalId)) throw ApiError.Missing();
        IEnumerable<string> skills = [];
        if (userId is Guid learner)
        {
            var practice = await Progress(conn, release, learner, ct, tx);
            var coding = await Db.Query(conn, tx, """
                SELECT DISTINCT skill_id FROM public.code_lab_evidence WHERE user_id=@user AND release_id=@release
                """, row => row.GetString(0), ct, ("user", learner), ("release", release.ReleaseId));
            skills = practice.PracticedSkillIds.Union(coding, StringComparer.Ordinal);
        }
        var plan = CurriculumEngine.Plan(release.Bundle, goalId, skills);
        plan["releaseId"] = release.ReleaseId;
        return plan;
    }

    private static PlanResult ReadPlan(NpgsqlDataReader r) => new(r.GetGuid(0), r.GetInt32(1), r.GetString(2),
        r.GetString(3), r.GetString(4), JsonNode.Parse(r.GetString(5))!.AsObject());

    public static void MapLearning(this WebApplication app)
    {
        app.MapPost("/api/v1/plan-previews", async (PreviewRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Content.Find(conn, Input.Id(request.ReleaseId), ct);
            var plan = await Plan(conn, release, Input.Id(request.GoalId),
                ctx.User.Identity?.IsAuthenticated == true ? Input.UserId(ctx) : null, ct);
            return Results.Ok(plan);
        });

        app.MapPost("/api/v1/learning-plans", async (PlanRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            var userId = Input.UserId(ctx);
            var goalId = Input.Id(request.GoalId);
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            // Serialize revision allocation per real owner, including the first plan.
            await Db.Scalar<Guid>(conn, tx, "SELECT id FROM public.users WHERE id=@id FOR UPDATE", ct, ("id", userId));
            var current = await Db.Scalar<int>(conn, tx,
                "SELECT COALESCE(MAX(revision),0) FROM public.learning_plans WHERE user_id=@user", ct, ("user", userId));
            if (current > 0 && request.ExpectedCurrentRevision != current ||
                current == 0 && request.ExpectedCurrentRevision is not null and not 0)
                throw ApiError.Conflict("plan_revision_conflict");
            var release = await Content.Find(conn, Input.Id(request.ReleaseId), ct, tx);
            var plan = await Plan(conn, release, goalId, userId, ct, tx);
            var id = Guid.NewGuid();
            var status = Input.String(plan["status"]);
            await Db.Execute(conn, tx, """
                INSERT INTO public.learning_plans(id,user_id,revision,release_id,goal_id,status,plan)
                VALUES (@id,@user,@revision,@release,@goal,@status,@plan::jsonb)
                """, ct, ("id", id), ("user", userId), ("revision", current + 1), ("release", release.ReleaseId),
                ("goal", goalId), ("status", status), ("plan", plan.ToJsonString()));
            await tx.CommitAsync(ct);
            return Results.Json(new PlanResult(id, current + 1, release.ReleaseId, goalId, status, plan), statusCode: 201);
        }).RequireAuthorization();

        app.MapGet("/api/v1/me/plan", async (HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var plans = await Db.Query(conn, null, """
                SELECT id,revision,release_id,goal_id,status,plan::text FROM public.learning_plans
                WHERE user_id=@user ORDER BY revision DESC LIMIT 1
                """, ReadPlan, ct, ("user", Input.UserId(ctx)));
            return Results.Ok(plans.FirstOrDefault() ?? throw ApiError.Missing());
        }).RequireAuthorization();
        app.MapGet("/api/v1/me/plan/history", async (HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var revisions = await Db.Query(conn, null, """
                SELECT id,revision,release_id,goal_id,created_at FROM public.learning_plans WHERE user_id=@user ORDER BY revision DESC
                """, r => new { id = r.GetGuid(0), revision = r.GetInt32(1), releaseId = r.GetString(2), goalId = r.GetString(3), createdAt = r.GetDateTime(4) }, ct,
                ("user", Input.UserId(ctx)));
            return Results.Ok(new { revisions });
        }).RequireAuthorization();
        app.MapGet("/api/v1/learning-plans/{id:guid}", async (Guid id, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var plans = await Db.Query(conn, null, """
                SELECT id,revision,release_id,goal_id,status,plan::text FROM public.learning_plans WHERE id=@id AND user_id=@user
                """, ReadPlan, ct, ("id", id), ("user", Input.UserId(ctx)));
            return Results.Ok(plans.FirstOrDefault() ?? throw ApiError.Missing());
        }).RequireAuthorization();

        app.MapPost("/api/v1/practice/attempts", async (AttemptRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            var releaseId = Input.Id(request.ReleaseId);
            var lessonId = Input.Id(request.LessonId);
            var exerciseId = Input.Id(request.ExerciseId);
            var answer = Input.Text(request.Answer, 0, 4096, false);
            var key = Input.Text(request.IdempotencyKey, 1, 128, false);
            if (request.HintsUsed < 0 || request.HintsUsed > 100) throw ApiError.Invalid();
            var userId = Input.UserId(ctx);
            var hash = Input.Hash(JsonSerializer.Serialize(new { releaseId, lessonId, exerciseId, answer, hintsUsed = request.HintsUsed }));
            await using var conn = await db.Open(ct);
            await using var tx = await conn.BeginTransactionAsync(ct);
            // Same per-owner lock makes simultaneous retries deterministic without a duplicate insert race.
            await Db.Scalar<Guid>(conn, tx, "SELECT id FROM public.users WHERE id=@id FOR UPDATE", ct, ("id", userId));
            var existing = await Db.Query(conn, tx, """
                SELECT id,correct,assisted,explanation,payload_hash FROM public.attempts WHERE user_id=@user AND idempotency_key=@key
                """, r => (Result: new AttemptResult(r.GetGuid(0), r.GetBoolean(1), r.GetBoolean(2), r.GetString(3), true), Hash: r.GetString(4)), ct,
                ("user", userId), ("key", key));
            if (existing.Count > 0)
            {
                if (existing[0].Hash != hash) throw ApiError.Conflict("idempotency_conflict");
                await tx.CommitAsync(ct);
                return Results.Ok(existing[0].Result);
            }
            var release = await Content.Find(conn, releaseId, ct, tx);
            var exercise = Content.Exercise(release, exerciseId, lessonId);
            if (request.HintsUsed > (exercise["hints"] as JsonArray ?? []).Count) throw ApiError.Invalid();
            var evaluated = ExerciseEvaluator.Evaluate(exercise, answer, request.HintsUsed);
            var correct = evaluated["correct"]?.GetValue<bool>() ?? false;
            var assisted = evaluated["assisted"]?.GetValue<bool>() ?? request.HintsUsed > 0;
            var explanation = Input.String(evaluated["explanation"]);
            var id = Guid.NewGuid();
            await Db.Execute(conn, tx, """
                INSERT INTO public.attempts(id,user_id,release_id,lesson_id,exercise_id,answer,hints_used,correct,assisted,explanation,idempotency_key,payload_hash)
                VALUES (@id,@user,@release,@lesson,@exercise,@answer,@hints,@correct,@assisted,@explanation,@key,@hash)
                """, ct, ("id", id), ("user", userId), ("release", releaseId), ("lesson", lessonId), ("exercise", exerciseId),
                ("answer", answer), ("hints", request.HintsUsed), ("correct", correct), ("assisted", assisted),
                ("explanation", explanation), ("key", key), ("hash", hash));
            await tx.CommitAsync(ct);
            return Results.Ok(new AttemptResult(id, correct, assisted, explanation, false));
        }).RequireAuthorization();

        app.MapGet("/api/v1/me/progress", async (string releaseId, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var release = await Content.Find(conn, Input.Id(releaseId), ct, requirePublished: false);
            if (release.Status is not ("published" or "retired")) throw ApiError.Missing();
            return Results.Ok(await Progress(conn, release, Input.UserId(ctx), ct));
        }).RequireAuthorization();

        app.MapGet("/api/v1/me/drafts/{releaseId}/{exerciseId}", async (string releaseId, string exerciseId, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            await using var conn = await db.Open(ct);
            var drafts = await Db.Query(conn, null, """
                SELECT answer,version FROM public.drafts WHERE user_id=@user AND release_id=@release AND exercise_id=@exercise
                """, r => new { answer = r.GetString(0), version = r.GetInt32(1) }, ct,
                ("user", Input.UserId(ctx)), ("release", Input.Id(releaseId)), ("exercise", Input.Id(exerciseId)));
            return Results.Ok(drafts.FirstOrDefault() ?? throw ApiError.Missing());
        }).RequireAuthorization();
        app.MapPut("/api/v1/me/drafts/{releaseId}/{exerciseId}", async (string releaseId, string exerciseId, DraftRequest request, HttpContext ctx, Db db, CancellationToken ct) =>
        {
            var answer = Input.Text(request.Answer, 0, 4096, false);
            if (request.ExpectedVersion < 0 || request.ExpectedVersion == int.MaxValue) throw ApiError.Invalid();
            await using var conn = await db.Open(ct);
            var release = await Content.Find(conn, Input.Id(releaseId), ct);
            Content.Exercise(release, Input.Id(exerciseId));
            var userId = Input.UserId(ctx);
            int changed;
            if (request.ExpectedVersion == 0)
                changed = await Db.Execute(conn, null, """
                    INSERT INTO public.drafts(user_id,release_id,exercise_id,answer,version) VALUES (@user,@release,@exercise,@answer,1)
                    ON CONFLICT DO NOTHING
                    """, ct, ("user", userId), ("release", releaseId), ("exercise", exerciseId), ("answer", answer));
            else
                changed = await Db.Execute(conn, null, """
                    UPDATE public.drafts SET answer=@answer,version=version+1,updated_at=now()
                    WHERE user_id=@user AND release_id=@release AND exercise_id=@exercise AND version=@version
                    """, ct, ("user", userId), ("release", releaseId), ("exercise", exerciseId), ("answer", answer), ("version", request.ExpectedVersion));
            if (changed != 1) throw ApiError.Conflict("draft_version_conflict");
            return Results.Ok(new { answer, version = request.ExpectedVersion + 1 });
        }).RequireAuthorization();
    }
}
