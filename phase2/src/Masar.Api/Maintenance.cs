using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Masar.Domain;
using Npgsql;

namespace Masar.Api;

public static class Maintenance
{
    public const string HistoryTable = "public.masar_schema_migrations";
    private const long MigrationLock = 632793228502L;

    public static async Task<int> Run(string[] args, IConfiguration config, bool development)
    {
        try
        {
            if (args.Length == 2 && args[0] == "--verify-curriculum")
            {
                var (_, bundle) = await ReadBundle(args[1]);
                VerifyCurriculum(bundle);
                return 0;
            }
            // Elevated connection is exclusively consumed by explicit local maintenance commands.
            var raw = config.GetConnectionString("Migration");
            if (string.IsNullOrWhiteSpace(raw)) throw new InvalidOperationException("migration_connection_required");
            var options = new NpgsqlConnectionStringBuilder(raw) { IncludeErrorDetail = false, LogParameters = false };
            await using var source = NpgsqlDataSource.Create(options.ConnectionString);
            await using var conn = await source.OpenConnectionAsync();
            if (args.SequenceEqual(["--migrate"])) await Migrate(conn);
            else if (args.Length == 2 && args[0] == "--promote-admin") await Promote(conn, Input.UserName(args[1]));
            else if ((args.Length == 2 || args.Length == 3 && args[2] == "--publish-initial") && args[0] == "--import-bundle")
                await Import(conn, args[1], args.Length == 3);
            else if (args.Length == 3 && args[0] == "--publish-reviewed-curriculum")
            {
                if (!development) throw new MigrationFailure("local_curriculum_only");
                await Import(conn, args[1], false, args[2]);
            }
            else throw new InvalidOperationException("invalid_maintenance_arguments");
            Console.WriteLine("Masar: maintenance completed.");
            return 0;
        }
        catch (Exception ex)
        {
            // Deliberately exclude exception messages: PostgreSQL errors may contain rows or credentials.
            var code = ex is ApiError error ? error.Code : ex is MigrationFailure failure ? failure.Code : "maintenance_failed";
            Console.Error.WriteLine($"Masar: {code} ({ex.GetType().Name}).");
            return 1;
        }
    }

    private sealed class MigrationFailure(string code) : Exception { public string Code { get; } = code; }

    private static async Task Migrate(NpgsqlConnection conn)
    {
        await Db.Scalar<bool>(conn, null, "SELECT pg_advisory_lock(@key) IS NULL", default, ("key", MigrationLock));
        try
        {
            await Db.Execute(conn, null, """
                CREATE TABLE IF NOT EXISTS public.masar_schema_migrations (
                    name text PRIMARY KEY,
                    checksum text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                );
                REVOKE ALL ON public.masar_schema_migrations FROM PUBLIC;
                """);
            var assembly = Assembly.GetExecutingAssembly();
            var names = assembly.GetManifestResourceNames().Where(n => n.StartsWith("Migrations.", StringComparison.Ordinal) && n.EndsWith(".sql", StringComparison.Ordinal))
                .Order(StringComparer.Ordinal).ToArray();
            if (names.Length == 0) throw new MigrationFailure("no_embedded_migrations");
            var applied = await Db.Query(conn, null, "SELECT name,checksum FROM public.masar_schema_migrations ORDER BY name", r => (Name: r.GetString(0), Checksum: r.GetString(1)));
            if (applied.Any(a => !names.Contains(a.Name, StringComparer.Ordinal))) throw new MigrationFailure("unknown_migration");
            foreach (var name in names)
            {
                await using var stream = assembly.GetManifestResourceStream(name)!;
                using var bytes = new MemoryStream();
                await stream.CopyToAsync(bytes);
                var payload = bytes.ToArray();
                var checksum = Convert.ToHexStringLower(SHA256.HashData(payload));
                var prior = applied.FirstOrDefault(a => a.Name == name);
                if (prior.Name is not null)
                {
                    if (prior.Checksum != checksum) throw new MigrationFailure("migration_checksum_mismatch");
                    continue;
                }
                if (applied.Any(a => string.CompareOrdinal(a.Name, name) > 0)) throw new MigrationFailure("migration_order_mismatch");
                await using var tx = await conn.BeginTransactionAsync();
                await Db.Execute(conn, tx, Encoding.UTF8.GetString(payload));
                await Db.Execute(conn, tx, "INSERT INTO public.masar_schema_migrations(name,checksum) VALUES (@name,@checksum)",
                    default, ("name", name), ("checksum", checksum));
                await tx.CommitAsync();
                Console.WriteLine($"Masar: applied {name}.");
            }
        }
        finally { await Db.Scalar<bool>(conn, null, "SELECT pg_advisory_unlock(@key)", default, ("key", MigrationLock)); }
    }

    private static async Task<(string Hash, JsonObject Bundle)> ReadBundle(string path)
    {
        if (!Path.IsPathFullyQualified(path)) throw new MigrationFailure("absolute_bundle_path_required");
        var file = new FileInfo(path);
        if (!file.Exists || file.Length > 1_048_576) throw new MigrationFailure("invalid_bundle_file");
        var payload = await File.ReadAllBytesAsync(path);
        var bundle = JsonNode.Parse(payload.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) ? payload.AsSpan(3) : payload,
            documentOptions: new() { MaxDepth = 64 })?.AsObject()
            ?? throw ApiError.Invalid();
        Content.Validate(bundle);
        return (Convert.ToHexStringLower(SHA256.HashData(payload)), bundle);
    }

    private static void VerifyCurriculum(JsonObject bundle)
    {
        var release = Input.String(bundle["sample"]?["releaseId"]);
        var paths = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["explore"] = LessonRange("core", 12),
            ["python"] = [.. LessonRange("core", 12), .. LessonRange("py", 12)],
            ["web"] = [.. LessonRange("core", 12), .. LessonRange("web", 12)]
        };
        if (release is "phase7-ar-v1" or "phase8-ar-v1")
            paths.Add("data-analysis", [.. paths["python"], .. LessonRange("data", 8)]);
        if (release == "phase8-ar-v1")
        {
            paths.Add("sql", LessonRange("sql", 6));
            paths.Add("web-data", [.. paths["web"], .. LessonRange("web-data", 5)]);
            paths.Add("git-workshop", [.. paths["python"], .. LessonRange("git", 5)]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "git-workshop", ["web.lesson12"]), LessonRange("git", 5));
            VerifyPlan(CurriculumEngine.Plan(bundle, "git-workshop", ["py.automation"]), LessonRange("git", 5));
            var workshopLessons = paths["git-workshop"].ToHashSet(StringComparer.Ordinal);
            VerifyPlan(CurriculumEngine.Plan(bundle, "git-workshop", ["web.lesson11"], allowedLessonIds: workshopLessons),
                paths["git-workshop"]);
        }
        else if (release is not ("phase4-ar-v1" or "phase7-ar-v1"))
            throw new MigrationFailure("unsupported_reviewed_curriculum");

        var exercises = Content.Lessons(bundle).SelectMany(Content.Exercises).ToArray();
        foreach (var exercise in exercises)
        {
            var answers = exercise["acceptedAnswers"]!.AsArray().Select(Input.String).ToArray();
            var wrong = Input.String(exercise["type"]) == "choice"
                ? exercise["options"]!.AsArray().Select(option => Input.String(option?["id"]))
                    .FirstOrDefault(option => !answers.Contains(option, StringComparer.Ordinal))
                : "إجابة تحقق غير صحيحة 481759";
            if (answers.Any(answer => ExerciseEvaluator.Evaluate(exercise, answer, 0)["correct"]?.GetValue<bool>() != true) ||
                wrong is null || ExerciseEvaluator.Evaluate(exercise, wrong, 0)["correct"]?.GetValue<bool>() == true)
                throw new MigrationFailure("curriculum_grade_check_failed");
        }
        foreach (var (goal, expected) in paths)
            VerifyPlan(CurriculumEngine.Plan(bundle, goal), expected);
        Console.WriteLine($"Curriculum checked: {Content.Lessons(bundle).Count()} lessons, {exercises.Length} graded exercises, {paths.Count} complete learning paths.");
    }

    private static void VerifyPlan(JsonObject plan, IEnumerable<string> expected)
    {
        var actual = plan["steps"]!.AsArray().Select(step => Input.String(step?["lessonId"]));
        if (!actual.SequenceEqual(expected, StringComparer.Ordinal) || plan["uncoveredSkillIds"]!.AsArray().Count != 0)
            throw new MigrationFailure("curriculum_plan_check_failed");
    }

    private static string[] LessonRange(string prefix, int count) =>
        Enumerable.Range(1, count).Select(number => FormattableString.Invariant($"{prefix}-{number:00}")).ToArray();

    private static async Task Import(NpgsqlConnection conn, string path, bool publishInitial, string? reviewedHash = null)
    {
        var (hash, bundle) = await ReadBundle(path);
        var releaseId = Input.String(bundle["sample"]?["releaseId"]);
        if (reviewedHash is not null)
        {
            if (releaseId is not ("phase4-ar-v1" or "phase7-ar-v1" or "phase8-ar-v1") || hash != reviewedHash.ToLowerInvariant())
                throw new MigrationFailure("reviewed_curriculum_digest_mismatch");
            VerifyCurriculum(bundle);
        }
        if (publishInitial && (releaseId != "phase1-ar-v1" || Content.Lessons(bundle).Count() != 3))
            throw new MigrationFailure("initial_sample_only");
        await using var tx = await conn.BeginTransactionAsync();
        await Content.LockActiveRelease(conn, tx);
        var existing = await Db.Query(conn, tx, """
            SELECT id,release_id,title,status,version,bundle::text FROM public.content_releases WHERE release_id=@release FOR UPDATE
            """, Content.Read, default, ("release", releaseId));
        var id = existing.Count == 0 ? Guid.NewGuid() : existing[0].Id;
        if (existing.Count > 0)
        {
            var identical = await Db.Scalar<bool>(conn, tx, "SELECT bundle=@bundle::jsonb FROM public.content_releases WHERE id=@id",
                default, ("bundle", bundle.ToJsonString()), ("id", id));
            if (!identical) throw ApiError.Conflict("release_payload_conflict");
        }
        else
        {
            await Db.Execute(conn, tx, """
                INSERT INTO public.content_releases(id,release_id,title,bundle) VALUES (@id,@release,@title,@bundle::jsonb)
                """, default, ("id", id), ("release", releaseId), ("title", Input.String(bundle["sample"]?["title"])), ("bundle", bundle.ToJsonString()));
            await Db.Audit(conn, tx, null, "release.import", id.ToString());
        }
        if (publishInitial && (existing.Count == 0 || existing[0].Status != "published"))
        {
            var hadPublished = await Db.Scalar<bool>(conn, tx, "SELECT EXISTS(SELECT 1 FROM public.content_releases WHERE published_at IS NOT NULL OR status IN ('published','retired'))");
            if (hadPublished || existing.Count > 0 && existing[0].Status != "draft") throw new MigrationFailure("initial_publish_not_allowed");
            await Db.Execute(conn, tx, "UPDATE public.content_releases SET status='published',version=version+1,published_at=now() WHERE id=@id",
                default, ("id", id));
            await Db.Execute(conn, tx, "INSERT INTO public.settings(key,value) VALUES ('active_release_id',@release) ON CONFLICT DO NOTHING", default, ("release", releaseId));
            await Db.Audit(conn, tx, null, "release.publish_initial", id.ToString(), new JsonObject { ["localBootstrap"] = true });
        }
        if (reviewedHash is not null)
            await PublishReviewed(conn, tx, id, releaseId, existing.FirstOrDefault()?.Status ?? "draft", hash);
        await tx.CommitAsync();
    }

    private static async Task PublishReviewed(NpgsqlConnection conn, NpgsqlTransaction tx, Guid id,
        string releaseId, string status, string hash)
    {
        var active = await Db.Scalar<string>(conn, tx, "SELECT value FROM public.settings WHERE key='active_release_id'");
        if (active == releaseId && status == "published") return;
        var requiredPredecessor = releaseId switch
        {
            "phase8-ar-v1" => "phase7-ar-v1",
            "phase7-ar-v1" => "phase4-ar-v1",
            _ => "phase1-ar-v1"
        };
        if (active != requiredPredecessor || status is not ("draft" or "published"))
            throw new MigrationFailure("unexpected_local_release_state");
        if (status == "draft")
        {
            foreach (var next in new[] { "technical_review", "learning_review", "published" })
            {
                await Db.Execute(conn, tx, """
                    UPDATE public.content_releases SET status=@status, version=version+1,
                      published_at=CASE WHEN @status='published' THEN now() ELSE published_at END WHERE id=@id
                    """, default, ("id", id), ("status", next));
                await Db.Audit(conn, tx, null, "release.transition", id.ToString(),
                    new JsonObject { ["from"] = status, ["to"] = next, ["reviewedSha256"] = hash });
                status = next;
            }
        }
        await Db.Execute(conn, tx, """
            UPDATE public.settings SET value=@release WHERE key='active_release_id'
            """, default, ("release", releaseId));
        await Db.Execute(conn, tx, "UPDATE public.content_releases SET version=version+1 WHERE id=@id", default, ("id", id));
        await Db.Audit(conn, tx, null, "release.activate", id.ToString(),
            new JsonObject { ["from"] = active, ["to"] = releaseId, ["reviewedSha256"] = hash });
    }

    private static async Task Promote(NpgsqlConnection conn, string name)
    {
        await using var tx = await conn.BeginTransactionAsync();
        var users = await Db.Query(conn, tx, "SELECT id FROM public.users WHERE normalized_user_name=@name FOR UPDATE", r => r.GetGuid(0), default, ("name", name));
        if (users.Count != 1) throw new MigrationFailure("existing_user_required");
        var id = users[0];
        await Db.Execute(conn, tx, "UPDATE public.users SET role='Admin' WHERE id=@id", default, ("id", id));
        await Db.Audit(conn, tx, null, "account.promote_admin", id.ToString(), new JsonObject { ["localBootstrap"] = true });
        await tx.CommitAsync();
    }
}
