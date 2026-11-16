using System.Text.Json.Nodes;

namespace Masar.Domain.Tests;

internal static class Fixtures
{
    internal static JsonObject Phase1() => new()
    {
        ["sample"] = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "sample.json"))),
        ["graph"] = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "graph.json")))
    };

    internal static JsonObject Exercise(string answer = "9", string type = "text") => new()
    {
        ["id"] = "exercise", ["type"] = type, ["prompt"] = "ما الإجابة؟", ["explanation"] = "شرح موثوق من المؤلف.",
        ["acceptedAnswers"] = new JsonArray(answer), ["hints"] = new JsonArray("تلميح"), ["independent"] = true,
        ["options"] = type == "choice" ? new JsonArray(new JsonObject { ["id"] = "yes", ["text"] = "نعم" }, new JsonObject { ["id"] = "no", ["text"] = "لا" }) : new JsonArray()
    };

    internal static JsonObject Bundle(params string[] ids)
    {
        var skills = new JsonArray();
        var lessons = new JsonArray();
        var sampleLessons = new JsonArray();
        foreach (var id in ids)
        {
            skills.Add(new JsonObject { ["id"] = id, ["title"] = id, ["description"] = "شرح مهارة", ["required"] = null, ["recommended"] = new JsonArray() });
            lessons.Add(new JsonObject { ["id"] = "lesson-" + id, ["title"] = "درس " + id, ["why"] = "سبب تعلم المهارة", ["skillIds"] = new JsonArray(id) });
            var exercise = Exercise();
            exercise["id"] = "exercise-" + id;
            sampleLessons.Add(new JsonObject
            {
                ["id"] = "lesson-" + id,
                ["title"] = "درس " + id,
                ["summary"] = "مقدمة عن المهارة",
                ["why"] = "سبب تعلم المهارة",
                ["minutes"] = "5–10",
                ["takeaway"] = "الفكرة الرئيسية للدرس",
                ["skillIds"] = new JsonArray(id),
                ["objectives"] = new JsonArray("أشرح الفكرة الرئيسية"),
                ["sections"] = new JsonArray(new JsonObject { ["heading"] = "شرح الفكرة", ["body"] = "تفاصيل الفكرة" }),
                ["examples"] = new JsonArray(new JsonObject
                {
                    ["title"] = "مثال توضيحي", ["language"] = "text", ["code"] = "المدخل: 9", ["explanation"] = "شرح المثال"
                }),
                ["exercises"] = new JsonArray(exercise)
            });
        }
        return new JsonObject
        {
            ["sample"] = new JsonObject
            {
                ["schemaVersion"] = 1,
                ["releaseId"] = "general-v2",
                ["title"] = "منهج عام",
                ["intro"] = "تعريف بالمنهج",
                ["lessons"] = sampleLessons,
                ["glossary"] = new JsonArray(new JsonObject { ["term"] = "مهارة", ["technical"] = "Skill", ["definition"] = "قدرة يمكن ممارستها" })
            },
            ["graph"] = new JsonObject
            {
                ["schemaVersion"] = 1, ["releaseId"] = "general-v2", ["skills"] = skills, ["lessons"] = lessons,
                ["goals"] = new JsonArray(new JsonObject { ["id"] = "goal", ["title"] = "هدفي", ["description"] = "شرح الهدف", ["status"] = "sample", ["skillIds"] = new JsonArray(ids.Last()) })
            }
        };
    }

    internal static JsonObject Skill(JsonObject bundle, string id) => ((JsonArray)bundle["graph"]!["skills"]!).OfType<JsonObject>().Single(item => item["id"]!.GetValue<string>() == id);
    internal static JsonObject Ref(string id) => new() { ["skill"] = id };
    internal static JsonObject All(params JsonNode[] children) => new() { ["allOf"] = new JsonArray(children) };
    internal static JsonObject Any(params JsonNode[] children) => new() { ["anyOf"] = new JsonArray(children) };
    internal static string[] Strings(JsonNode? node) => ((JsonArray)node!).Select(item => item!.GetValue<string>()).ToArray();
    internal static string[] LessonIds(JsonObject plan) => ((JsonArray)plan["steps"]!).Select(step => step!["lessonId"]!.GetValue<string>()).ToArray();
}
