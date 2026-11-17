using System.Text.Json.Nodes;
using Masar.Domain;

namespace Masar.Api;

internal static class CommercialLearning
{
    public static void RequireGoal(CommercialEntitlements access, string goalId)
    {
        if (!access.FullAccess && !access.GoalIds.Contains(goalId)) throw Denied();
    }

    public static void RequireLesson(CommercialEntitlements access, Release release, string lessonId)
    {
        if (!access.FullAccess && !AllowedLessons(access, release).Contains(lessonId)) throw Denied();
    }

    public static HashSet<string> AllowedLessons(CommercialEntitlements access, Release release)
    {
        var published = Content.Lessons(release.Bundle).Select(lesson => Input.String(lesson["id"]))
            .ToHashSet(StringComparer.Ordinal);
        if (access.FullAccess) return published;
        var allowed = access.LessonIds.Where(published.Contains).ToHashSet(StringComparer.Ordinal);
        foreach (var goal in (release.Bundle["graph"]?["goals"] as JsonArray ?? []).OfType<JsonObject>())
        {
            var goalId = Input.String(goal["id"]);
            if (!access.GoalIds.Contains(goalId)) continue;
            var plan = CurriculumEngine.Plan(release.Bundle, goalId, []);
            foreach (var step in (plan["steps"] as JsonArray ?? []).OfType<JsonObject>())
            {
                var lessonId = Input.String(step["lessonId"]);
                if (published.Contains(lessonId)) allowed.Add(lessonId);
            }
        }
        return allowed;
    }

    public static JsonObject ProjectContent(JsonObject clean, CommercialEntitlements access, Release release)
    {
        if (access.FullAccess) return clean;
        var allowed = AllowedLessons(access, release);
        var sample = clean["sample"]!.AsObject();
        Keep(sample, "lessons", item => allowed.Contains(Input.String(item["id"])));
        Keep(sample, "projects", item => allowed.Contains(Input.String(item["lessonId"])));
        Keep(sample, "tracks", item => access.GoalIds.Contains(Input.String(item["id"])));
        var graph = clean["graph"]!.AsObject();
        Keep(graph, "lessons", item => allowed.Contains(Input.String(item["id"])));
        Keep(graph, "goals", item => access.GoalIds.Contains(Input.String(item["id"])));
        return clean;
    }

    private static void Keep(JsonObject node, string property, Func<JsonObject, bool> match)
    {
        if (node[property] is not JsonArray items) return;
        for (var index = items.Count - 1; index >= 0; index--)
            if (items[index] is not JsonObject item || !match(item)) items.RemoveAt(index);
    }

    private static ApiError Denied() => new(403, "access_required", "هذا المسار أو الدرس غير مفعّل لحسابك.");
}
