using System.Text.Json.Nodes;

namespace Masar.Domain;

internal static class Planner
{
    internal static JsonObject Build(JsonObject bundle, string goalId, IEnumerable<string>? achievedSkillIds,
        IEnumerable<string>? preferredSkillIds, IReadOnlySet<string>? allowedLessonIds)
    {
        if (CurriculumEngine.Validate(bundle).Count != 0) return Empty(goalId);
        var graph = (JsonObject)bundle["graph"]!;
        var goal = ((JsonArray)graph["goals"]!).OfType<JsonObject>().FirstOrDefault(item => Text(item, "id") == goalId);
        if (goal is null) return Empty(goalId);
        try { return new Run(graph, goal, achievedSkillIds, preferredSkillIds, allowedLessonIds).Build(); }
        catch (PlanningLimitException) { return Empty(goalId); }
    }

    private static JsonObject Empty(string? goalId) => new()
    {
        ["goalId"] = goalId, ["status"] = "unavailable", ["steps"] = new JsonArray(),
        ["missingSkillIds"] = new JsonArray(), ["uncoveredSkillIds"] = new JsonArray(),
        ["chosenAlternatives"] = new JsonArray(), ["plannerVersion"] = "2.0.0"
    };

    private sealed class PlanningLimitException : Exception;
    private sealed record Step(string LessonId, string[] SkillIds, string Reason);
    private sealed record Choice(string SkillId, string Path, int Index, string[] SkillIds);
    private sealed class State
    {
        internal HashSet<string> Available = new(StringComparer.Ordinal);
        internal HashSet<string> Active = new(StringComparer.Ordinal);
        internal List<string> Required = [];
        internal HashSet<string> RequiredSet = new(StringComparer.Ordinal);
        internal List<Step> Steps = [];
        internal List<Choice> Choices = [];
        internal void Require(string id) { if (RequiredSet.Add(id)) Required.Add(id); }
        internal State Clone() => new()
        {
            Available = new(Available, StringComparer.Ordinal), Active = new(Active, StringComparer.Ordinal),
            Required = new(Required), RequiredSet = new(RequiredSet, StringComparer.Ordinal),
            Steps = new(Steps), Choices = new(Choices)
        };
        internal void Adopt(State state)
        {
            Available = state.Available; Active = state.Active; Required = state.Required;
            RequiredSet = state.RequiredSet; Steps = state.Steps; Choices = state.Choices;
        }
    }

    private sealed class Run
    {
        private readonly Dictionary<string, JsonObject> skills;
        private readonly JsonObject[] lessons;
        private readonly JsonObject goal;
        private readonly HashSet<string> achieved;
        private readonly HashSet<string> preferred;
        private int work;

        internal Run(JsonObject graph, JsonObject goal, IEnumerable<string>? achieved, IEnumerable<string>? preferred,
            IReadOnlySet<string>? allowedLessonIds)
        {
            skills = ((JsonArray)graph["skills"]!).OfType<JsonObject>().ToDictionary(item => Text(item, "id"), StringComparer.Ordinal);
            lessons = ((JsonArray)graph["lessons"]!).OfType<JsonObject>()
                .Where(lesson => allowedLessonIds is null || allowedLessonIds.Contains(Text(lesson, "id"))).ToArray();
            this.goal = goal;
            this.achieved = ReadInput(achieved);
            this.preferred = ReadInput(preferred);
        }

        private HashSet<string> ReadInput(IEnumerable<string>? input)
        {
            if (input is null) return new(StringComparer.Ordinal);
            var items = input.Take(DomainLimits.MaxRows + 1).ToArray();
            if (items.Length > DomainLimits.MaxRows) throw new PlanningLimitException();
            return new(items.Where(id => id is not null && skills.ContainsKey(id)), StringComparer.Ordinal);
        }

        internal JsonObject Build()
        {
            var state = new State { Available = new(achieved, StringComparer.Ordinal) };
            var goalSkills = Ids(goal["skillIds"]);
            foreach (var id in goalSkills) EnsureSkill(id, state, null, 0);
            var missing = state.Required.Where(id => !achieved.Contains(id)).ToArray();
            var uncovered = missing.Where(id => !state.Available.Contains(id)).ToArray();
            var status = Text(goal, "status") == "planned" ? "planned" : uncovered.Length != 0
                ? (state.Steps.Count > 0 || goalSkills.Any(achieved.Contains) ? "partial" : "unavailable") : "sample";
            return new JsonObject
            {
                ["goalId"] = Text(goal, "id"), ["status"] = status, ["plannerVersion"] = "2.0.0",
                ["steps"] = new JsonArray(state.Steps.Select(step => (JsonNode)new JsonObject
                {
                    ["lessonId"] = step.LessonId, ["skillIds"] = Strings(step.SkillIds), ["reason"] = step.Reason
                }).ToArray()),
                ["missingSkillIds"] = Strings(missing), ["uncoveredSkillIds"] = Strings(uncovered),
                ["chosenAlternatives"] = new JsonArray(state.Choices.Select(choice => (JsonNode)new JsonObject
                {
                    ["skillId"] = choice.SkillId, ["path"] = choice.Path,
                    ["alternativeIndex"] = choice.Index, ["selectedSkillIds"] = Strings(choice.SkillIds)
                }).ToArray())
            };
        }

        private void Tick(int depth)
        {
            if (++work > DomainLimits.MaxPlanningWork || depth > DomainLimits.MaxPlanningDepth) throw new PlanningLimitException();
        }

        private bool Satisfied(JsonNode? node, HashSet<string> available, int depth)
        {
            Tick(depth);
            if (node is null) return true;
            var expr = (JsonObject)node;
            if (expr.ContainsKey("skill")) return available.Contains(Text(expr, "skill"));
            if (expr["allOf"] is JsonArray all) return all.All(child => Satisfied(child, available, depth + 1));
            return ((JsonArray)expr["anyOf"]!).Any(child => Satisfied(child, available, depth + 1));
        }

        private bool LessonReady(JsonObject lesson, HashSet<string> available, int depth)
        {
            var local = new HashSet<string>(available, StringComparer.Ordinal);
            var ids = Ids(lesson["skillIds"]);
            bool changed;
            do
            {
                changed = false;
                foreach (var id in ids)
                {
                    Tick(depth);
                    if (!local.Contains(id) && Satisfied(skills[id]["required"], local, depth + 1))
                    { local.Add(id); changed = true; }
                }
            } while (changed);
            return ids.All(local.Contains);
        }

        private string[] EnsureExpression(JsonNode? node, State state, string owner, string path, HashSet<string> internalSkills, int depth)
        {
            Tick(depth);
            if (node is null) return [];
            var expr = (JsonObject)node;
            if (expr.ContainsKey("skill"))
            {
                var id = Text(expr, "skill");
                if (!internalSkills.Contains(id)) EnsureSkill(id, state, owner, depth + 1);
                return [id];
            }
            if (expr["allOf"] is JsonArray all)
                return all.SelectMany((child, index) => EnsureExpression(child, state, owner, $"{path}.allOf[{index}]", internalSkills, depth + 1)).Distinct(StringComparer.Ordinal).ToArray();
            var alternatives = (JsonArray)expr["anyOf"]!;
            (int[] Score, State Trial, string[] Ids, int Index)? selected = null;
            for (var index = 0; index < alternatives.Count; index++)
            {
                var trial = state.Clone();
                var ids = EnsureExpression(alternatives[index], trial, owner, $"{path}.anyOf[{index}]", internalSkills, depth + 1);
                var available = new HashSet<string>(trial.Available, StringComparer.Ordinal);
                available.UnionWith(internalSkills);
                int[] score = [Satisfied(alternatives[index], available, depth + 1) ? 0 : 1,
                    trial.Required.Count(id => !available.Contains(id)), trial.Steps.Count - state.Steps.Count,
                    -ids.Count(preferred.Contains), index];
                if (selected is null || Compare(score, selected.Value.Score) < 0) selected = (score, trial, ids, index);
            }
            var choice = selected!.Value;
            state.Adopt(choice.Trial);
            state.Choices.Add(new(owner, path, choice.Index, choice.Ids));
            return choice.Ids;
        }

        private void EnsureSkill(string id, State state, string? forSkillId, int depth)
        {
            Tick(depth);
            state.Require(id);
            if (state.Available.Contains(id) || state.Active.Contains(id)) return;
            state.Active.Add(id);
            var lesson = lessons.FirstOrDefault(item => Ids(item["skillIds"]).Contains(id, StringComparer.Ordinal));
            if (lesson is null)
            {
                EnsureExpression(skills[id]["required"], state, id, "required", new(StringComparer.Ordinal), depth + 1);
                state.Active.Remove(id);
                return;
            }
            var taught = Ids(lesson["skillIds"]);
            var internalSkills = new HashSet<string>(taught, StringComparer.Ordinal);
            foreach (var taughtId in taught)
                if (!state.Available.Contains(taughtId)) EnsureExpression(skills[taughtId]["required"], state, taughtId, "required", internalSkills, depth + 1);
            if (!state.Steps.Any(step => step.LessonId == Text(lesson, "id")) && LessonReady(lesson, state.Available, depth + 1))
            {
                var newIds = taught.Where(taughtId => !state.Available.Contains(taughtId)).ToArray();
                if (newIds.Length > 0)
                {
                    var purpose = forSkillId is not null ? $"تمهيدًا لمهارة «{Text(skills[forSkillId], "title")}»" : $"للتقدم نحو هدف «{Text(goal, "title")}»";
                    var reason = $"ندرس «{Text(lesson, "title")}» {purpose}. {Text(lesson, "why")} المهارات الجديدة: {string.Join("، ", newIds.Select(taughtId => Text(skills[taughtId], "title")))}.";
                    state.Steps.Add(new(Text(lesson, "id"), newIds, reason));
                    foreach (var taughtId in newIds) { state.Available.Add(taughtId); state.Require(taughtId); }
                }
            }
            state.Active.Remove(id);
        }

        private static int Compare(int[] left, int[] right)
        {
            for (var index = 0; index < left.Length; index++)
                if (left[index] != right[index]) return left[index].CompareTo(right[index]);
            return 0;
        }
    }

    private static string Text(JsonObject obj, string key) => obj[key]!.GetValue<string>();
    private static string[] Ids(JsonNode? node) => ((JsonArray)node!).Select(item => item!.GetValue<string>()).ToArray();
    private static JsonArray Strings(IEnumerable<string> values) => new(values.Select(value => (JsonNode)JsonValue.Create(value)!).ToArray());
}
