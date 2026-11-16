using System.Text.Json.Nodes;

namespace Masar.Api;

internal static class CurriculumPresentation
{
    public static void Validate(JsonObject bundle)
    {
        var sample = bundle["sample"]!.AsObject();
        var ids = Content.Lessons(bundle).Select(lesson => Input.String(lesson["id"])).ToHashSet(StringComparer.Ordinal);
        if (sample.ContainsKey("tracks"))
        {
            if (sample["tracks"] is not JsonArray { Count: >= 1 and <= 32 } tracks) throw Invalid();
            var covered = new HashSet<string>(StringComparer.Ordinal);
            var trackIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (var node in tracks)
            {
                if (node is not JsonObject track || !trackIds.Add(Text(track["id"], 100)) ||
                    track["lessonIds"] is not JsonArray { Count: >= 1 } trackLessons)
                    throw Invalid();
                Text(track["title"], 300);
                foreach (var lesson in trackLessons)
                {
                    var id = Text(lesson, 100);
                    if (!ids.Contains(id) || !covered.Add(id)) throw Invalid();
                }
            }
            if (!covered.SetEquals(ids)) throw Invalid();
        }
        if (!sample.ContainsKey("projects")) return;
        if (sample["projects"] is not JsonArray { Count: <= 32 } projects) throw Invalid();
        var projectIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in projects)
        {
            if (node is not JsonObject project || !projectIds.Add(Text(project["id"], 100)) ||
                !ids.Contains(Text(project["lessonId"], 100)) || project["criteria"] is not JsonArray { Count: >= 1 and <= 16 } criteria)
                throw Invalid();
            Text(project["title"], 300);
            Text(project["summary"], 2000);
            foreach (var criterion in criteria) Text(criterion, 1000);
            if (project.ContainsKey("download") && Text(project["download"], 100) != "/projects/web-starter-v1.zip")
                throw Invalid();
        }
    }

    private static string Text(JsonNode? node, int max)
    {
        if (node is not JsonValue value || !value.TryGetValue<string>(out var text) || string.IsNullOrWhiteSpace(text) ||
            text.Length > max || text.Contains('\0'))
            throw Invalid();
        return text;
    }

    private static ApiError Invalid() => new(400, "invalid_curriculum_presentation", "بيانات وحدات المنهج أو مشروعاته غير صالحة.");
}
