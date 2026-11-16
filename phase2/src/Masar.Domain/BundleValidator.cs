using System.Text.Json.Nodes;

namespace Masar.Domain;

internal static class DomainLimits
{
    internal const int MaxAnswerLength = 4096;
    internal const int MaxJsonDepth = 64;
    internal const int MaxJsonNodes = 50000;
    internal const int MaxTextCharacters = 2_000_000;
    internal const int MaxRows = 512;
    internal const int MaxGoals = 128;
    internal const int MaxExpressionDepth = 24;
    internal const int MaxDependencyDepth = 64;
    internal const int MaxExercisesPerLesson = 128;
    internal const int MaxExercises = 4096;
    internal const int MaxPlanningWork = 100000;
    internal const int MaxPlanningDepth = 256;
}

internal static class BundleValidator
{
    internal static IReadOnlyList<string> Validate(JsonObject? bundle)
    {
        var errors = new List<string>();
        if (bundle is null) return new[] { "bundle must be an object" };
        if (!WithinStructuralLimits(bundle, errors)) return errors;
        if (bundle["sample"] is not JsonObject sample || bundle["graph"] is not JsonObject graph)
            return new[] { "bundle.sample and bundle.graph must be objects" };
        Schema(sample, "sample", errors);
        Schema(graph, "graph", errors);
        var sampleRelease = RequiredText(sample, "releaseId", "sample", errors, 128);
        var graphRelease = RequiredText(graph, "releaseId", "graph", errors, 128);
        if (sampleRelease != graphRelease) errors.Add("sample.releaseId and graph.releaseId must match");
        RequiredText(sample, "title", "sample", errors, 500);
        RequiredText(sample, "intro", "sample", errors);
        ValidateDisplayRows(sample, "glossary", "sample", errors, ValidateGlossaryEntry);

        var skills = Table(graph, "skills", "graph", errors);
        var lessons = Table(graph, "lessons", "graph", errors);
        var goals = Table(graph, "goals", "graph", errors, DomainLimits.MaxGoals);
        var sampleLessons = Table(sample, "lessons", "sample", errors);
        if (sampleRelease == "phase1-ar-v1" && (sampleLessons.Count != 3 || lessons.Count != 3))
            errors.Add("phase1-ar-v1 initial sample must contain exactly 3 matching lessons");
        if (!sampleLessons.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(lessons.Keys))
            errors.Add("sample and graph lesson ids must match");

        var edges = skills.Keys.ToDictionary(id => id, _ => new HashSet<string>(StringComparer.Ordinal), StringComparer.Ordinal);
        foreach (var (id, skill) in skills)
        {
            var path = $"graph.skills.{id}";
            RequiredText(skill, "description", path, errors, 4000);
            if (!skill.ContainsKey("required")) errors.Add($"{path}.required is required (null or expression)");
            else if (skill["required"] is not null) Expression(skill["required"], path + ".required", edges[id], skills, errors, 0);
            SkillList(skill["recommended"], path + ".recommended", skills, errors, allowEmpty: true);
        }
        foreach (var (id, lesson) in lessons)
        {
            var path = $"graph.lessons.{id}";
            var graphSkills = SkillList(lesson["skillIds"], path + ".skillIds", skills, errors);
            RequiredText(lesson, "why", path, errors, 4000);
            if (sampleLessons.TryGetValue(id, out var content))
            {
                var contentSkills = SkillList(content["skillIds"], $"sample.lessons.{id}.skillIds", skills, errors);
                if (!graphSkills.SetEquals(contentSkills)) errors.Add($"sample.lessons.{id}.skillIds must match graph lesson");
            }
        }
        foreach (var (id, goal) in goals)
        {
            var path = $"graph.goals.{id}";
            RequiredText(goal, "description", path, errors, 4000);
            SkillList(goal["skillIds"], path + ".skillIds", skills, errors);
            if (String(goal["status"]) is not ("sample" or "planned")) errors.Add($"{path}.status must be sample or planned");
        }
        CheckDag(edges, errors);
        var exerciseIds = new HashSet<string>(StringComparer.Ordinal);
        var totalExercises = 0;
        foreach (var (id, lesson) in sampleLessons)
        {
            var lessonPath = $"sample.lessons.{id}";
            ValidateLessonDisplay(lesson, lessonPath, errors);
            var path = lessonPath + ".exercises";
            if (lesson["exercises"] is not JsonArray exercises || exercises.Count is < 1 or > DomainLimits.MaxExercisesPerLesson)
            {
                errors.Add($"{path} must contain 1..{DomainLimits.MaxExercisesPerLesson} exercises");
                continue;
            }
            totalExercises += exercises.Count;
            for (var index = 0; index < exercises.Count; index++)
            {
                if (exercises[index] is not JsonObject exercise) errors.Add($"{path}[{index}] must be an object");
                else ValidateExercise(exercise, $"{path}[{index}]", errors, exerciseIds);
            }
        }
        if (totalExercises > DomainLimits.MaxExercises) errors.Add($"bundle exceeds {DomainLimits.MaxExercises} exercises");
        return errors;
    }

    private static void ValidateLessonDisplay(JsonObject lesson, string path, List<string> errors)
    {
        RequiredText(lesson, "summary", path, errors);
        RequiredText(lesson, "why", path, errors);
        RequiredText(lesson, "minutes", path, errors);
        RequiredText(lesson, "takeaway", path, errors);

        var objectives = RequiredDisplayArray(lesson, "objectives", path, errors);
        if (objectives is not null)
        {
            for (var index = 0; index < objectives.Count; index++)
                RequiredText(objectives[index], $"{path}.objectives[{index}]", errors);
        }

        ValidateDisplayRows(lesson, "sections", path, errors, ValidateSection);
        ValidateDisplayRows(lesson, "examples", path, errors, ValidateExample);
    }

    private static void ValidateSection(JsonObject section, string path, List<string> errors)
    {
        RequiredText(section, "heading", path, errors);
        RequiredText(section, "body", path, errors);
        if (section.ContainsKey("language") && String(section["language"]) is not ("python" or "javascript"))
            errors.Add($"{path}.language must be python or javascript when present");
    }

    private static void ValidateExample(JsonObject example, string path, List<string> errors)
    {
        RequiredText(example, "title", path, errors);
        RequiredText(example, "code", path, errors);
        RequiredText(example, "explanation", path, errors);
        if (String(example["language"]) is not ("text" or "python" or "javascript"))
            errors.Add($"{path}.language must be text, python or javascript");
    }

    private static void ValidateGlossaryEntry(JsonObject entry, string path, List<string> errors)
    {
        RequiredText(entry, "term", path, errors);
        RequiredText(entry, "technical", path, errors);
        RequiredText(entry, "definition", path, errors);
    }

    private static void ValidateDisplayRows(JsonObject owner, string key, string path, List<string> errors,
        Action<JsonObject, string, List<string>> validateRow)
    {
        var items = RequiredDisplayArray(owner, key, path, errors);
        if (items is null) return;

        for (var index = 0; index < items.Count; index++)
        {
            var itemPath = $"{path}.{key}[{index}]";
            if (items[index] is JsonObject row) validateRow(row, itemPath, errors);
            else errors.Add($"{itemPath} must be an object");
        }
    }

    private static JsonArray? RequiredDisplayArray(JsonObject owner, string key, string path, List<string> errors)
    {
        if (owner[key] is JsonArray { Count: > 0 } array) return array;
        errors.Add($"{path}.{key} must be a nonempty array");
        return null;
    }

    // Iterative before any recursive expression/planner operation: even a hand-built deep JsonNode is bounded.
    internal static bool WithinStructuralLimits(JsonNode root, List<string> errors)
    {
        try { return CheckStructure(root, errors); }
        catch (InvalidOperationException)
        { errors.Add("JSON contains invalid Unicode text or structure"); return false; }
        catch (ArgumentException)
        { errors.Add("JSON contains invalid Unicode text or structure"); return false; }
    }

    private static bool CheckStructure(JsonNode root, List<string> errors)
    {
        var stack = new Stack<(JsonNode? Node, int Depth)>();
        stack.Push((root, 0));
        var nodes = 0;
        long characters = 0;
        while (stack.TryPop(out var entry))
        {
            if (++nodes > DomainLimits.MaxJsonNodes || entry.Depth > DomainLimits.MaxJsonDepth)
            {
                errors.Add($"JSON exceeds {DomainLimits.MaxJsonNodes} nodes or depth {DomainLimits.MaxJsonDepth}");
                return false;
            }
            if ((entry.Node is JsonObject objectNode && nodes + stack.Count + objectNode.Count > DomainLimits.MaxJsonNodes) ||
                (entry.Node is JsonArray arrayNode && nodes + stack.Count + arrayNode.Count > DomainLimits.MaxJsonNodes))
            {
                errors.Add($"JSON exceeds {DomainLimits.MaxJsonNodes} nodes");
                return false;
            }
            if (entry.Node is JsonObject obj)
                foreach (var property in obj)
                {
                    characters += property.Key.Length;
                    if (characters > DomainLimits.MaxTextCharacters || !ExerciseEvaluator.TryNormalize(property.Key, out _))
                    { errors.Add("JSON exceeds text character limit or contains invalid Unicode text"); return false; }
                    stack.Push((property.Value, entry.Depth + 1));
                }
            else if (entry.Node is JsonArray array)
                foreach (var child in array) stack.Push((child, entry.Depth + 1));
            else if (entry.Node is JsonValue value)
            {
                if (value.TryGetValue<string>(out var text))
                {
                    characters += text.Length;
                    if (characters > DomainLimits.MaxTextCharacters)
                    { errors.Add($"JSON exceeds {DomainLimits.MaxTextCharacters} text characters"); return false; }
                    if (!ExerciseEvaluator.TryNormalize(text, out _))
                    { errors.Add("JSON contains invalid Unicode text"); return false; }
                }
            }
            if (characters > DomainLimits.MaxTextCharacters)
            {
                errors.Add($"JSON exceeds {DomainLimits.MaxTextCharacters} text characters");
                return false;
            }
        }
        return true;
    }

    internal static void ValidateExercise(JsonObject exercise, string path, List<string> errors, HashSet<string> exerciseIds)
    {
        var id = RequiredText(exercise, "id", path, errors, 128);
        if (id is not null && !exerciseIds.Add(id)) errors.Add($"{path}.id duplicates an exercise id in this release");
        RequiredText(exercise, "prompt", path, errors, 4000);
        RequiredText(exercise, "explanation", path, errors, 8000);
        var type = String(exercise["type"]);
        if (type is not ("choice" or "text")) errors.Add($"{path}.type must be choice or text");
        var optionIds = new HashSet<string>(StringComparer.Ordinal);
        if (exercise["options"] is not JsonArray options) errors.Add($"{path}.options must be an array");
        else
        {
            if (type == "choice" && options.Count is < 2 or > 32) errors.Add($"{path}.options must contain 2..32 choices");
            if (type == "text" && options.Count != 0) errors.Add($"{path}.options must be empty for text exercises");
            if (options.Count > 32) errors.Add($"{path}.options exceeds 32");
            foreach (var (node, index) in options.Take(32).Select((node, index) => (node, index)))
            {
                if (node is not JsonObject option) { errors.Add($"{path}.options[{index}] must be an object"); continue; }
                var optionId = RequiredText(option, "id", $"{path}.options[{index}]", errors, 128);
                RequiredText(option, "text", $"{path}.options[{index}]", errors, 4000);
                if (optionId is not null && ExerciseEvaluator.TryNormalize(optionId, out var normalized) && !optionIds.Add(normalized))
                    errors.Add($"{path}.options has duplicate ids after normalization");
            }
        }
        if (exercise["acceptedAnswers"] is not JsonArray accepted || accepted.Count is < 1 or > 32)
            errors.Add($"{path}.acceptedAnswers must contain 1..32 answers");
        else
        {
            var answers = new HashSet<string>(StringComparer.Ordinal);
            foreach (var answer in accepted)
            {
                var text = String(answer);
                if (text is null || text.Length > DomainLimits.MaxAnswerLength || !ExerciseEvaluator.TryNormalize(text, out var normalized) || normalized.Length == 0)
                { errors.Add($"{path}.acceptedAnswers contains an invalid or empty answer"); continue; }
                if (!answers.Add(normalized)) errors.Add($"{path}.acceptedAnswers contains duplicates after normalization");
                if (type == "choice" && !optionIds.Contains(normalized)) errors.Add($"{path}.acceptedAnswers must reference existing option ids");
            }
        }
        if (exercise["hints"] is not JsonArray hints || hints.Count > 16) errors.Add($"{path}.hints must be an array of at most 16 hints");
        else foreach (var hint in hints)
            if (String(hint) is not { Length: > 0 and <= 4000 } text || string.IsNullOrWhiteSpace(text)) errors.Add($"{path}.hints contains invalid text");
        if (exercise.ContainsKey("independent") && (exercise["independent"] is not JsonValue flag || !flag.TryGetValue<bool>(out _)))
            errors.Add($"{path}.independent must be boolean");
    }

    private static void Schema(JsonObject obj, string path, List<string> errors)
    {
        if (obj["schemaVersion"] is not JsonValue value || !value.TryGetValue<int>(out var version) || version != 1)
            errors.Add($"{path}.schemaVersion must be 1");
    }

    private static Dictionary<string, JsonObject> Table(JsonObject owner, string key, string path, List<string> errors, int maximum = DomainLimits.MaxRows)
    {
        var result = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        if (owner[key] is not JsonArray rows || rows.Count is < 1 || rows.Count > maximum)
        { errors.Add($"{path}.{key} must contain 1..{maximum} rows"); return result; }
        for (var index = 0; index < rows.Count; index++)
        {
            var rowPath = $"{path}.{key}[{index}]";
            if (rows[index] is not JsonObject row) { errors.Add($"{rowPath} must be an object"); continue; }
            var id = RequiredText(row, "id", rowPath, errors, 128);
            RequiredText(row, "title", rowPath, errors, 500);
            if (id is not null && !result.TryAdd(id, row)) errors.Add($"{rowPath}.id duplicates {id}");
        }
        return result;
    }

    private static HashSet<string> SkillList(JsonNode? node, string path, Dictionary<string, JsonObject> skills, List<string> errors, bool allowEmpty = false)
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        if (node is not JsonArray array || array.Count > DomainLimits.MaxRows || (!allowEmpty && array.Count == 0))
        { errors.Add($"{path} must be {(allowEmpty ? "an" : "a nonempty")} array of at most {DomainLimits.MaxRows} skill references"); return result; }
        foreach (var item in array)
        {
            var id = String(item);
            if (id is null || !skills.ContainsKey(id)) errors.Add($"{path}: missing skill reference");
            if (id is not null && !result.Add(id)) errors.Add($"{path}: duplicate skill references");
        }
        return result;
    }

    private static void Expression(JsonNode? node, string path, HashSet<string> edges, Dictionary<string, JsonObject> skills, List<string> errors, int depth)
    {
        if (depth > DomainLimits.MaxExpressionDepth) { errors.Add($"{path}: expression depth exceeds {DomainLimits.MaxExpressionDepth}"); return; }
        if (node is not JsonObject expr || expr.Count != 1) { errors.Add($"{path}: expression must contain exactly one of skill, allOf, anyOf"); return; }
        var key = expr.First().Key;
        if (key == "skill")
        {
            var id = String(expr["skill"]);
            if (id is null || !skills.ContainsKey(id)) errors.Add($"{path}: missing skill reference");
            else edges.Add(id);
            return;
        }
        if (key is not ("allOf" or "anyOf") || expr[key] is not JsonArray group || group.Count is < 1 or > DomainLimits.MaxRows)
        { errors.Add($"{path}: allOf/anyOf group must be a nonempty array of at most {DomainLimits.MaxRows} expressions"); return; }
        for (var index = 0; index < group.Count; index++) Expression(group[index], $"{path}.{key}[{index}]", edges, skills, errors, depth + 1);
    }

    // Kahn's algorithm rejects cycles conservatively across every OR edge, without recursive DFS.
    private static void CheckDag(Dictionary<string, HashSet<string>> edges, List<string> errors)
    {
        var remaining = edges.ToDictionary(pair => pair.Key, pair => pair.Value.Count, StringComparer.Ordinal);
        var dependents = edges.Keys.ToDictionary(id => id, _ => new List<string>(), StringComparer.Ordinal);
        foreach (var (owner, dependencies) in edges) foreach (var dependency in dependencies) dependents[dependency].Add(owner);
        var depth = edges.Keys.ToDictionary(id => id, _ => 0, StringComparer.Ordinal);
        var ready = new Queue<string>(remaining.Where(pair => pair.Value == 0).Select(pair => pair.Key));
        var visited = 0;
        while (ready.TryDequeue(out var id))
        {
            visited++;
            foreach (var dependent in dependents[id])
            {
                depth[dependent] = Math.Max(depth[dependent], depth[id] + 1);
                if (--remaining[dependent] == 0) ready.Enqueue(dependent);
            }
        }
        if (visited != edges.Count) errors.Add("graph contains a dependency cycle (including OR alternatives)");
        if (depth.Values.Any(value => value > DomainLimits.MaxDependencyDepth)) errors.Add($"graph dependency depth exceeds {DomainLimits.MaxDependencyDepth}");
    }

    internal static string? String(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text) ? text : null;

    private static string? RequiredText(JsonObject obj, string key, string path, List<string> errors,
        int max = DomainLimits.MaxTextCharacters)
    {
        var text = RequiredText(obj[key], $"{path}.{key}", errors, max);
        if (text is not null && (key is "id" or "releaseId") && (text != text.Trim() || text.Any(char.IsControl)))
        { errors.Add($"{path}.{key} must be trimmed without control characters"); return null; }
        return text;
    }

    private static string? RequiredText(JsonNode? node, string path, List<string> errors,
        int max = DomainLimits.MaxTextCharacters)
    {
        var text = String(node);
        if (!string.IsNullOrWhiteSpace(text) && text.Length <= max && ExerciseEvaluator.TryNormalize(text, out _))
            return text;

        errors.Add($"{path} must be nonempty valid text of at most {max} characters");
        return null;
    }
}
