using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text;

namespace Masar.Api;

internal sealed record CodeLabExercise(
    string Id, string Language, string Title, string Prompt, string StarterCode,
    string SampleInput, string SampleOutput, string SkillId);

internal sealed record CodeLabTest(string Input, string ExpectedOutput);

internal sealed record CodeLabDefinition(
    string ReleaseId, string LessonId, CodeLabExercise Exercise, CodeLabTest[] HiddenTests)
{
    public string Version => Input.Hash(JsonSerializer.Serialize(new { ReleaseId, LessonId, Exercise, HiddenTests }));

    public CodeLabTest[] TestCases => [new(Exercise.SampleInput, Exercise.SampleOutput), .. HiddenTests];
}

internal static class CodeLabCatalog
{
    private static readonly CodeLabDefinition[] SampleExercises =
    [
        new("phase1-ar-v1", "what-is-a-program",
            new("python-greeting", "python", "رسالة ترحيب بالاسم",
                "اقرأ اسمًا من سطر الإدخال. اطبع كلمة «أهلًا» ثم مسافة واحدة ثم الاسم في سطر واحد.",
                "name = input()\n# أضف كلمة الترحيب إلى الاسم عند الطباعة.\nprint(name)\n",
                "ليلى\n", "أهلًا ليلى\n", "concept.input-output"),
            [new("Maya\n", "أهلًا Maya\n"), new("عبد الرحمن\n", "أهلًا عبد الرحمن\n")]),
        new("phase1-ar-v1", "step-by-step",
            new("javascript-price", "javascript", "احسب سعر عبوتين",
                "اقرأ سعر القطعة كعدد صحيح. أضف ٣ لتكلفة تغليف القطعة، ثم اضرب الناتج في ٢ لسعر قطعتين مغلّفتين. اطبع السعر النهائي فقط.",
                "const price = Number(require('node:fs').readFileSync(0, 'utf8').trim());\n// احسب سعر القطعتين بعد إضافة التغليف لكل قطعة.\nconsole.log(price);\n",
                "2\n", "10\n", "concept.sequence"),
            [new("0\n", "6\n"), new("11\n", "28\n")])
    ];

    public static IEnumerable<CodeLabDefinition> ForRelease(Release release)
    {
        var graphSkills = (release.Bundle["graph"]?["skills"] as JsonArray ?? [])
            .OfType<JsonObject>().Select(skill => Input.String(skill["id"])).ToHashSet(StringComparer.Ordinal);
        var lessons = Content.Lessons(release.Bundle).ToDictionary(lesson => Input.String(lesson["id"]), StringComparer.Ordinal);
        var publishedExercises = release.Bundle["codeLab"] is JsonArray entries
            ? entries.OfType<JsonObject>().Select(entry => ReadDefinition(release.ReleaseId, entry))
            : [];
        return SampleExercises.Concat(publishedExercises).Where(definition => definition.ReleaseId == release.ReleaseId &&
            graphSkills.Contains(definition.Exercise.SkillId) &&
            lessons.TryGetValue(definition.LessonId, out var lesson) &&
            (lesson["skillIds"] as JsonArray ?? []).Any(skill => Input.String(skill) == definition.Exercise.SkillId));
    }

    public static void Validate(JsonObject bundle)
    {
        if (!bundle.ContainsKey("codeLab")) return;
        var releaseId = Input.String(bundle["sample"]?["releaseId"]);
        if (releaseId == "phase1-ar-v1" || bundle["codeLab"] is not JsonArray { Count: <= 128 } entries)
            throw InvalidLab();
        var lessons = Content.Lessons(bundle).ToDictionary(lesson => Input.String(lesson["id"]), StringComparer.Ordinal);
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in entries)
        {
            if (entry is not JsonObject obj) throw InvalidLab();
            var definition = ReadDefinition(releaseId, obj);
            if (!ids.Add(definition.Exercise.Id) || !lessons.TryGetValue(definition.LessonId, out var lesson) ||
                !(lesson["skillIds"] as JsonArray ?? []).Any(skill => Input.String(skill) == definition.Exercise.SkillId))
                throw InvalidLab();
        }
    }

    private static CodeLabDefinition ReadDefinition(string releaseId, JsonObject entry)
    {
        var language = Input.String(entry["language"]);
        if (language is not ("python" or "javascript") || entry["hiddenTests"] is not JsonArray { Count: >= 1 and <= 3 } cases ||
            entry.ContainsKey("solution"))
            throw InvalidLab();
        var testCases = cases.Select(test => test is JsonObject item
            ? new CodeLabTest(ReadText(item, "input", 0, 4096), ReadText(item, "expectedOutput", 0, 4096))
            : throw InvalidLab()).ToArray();
        var exercise = new CodeLabExercise(ReadText(entry, "id", 1, 100), language,
            ReadText(entry, "title", 1, 600), ReadText(entry, "prompt", 1, 4000),
            ReadText(entry, "starterCode", 1, 16_384), ReadText(entry, "sampleInput", 0, 4096),
            ReadText(entry, "sampleOutput", 0, 4096), ReadText(entry, "skillId", 1, 100));
        var definition = new CodeLabDefinition(releaseId, ReadText(entry, "lessonId", 1, 100), exercise, testCases);
        if (Encoding.UTF8.GetByteCount(JsonSerializer.Serialize(definition.TestCases)) > 30_000)
            throw InvalidLab();
        return definition;
    }

    private static string ReadText(JsonObject entry, string key, int min, int maxBytes)
    {
        if (entry[key] is not JsonValue value || !value.TryGetValue<string>(out var text) ||
            text.Length < min || text.Contains('\0') || Encoding.UTF8.GetByteCount(text) > maxBytes)
            throw InvalidLab();
        return text;
    }

    private static ApiError InvalidLab() =>
        new(400, "invalid_code_lab", "تعريف تمرين البرمجة أو حالات اختباره غير صالح.");
}
