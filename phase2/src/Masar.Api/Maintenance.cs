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
    private const int MaxBundleFileBytes = 2 * 1024 * 1024;

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
        if (!File.Exists(path)) throw new MigrationFailure("invalid_bundle_file");
        await using var file = File.OpenRead(path);
        var length = file.Length;
        if (length > MaxBundleFileBytes) throw new MigrationFailure("invalid_bundle_file");
        var payload = new byte[(int)length];
        await file.ReadExactlyAsync(payload);
        if (file.ReadByte() != -1) throw new MigrationFailure("invalid_bundle_file");
        var bundle = JsonNode.Parse(payload.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) ? payload.AsSpan(3) : payload,
            documentOptions: new() { MaxDepth = 64 })?.AsObject()
            ?? throw ApiError.Invalid();
        Content.Validate(bundle);
        return (Convert.ToHexStringLower(SHA256.HashData(payload)), bundle);
    }

    private static void VerifyCurriculum(JsonObject bundle)
    {
        var phase = ReviewedPhase(Input.String(bundle["sample"]?["releaseId"]));
        if (phase == 0) throw new MigrationFailure("unsupported_reviewed_curriculum");
        var paths = new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["explore"] = LessonRange("core", 12),
            ["python"] = [.. LessonRange("core", 12), .. LessonRange("py", 12)],
            ["web"] = [.. LessonRange("core", 12), .. LessonRange("web", 12)]
        };
        if (phase >= 7)
            paths.Add("data-analysis", [.. paths["python"], .. LessonRange("data", 8)]);
        if (phase >= 8)
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
        if (phase >= 9)
        {
            paths.Add("python-projects", [.. paths["python"], .. LessonRange("pyproj", 3)]);
            paths.Add("sql-write", [.. paths["sql"], .. LessonRange("sql-write", 4)]);
            paths.Add("backend", [.. paths["python-projects"], .. LessonRange("backend", 3),
                .. paths["sql-write"], .. LessonRange("backend", 7).Skip(3)]);
            paths.Add("fullstack", [.. paths["backend"], .. LessonRange("web", 12),
                .. LessonRange("web-data", 5), .. LessonRange("fullstack", 2)]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "backend", ["pyproj.types", "sqlwrite.transactions"]),
                LessonRange("backend", 7));
            VerifyPlan(CurriculumEngine.Plan(bundle, "fullstack", ["backend.tests", "web-data.catalogue"]),
                LessonRange("fullstack", 2));
        }

        if (phase >= 10)
        {
            paths.Add("javascript-projects", [.. paths["web-data"], .. LessonRange("jsproj", 4)]);
            paths.Add("react", [.. paths["javascript-projects"], .. LessonRange("react", 7)]);
            paths.Add("typescript-react", [.. paths["react"], .. LessonRange("tsreact", 3)]);
            paths.Add("react-fullstack", [.. paths["react"],
                .. paths["backend"].Where(lesson => !paths["react"].Contains(lesson, StringComparer.Ordinal))]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "react", ["jsproj.immutable"]), LessonRange("react", 7));
            VerifyPlan(CurriculumEngine.Plan(bundle, "typescript-react", ["react.project"]), LessonRange("tsreact", 3));
            VerifyPlan(CurriculumEngine.Plan(bundle, "react-fullstack", ["react.project", "backend.tests"]), []);
        }

        if (phase >= 11)
        {
            paths.Add("algorithms", [.. paths["explore"], .. LessonRange("alg", 8)]);
            paths.Add("oop", [.. paths["python-projects"], .. LessonRange("oop", 6)]);
            paths.Add("problem-solving", [.. paths["algorithms"], .. LessonRange("solve", 6)]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "algorithms", ["core.debugging"]), LessonRange("alg", 8));
            VerifyPlan(CurriculumEngine.Plan(bundle, "oop", ["pyproj.types"]), LessonRange("oop", 6));
            VerifyPlan(CurriculumEngine.Plan(bundle, "problem-solving", ["alg.recursion"]), LessonRange("solve", 6));
        }

        if (phase >= 12)
        {
            string[] modules = [.. LessonRange("pd", 5), .. LessonRange("stat", 5),
                .. LessonRange("ana-sql", 5), "applied-01"];
            paths.Add("applied-data", [.. paths["data-analysis"], .. modules.Take(10),
                .. paths["sql"], .. modules.Skip(10)]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "applied-data", ["data.project", "sql.report"]), modules);
            VerifyPlan(CurriculumEngine.Plan(bundle, "applied-data", ["pd.clean", "stat.interpret", "anasql.audit"]),
                ["applied-01"]);
        }

        if (phase >= 13)
        {
            string[] modules = [.. LessonRange("mlprep", 4), .. LessonRange("mlmod", 4),
                .. LessonRange("mleval", 4), "mlproject-01"];
            paths.Add("machine-learning", [.. paths["data-analysis"], .. LessonRange("pd", 5),
                .. LessonRange("stat", 5), .. modules]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "machine-learning", ["pd.clean", "stat.interpret"]), modules);
            VerifyPlan(CurriculumEngine.Plan(bundle, "machine-learning", ["mleval.report"]), ["mlproject-01"]);
        }

        if (phase >= 14)
        {
            var basics = LessonRange("csharp-basics", 4);
            var programming = LessonRange("csharp-programming", 4);
            var application = LessonRange("csharp-application", 4);
            string[] coreSkills = ["core.workspace", "core.input-output", "core.algorithm", "core.variables",
                "core.types", "core.expressions", "core.conditions", "core.loops", "core.collections",
                "core.functions", "core.testing"];
            paths.Add("csharp", ["core-01", basics[0], "core-02", "core-03", "core-04", "core-05",
                basics[1], "core-06", basics[2], "core-07", basics[3], "core-08", programming[0],
                "core-09", "core-10", .. programming.Skip(1), .. application.Take(3), "core-11",
                application[3], "csproject-01"]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "csharp", coreSkills),
                [.. basics, .. programming, .. application, "csproject-01"]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "csharp", ["csharp.testing"]), ["csproject-01"]);
        }

        if (phase >= 15)
        {
            string[] modules = [.. LessonRange("codex-local", 4), .. LessonRange("codex-flow", 4), "codex-project-01"];
            paths.Add("codex-automation", ["core-01", .. modules]);
            VerifyPlan(CurriculumEngine.Plan(bundle, "codex-automation", ["core.workspace"]), modules);
        }

        var lessons = Content.Lessons(bundle).ToArray();
        var exercises = lessons.SelectMany(Content.Exercises).ToArray();
        if (phase >= 16)
        {
            (int Lessons, int Exercises, int Goals, string Failure) expected = phase switch
            {
                16 => (173, 493, 23, "curriculum_cpp_inventory_check_failed"),
                17 => (185, 529, 24, "curriculum_java_inventory_check_failed"),
                _ => (197, 565, 25, "curriculum_go_inventory_check_failed")
            };
            if (lessons.Length != expected.Lessons || exercises.Length != expected.Exercises ||
                bundle["graph"]?["goals"]?.AsArray().Count != expected.Goals ||
                bundle["codeLab"] is not JsonArray { Count: 48 } labs)
                throw new MigrationFailure(expected.Failure);

            AddLocalLanguageTrack("cpp", "curriculum_cpp_inventory_check_failed");
            if (phase >= 17)
            {
                const string failure = "curriculum_java_inventory_check_failed";
                AddLocalLanguageTrack("java", failure);
                VerifyLocalProject("java-project-01", "/projects/java-library-starter-v1.zip", failure);
            }
            if (phase >= 18)
            {
                const string failure = "curriculum_go_inventory_check_failed";
                AddLocalLanguageTrack("go", failure);
                VerifyLocalProject("go-project-01", "/projects/go-tasks-api-starter-v1.zip", failure);
                VerifyPlan(CurriculumEngine.Plan(bundle, "go", ["go.project"]), []);
            }

            void AddLocalLanguageTrack(string goal, string failure)
            {
                string[] modules = [.. LessonRange($"{goal}-basics", 4), .. LessonRange($"{goal}-code", 4),
                    .. LessonRange($"{goal}-data", 3), $"{goal}-project-01"];
                paths.Add(goal, ["core-01", .. modules]);
                VerifyPlan(CurriculumEngine.Plan(bundle, goal, ["core.workspace"]), modules);

                var moduleIds = modules.ToHashSet(StringComparer.Ordinal);
                if (labs.Any(lab => moduleIds.Contains(Input.String(lab?["lessonId"]))) ||
                    lessons.Where(lesson => moduleIds.Contains(Input.String(lesson["id"])))
                        .Any(lesson => Content.Exercises(lesson).Count() != 3))
                    throw new MigrationFailure(failure);
            }

            void VerifyLocalProject(string lessonId, string download, string failure)
            {
                if (bundle["sample"]?["projects"] is not JsonArray projects ||
                    !projects.Any(project => Input.String(project?["lessonId"]) == lessonId &&
                        Input.String(project?["download"]) == download))
                    throw new MigrationFailure(failure);
            }
        }

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
        Console.WriteLine($"Curriculum checked: {lessons.Length} lessons, {exercises.Length} graded exercises, {paths.Count} complete learning paths.");
    }

    private static void VerifyPlan(JsonObject plan, IEnumerable<string> expected)
    {
        var actual = plan["steps"]!.AsArray().Select(step => Input.String(step?["lessonId"]));
        if (!actual.SequenceEqual(expected, StringComparer.Ordinal) || plan["uncoveredSkillIds"]!.AsArray().Count != 0)
            throw new MigrationFailure("curriculum_plan_check_failed");
    }

    private static string[] LessonRange(string prefix, int count) =>
        Enumerable.Range(1, count).Select(number => FormattableString.Invariant($"{prefix}-{number:00}")).ToArray();

    private static int ReviewedPhase(string releaseId) => releaseId switch
    {
        "phase4-ar-v1" => 4,
        "phase7-ar-v1" => 7,
        "phase8-ar-v1" => 8,
        "phase9-ar-v1" => 9,
        "phase10-ar-v1" => 10,
        "phase11-ar-v1" => 11,
        "phase12-ar-v1" => 12,
        "phase13-ar-v1" => 13,
        "phase14-ar-v1" => 14,
        "phase15-ar-v1" => 15,
        "phase16-ar-v1" => 16,
        "phase17-ar-v1" => 17,
        "phase18-ar-v1" => 18,
        _ => 0
    };

    private static async Task Import(NpgsqlConnection conn, string path, bool publishInitial, string? reviewedHash = null)
    {
        var (hash, bundle) = await ReadBundle(path);
        var releaseId = Input.String(bundle["sample"]?["releaseId"]);
        if (reviewedHash is not null)
        {
            if (ReviewedPhase(releaseId) == 0 || hash != reviewedHash.ToLowerInvariant())
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
            "phase18-ar-v1" => "phase17-ar-v1",
            "phase17-ar-v1" => "phase16-ar-v1",
            "phase16-ar-v1" => "phase15-ar-v1",
            "phase15-ar-v1" => "phase14-ar-v1",
            "phase14-ar-v1" => "phase13-ar-v1",
            "phase13-ar-v1" => "phase12-ar-v1",
            "phase12-ar-v1" => "phase11-ar-v1",
            "phase11-ar-v1" => "phase10-ar-v1",
            "phase10-ar-v1" => "phase9-ar-v1",
            "phase9-ar-v1" => "phase8-ar-v1",
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
