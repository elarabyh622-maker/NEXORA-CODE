using System.Text.Json;
using System.Text.Json.Serialization;
using Npgsql;

namespace Masar.Api;

internal sealed record CodeLabRunResult(Guid Id, string Status, string Verdict, string Stdout, string Stderr,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? PassedCases,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? TotalCases, bool AlreadyRecorded);

internal sealed record CodeLabSubmission(
    string ReleaseId, string LessonId, string ExerciseId, string Code, string Mode, string? Input);

internal sealed record CodeLabJob(Guid Id, string Language, string Code, string Stdin, CodeLabTest[] TestCases);

internal sealed class CodeLabQueue(Db db, CommercialOptions commercial)
{
    private const long QueueLock = 632793228504L;
    internal const int WorkerSlots = 2;
    private const int QueueCapacity = 32;
    private const int PerOwnerCapacity = 2;
    private const int PerOwnerRunsPerMinute = 20;
    private const string RunFields = """
        id, CASE WHEN status IN ('queued', 'running') THEN
            CASE WHEN expires_at <= now() THEN 'infrastructure_error' ELSE 'running' END
            ELSE status END, verdict, stdout, stderr, passed_cases, total_cases
        """;

    public async Task<CodeLabRunResult> Submit(Guid userId, CodeLabSubmission submission, string key, CancellationToken ct)
    {
        var hash = Input.Hash(JsonSerializer.Serialize(submission));
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await LockQueue(conn, tx, ct);
        var prior = await Db.Query(conn, tx, $"""
            SELECT {RunFields}, payload_hash FROM public.code_lab_runs WHERE user_id=@user AND idempotency_key=@key
            """, row => (Result: ReadRun(row) with { AlreadyRecorded = true }, Hash: row.GetString(7)), ct,
            ("user", userId), ("key", key));
        if (prior.Count > 0)
        {
            if (prior[0].Hash != hash) throw ApiError.Conflict("idempotency_conflict");
            return prior[0].Result;
        }

        var release = await RequirePublished(conn, tx, submission.ReleaseId, ct);
        var definition = CodeLabCatalog.ForRelease(release).SingleOrDefault(candidate =>
            candidate.LessonId == submission.LessonId && candidate.Exercise.Id == submission.ExerciseId)
            ?? throw ApiError.Missing();
        var counts = (await Db.Query(conn, tx, """
            SELECT count(*) FILTER (WHERE status IN ('queued', 'running') AND expires_at > now()),
                   count(*) FILTER (WHERE user_id=@user AND status IN ('queued', 'running') AND expires_at > now()),
                   count(*) FILTER (WHERE user_id=@user AND created_at > now() - interval '1 minute')
            FROM public.code_lab_runs
            WHERE (status IN ('queued', 'running') AND expires_at > now())
               OR (user_id=@user AND created_at > now() - interval '1 minute')
            """, row => (Active: row.GetInt64(0), OwnerActive: row.GetInt64(1), OwnerRecent: row.GetInt64(2)), ct,
            ("user", userId))).Single();
        if (counts.Active >= QueueCapacity || counts.OwnerActive >= PerOwnerCapacity ||
            counts.OwnerRecent >= PerOwnerRunsPerMinute)
        {
            throw new ApiError(429, "lab_busy", "المعمل مشغول. انتظر قليلًا ثم حاول مرة أخرى.");
        }

        var id = Guid.NewGuid();
        var assess = submission.Mode == "assess";
        var tests = assess ? definition.TestCases : [];
        if (commercial.Required)
        {
            // Reserve the worst-case execution count while holding the existing queue lock.
            var units = await Db.Scalar<long>(conn, tx, """
                SELECT COALESCE(SUM(GREATEST(1, jsonb_array_length(test_cases))), 0)
                FROM public.code_lab_runs WHERE created_at > now() - interval '24 hours'
                """, ct);
            if (units + Math.Max(1, tests.Length) > commercial.DailyExecutionLimit)
                throw new ApiError(429, "lab_daily_limit", "بلغ المختبر حد التشغيل في آخر 24 ساعة. يمكنك حفظ عملك والمحاولة لاحقًا.");
        }
        var stdin = assess ? "" : submission.Input ?? definition.Exercise.SampleInput;
        await Db.Execute(conn, tx, """
            INSERT INTO public.code_lab_runs
                (id,user_id,release_id,lesson_id,exercise_id,exercise_version,skill_id,language,code,stdin,mode,
                 test_cases,idempotency_key,payload_hash)
            VALUES (@id,@user,@release,@lesson,@exercise,@version,@skill,@language,@code,@stdin,@mode,@tests::jsonb,@key,@hash)
            """, ct, ("id", id), ("user", userId), ("release", release.ReleaseId), ("lesson", submission.LessonId),
            ("exercise", submission.ExerciseId), ("version", definition.Version), ("skill", definition.Exercise.SkillId),
            ("language", definition.Exercise.Language), ("code", submission.Code), ("stdin", stdin),
            ("mode", submission.Mode), ("tests", JsonSerializer.Serialize(tests)), ("key", key), ("hash", hash));
        await tx.CommitAsync(ct);
        return new CodeLabRunResult(id, "running", "not_evaluated", "", "", null, null, false);
    }

    public async Task<CodeLabRunResult> Find(Guid userId, Guid id, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        var results = await Db.Query(conn, null, $"""
            SELECT {RunFields} FROM public.code_lab_runs WHERE id=@id AND user_id=@user
            """, ReadRun, ct, ("id", id), ("user", userId));
        return results.FirstOrDefault() ?? throw ApiError.Missing();
    }

    public async Task<CodeLabJob?> Claim(CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await LockQueue(conn, tx, ct);
        // A lost worker leaves a bounded lease. Its job terminates without reusing a partial assessment.
        await Db.Execute(conn, tx, """
            UPDATE public.code_lab_runs SET status='infrastructure_error', completed_at=now()
            WHERE status IN ('queued', 'running') AND expires_at <= now()
            """, ct);
        var jobs = await Db.Query(conn, tx, """
            WITH next_job AS (
                SELECT id FROM public.code_lab_runs WHERE status='queued'
                  AND (SELECT count(*) FROM public.code_lab_runs WHERE status='running') < @slots
                ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE public.code_lab_runs AS runs SET status='running', expires_at=now() + interval '120 seconds'
            FROM next_job WHERE runs.id=next_job.id
            RETURNING runs.id,language,code,stdin,test_cases::text
            """, row => new CodeLabJob(row.GetGuid(0), row.GetString(1), row.GetString(2), row.GetString(3),
            JsonSerializer.Deserialize<CodeLabTest[]>(row.GetString(4))!), ct, ("slots", WorkerSlots));
        await tx.CommitAsync(ct);
        return jobs.FirstOrDefault();
    }

    public async Task Finish(CodeLabRunResult result, CancellationToken ct)
    {
        await using var conn = await db.Open(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        var updated = await Db.Execute(conn, tx, """
            UPDATE public.code_lab_runs
            SET status=@status, verdict=@verdict, stdout=@stdout, stderr=@stderr,
                passed_cases=@passed::integer, total_cases=@total::integer, completed_at=now()
            WHERE id=@id AND status='running' AND expires_at > now()
            """, ct, ("id", result.Id), ("status", result.Status), ("verdict", result.Verdict), ("stdout", result.Stdout),
            ("stderr", result.Stderr), ("passed", result.PassedCases), ("total", result.TotalCases));
        if (updated == 1 && result.Verdict == "passed")
        {
            await Db.Execute(conn, tx, """
                INSERT INTO public.code_lab_evidence (user_id,release_id,lesson_id,exercise_id,exercise_version,skill_id,run_id)
                SELECT user_id,release_id,lesson_id,exercise_id,exercise_version,skill_id,id
                FROM public.code_lab_runs WHERE id=@id AND status='completed' AND verdict='passed'
                ON CONFLICT (user_id,release_id,exercise_id) DO NOTHING
                """, ct, ("id", result.Id));
        }
        await tx.CommitAsync(ct);
    }

    internal static async Task<Release> RequirePublished(
        NpgsqlConnection conn, NpgsqlTransaction tx, string releaseId, CancellationToken ct)
    {
        var versions = await Db.Query(conn, tx, """
            SELECT id,release_id,title,status,version,bundle::text FROM public.content_releases
            WHERE release_id=@release AND status='published' FOR SHARE
            """, Content.Read, ct, ("release", releaseId));
        return versions.FirstOrDefault() ?? throw ApiError.Missing();
    }

    private static Task LockQueue(NpgsqlConnection conn, NpgsqlTransaction tx, CancellationToken ct) =>
        Db.Scalar<bool>(conn, tx, "SELECT pg_advisory_xact_lock(@key) IS NULL", ct, ("key", QueueLock));

    private static CodeLabRunResult ReadRun(NpgsqlDataReader row) => new(
        row.GetGuid(0), row.GetString(1), row.GetString(2), row.GetString(3), row.GetString(4),
        row.IsDBNull(5) ? null : row.GetInt32(5), row.IsDBNull(6) ? null : row.GetInt32(6), false);
}
