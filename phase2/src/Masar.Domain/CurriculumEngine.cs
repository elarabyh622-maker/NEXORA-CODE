using System.Text.Json.Nodes;

namespace Masar.Domain;

/// <summary>Validates versioned content and produces deterministic, explained practice plans.</summary>
public static class CurriculumEngine
{
    public static IReadOnlyList<string> Validate(JsonObject bundle) => BundleValidator.Validate(bundle);

    public static JsonObject Plan(JsonObject bundle, string goalId,
        IEnumerable<string>? achievedSkillIds = null,
        IEnumerable<string>? preferredSkillIds = null)
        => Planner.Build(bundle, goalId, achievedSkillIds, preferredSkillIds);
}
