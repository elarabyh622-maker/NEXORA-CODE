using System.Text.Json.Nodes;
using Xunit;
using static Masar.Domain.Tests.Fixtures;

namespace Masar.Domain.Tests;

public sealed class CurriculumEngineTests
{
    [Fact]
    public void MatchesAllTwentyFivePhase1ReferencePlansIncludingReasonsAndStatuses()
    {
        var cases = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "phase1-plans.json")))!.AsArray();
        Assert.Equal(25, cases.Count);
        foreach (var item in cases)
        {
            var plan = CurriculumEngine.Plan(Phase1(), item!["goalId"]!.GetValue<string>(),
                Strings(item["achievedSkillIds"]), Strings(item["preferredSkillIds"]));
            plan.Remove("plannerVersion");
            Assert.True(JsonNode.DeepEquals(item["expected"], plan), $"Phase1 parity failed for {item["goalId"]}, achieved {item["achievedSkillIds"]}");
        }
    }

    [Fact]
    public void Phase1ImportAndExplorationPlanPreservePublishedContract()
    {
        var bundle = Phase1();
        Assert.Empty(CurriculumEngine.Validate(bundle));
        var plan = CurriculumEngine.Plan(bundle, "explore");
        Assert.Equal("sample", plan["status"]!.GetValue<string>());
        Assert.Equal("2.0.0", plan["plannerVersion"]!.GetValue<string>());
        Assert.Equal(new[] { "what-is-a-program", "step-by-step", "first-variable" }, LessonIds(plan));
        Assert.Empty(Strings(plan["uncoveredSkillIds"]));
        Assert.Equal(4, Strings(plan["missingSkillIds"]).Length);
        Assert.All(((JsonArray)plan["steps"]!).OfType<JsonObject>(), step => Assert.Contains("المهارات الجديدة", step["reason"]!.GetValue<string>()));
    }

    [Fact]
    public void PlannedGoalStaysPlannedAndIdentifiesUnbuiltContent()
    {
        var plan = CurriculumEngine.Plan(Phase1(), "react");
        Assert.Equal("planned", plan["status"]!.GetValue<string>());
        Assert.Equal(new[] { "react.component" }, Strings(plan["uncoveredSkillIds"]));
        Assert.Equal(3, LessonIds(plan).Length);
    }

    [Fact]
    public void PlannedStatusIsPreservedEvenWhenAllSkillsHaveAvailableLessonsOrEvidence()
    {
        var bundle = Bundle("a");
        bundle["graph"]!["goals"]![0]!["status"] = "planned";
        Assert.Equal("planned", CurriculumEngine.Plan(bundle, "goal")["status"]!.GetValue<string>());
        Assert.Equal("planned", CurriculumEngine.Plan(bundle, "goal", new[] { "a" })["status"]!.GetValue<string>());
    }

    [Fact]
    public void GoalChangesReuseAchievedSkillsWithoutMutatingInputs()
    {
        var bundle = Phase1();
        var before = bundle.ToJsonString();
        var achieved = new[] { "concept.program", "concept.input-output", "concept.sequence", "concept.variable", "unknown" };
        var preferred = new[] { "concept.variable" };
        var plan = CurriculumEngine.Plan(bundle, "react", achieved, preferred);
        Assert.Empty(LessonIds(plan));
        Assert.Equal(new[] { "react.component" }, Strings(plan["missingSkillIds"]));
        Assert.Equal(before, bundle.ToJsonString());
        Assert.Equal("unknown", achieved.Last());
        Assert.Single(preferred);
        Assert.Empty(LessonIds(CurriculumEngine.Plan(bundle, "web", achieved)));
        plan["steps"]!.AsArray().Add(new JsonObject());
        Assert.Equal(before, bundle.ToJsonString());
    }

    [Theory]
    [InlineData(1)]
    [InlineData(4)]
    public void GeneralReleasesAreNotRestrictedToThreeLessons(int count)
    {
        var bundle = Bundle(Enumerable.Range(0, count).Select(value => "s" + value).ToArray());
        Assert.Empty(CurriculumEngine.Validate(bundle));
    }

    [Fact]
    public void InitialSampleRequiresThreeLessonsAndReleaseIdsMustMatch()
    {
        var bundle = Bundle("a");
        bundle["sample"]!["releaseId"] = "phase1-ar-v1";
        bundle["graph"]!["releaseId"] = "phase1-ar-v1";
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("exactly 3"));
        bundle["graph"]!["releaseId"] = "other";
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("must match"));
    }

    [Fact]
    public void NestedAndOrChoosesOneAlternativeAndHonorsPreferenceAfterCost()
    {
        var bundle = Bundle("a", "b", "c", "target");
        Skill(bundle, "target")["required"] = All(Ref("a"), Any(All(Ref("b")), All(Ref("c"))));
        Assert.Empty(CurriculumEngine.Validate(bundle));
        var plan = CurriculumEngine.Plan(bundle, "goal", preferredSkillIds: new[] { "c" });
        Assert.Equal(new[] { "lesson-a", "lesson-c", "lesson-target" }, LessonIds(plan));
        Assert.DoesNotContain("b", Strings(plan["missingSkillIds"]));
        var choice = Assert.Single(((JsonArray)plan["chosenAlternatives"]!).OfType<JsonObject>());
        Assert.Equal(1, choice["alternativeIndex"]!.GetValue<int>());
        Assert.Equal("required.allOf[1]", choice["path"]!.GetValue<string>());
        Assert.Equal(new[] { "c" }, Strings(choice["selectedSkillIds"]));
    }

    [Fact]
    public void AchievedOrBranchWinsOverPreferredUnachievedBranch()
    {
        var bundle = Bundle("a", "b", "target");
        Skill(bundle, "target")["required"] = Any(Ref("a"), Ref("b"));
        var plan = CurriculumEngine.Plan(bundle, "goal", new[] { "a" }, new[] { "b" });
        Assert.Equal(new[] { "lesson-target" }, LessonIds(plan));
        Assert.Equal(0, plan["chosenAlternatives"]![0]!["alternativeIndex"]!.GetValue<int>());
    }

    [Fact]
    public void FewerLessonsWinOverPreferenceAndUnresolvedTiesUseSourceOrder()
    {
        var bundle = Bundle("a", "b", "c", "target");
        Skill(bundle, "b")["required"] = Ref("a");
        Skill(bundle, "target")["required"] = Any(Ref("b"), Ref("c"));
        Assert.Equal(new[] { "lesson-c", "lesson-target" }, LessonIds(CurriculumEngine.Plan(bundle, "goal", preferredSkillIds: new[] { "b" })));
        Skill(bundle, "b")["required"] = null;
        Assert.Equal(new[] { "lesson-b", "lesson-target" }, LessonIds(CurriculumEngine.Plan(bundle, "goal")));
    }

    [Fact]
    public void NestedOrInsideOrPreservesBothChosenPaths()
    {
        var bundle = Bundle("a", "b", "c", "target");
        Skill(bundle, "target")["required"] = Any(Any(Ref("a"), Ref("b")), Ref("c"));
        var plan = CurriculumEngine.Plan(bundle, "goal", preferredSkillIds: new[] { "b" });
        Assert.Equal(new[] { "lesson-b", "lesson-target" }, LessonIds(plan));
        Assert.Equal(2, plan["chosenAlternatives"]!.AsArray().Count);
        Assert.Equal("required.anyOf[0]", plan["chosenAlternatives"]![0]!["path"]!.GetValue<string>());
        Assert.Equal("required", plan["chosenAlternatives"]![1]!["path"]!.GetValue<string>());
    }

    [Fact]
    public void BoundedInputsRejectLargeRowCountsTextsAndNodeCounts()
    {
        var bundle = Bundle("a");
        var rows = (JsonArray)bundle["graph"]!["skills"]!;
        var skill = rows[0]!.DeepClone();
        for (var index = 0; index < 512; index++) rows.Add(skill.DeepClone());
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("1..512 rows"));
        bundle = Bundle("a");
        bundle["unused"] = new string('x', 2_000_001);
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("text characters"));
        bundle = Bundle("a");
        bundle["unused"] = new JsonArray(Enumerable.Range(0, 50001).Select(_ => (JsonNode?)null).ToArray());
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("nodes"));
    }

    [Fact]
    public void BoundsSkillInputEnumerationInsteadOfHangingOnInfiniteEnumerable()
    {
        static IEnumerable<string> Infinite()
        {
            while (true) yield return "a";
        }
        AssertUnavailable(CurriculumEngine.Plan(Bundle("a"), "goal", Infinite()));
        AssertUnavailable(CurriculumEngine.Plan(Bundle("a"), "goal", preferredSkillIds: Infinite()));
    }

    [Fact]
    public void UncoveredAlternativeLosesToAvailableLesson()
    {
        var bundle = Bundle("a", "b", "target");
        RemoveLesson(bundle, "a");
        Skill(bundle, "target")["required"] = Any(Ref("a"), Ref("b"));
        var plan = CurriculumEngine.Plan(bundle, "goal");
        Assert.Equal(new[] { "lesson-b", "lesson-target" }, LessonIds(plan));
        Assert.Empty(Strings(plan["uncoveredSkillIds"]));
    }

    [Fact]
    public void SameLessonCanIntroducePrerequisiteBeforeDependentSkillRegardlessOfListOrder()
    {
        var bundle = Bundle("a", "b");
        Skill(bundle, "b")["required"] = Ref("a");
        RemoveLesson(bundle, "a");
        bundle["graph"]!["lessons"]![0]!["skillIds"] = new JsonArray("b", "a");
        bundle["sample"]!["lessons"]![0]!["skillIds"] = new JsonArray("b", "a");
        Assert.Empty(CurriculumEngine.Validate(bundle));
        var plan = CurriculumEngine.Plan(bundle, "goal");
        Assert.Equal(new[] { "lesson-b" }, LessonIds(plan));
        Assert.Empty(Strings(plan["uncoveredSkillIds"]));
    }

    [Fact]
    public void MissingContentProducesPartialOrUnavailableWithoutInventingLesson()
    {
        var bundle = Bundle("a", "b");
        RemoveLesson(bundle, "b");
        Skill(bundle, "b")["required"] = Ref("a");
        var partial = CurriculumEngine.Plan(bundle, "goal");
        Assert.Equal("partial", partial["status"]!.GetValue<string>());
        Assert.Equal(new[] { "lesson-a" }, LessonIds(partial));
        Assert.Equal(new[] { "b" }, Strings(partial["uncoveredSkillIds"]));
        Skill(bundle, "b")["required"] = null;
        Assert.Equal("unavailable", CurriculumEngine.Plan(bundle, "goal")["status"]!.GetValue<string>());
    }

    [Theory]
    [InlineData("allOf")]
    [InlineData("anyOf")]
    public void RejectsEmptyRequirementGroups(string key)
    {
        var bundle = Bundle("a");
        Skill(bundle, "a")["required"] = new JsonObject { [key] = new JsonArray() };
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("nonempty array"));
        AssertUnavailable(CurriculumEngine.Plan(bundle, "goal"));
    }

    [Fact]
    public void RejectsMissingReferencesAndAmbiguousExpressions()
    {
        var bundle = Bundle("a");
        Skill(bundle, "a")["required"] = Ref("missing");
        Skill(bundle, "a")["recommended"] = new JsonArray("missing");
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("missing skill reference"));
        Skill(bundle, "a")["required"] = new JsonObject { ["skill"] = "a", ["allOf"] = new JsonArray(Ref("a")) };
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("exactly one"));
    }

    [Fact]
    public void RejectsCyclesConservativelyAcrossEveryAlternative()
    {
        var bundle = Bundle("a", "b", "c");
        Skill(bundle, "a")["required"] = Any(Ref("b"), Ref("c"));
        Skill(bundle, "b")["required"] = Ref("a");
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("cycle"));
        AssertUnavailable(CurriculumEngine.Plan(bundle, "goal"));
    }

    [Fact]
    public void RejectsDuplicateIdsAndMismatchedLessonSkills()
    {
        var bundle = Bundle("a", "b");
        ((JsonArray)bundle["graph"]!["skills"]!).Add(Skill(bundle, "a").DeepClone());
        bundle["sample"]!["lessons"]![0]!["skillIds"] = new JsonArray("b");
        bundle["sample"]!["lessons"]![1]!["exercises"]![0]!["id"] = "exercise-a";
        var errors = CurriculumEngine.Validate(bundle);
        Assert.Contains(errors, error => error.Contains("duplicates a"));
        Assert.Contains(errors, error => error.Contains("skillIds must match"));
        Assert.Contains(errors, error => error.Contains("duplicates an exercise id"));
    }

    [Fact]
    public void DeepHandBuiltJsonIsRejectedWithoutRecursiveOverflow()
    {
        var bundle = Bundle("a");
        JsonNode expression = Ref("a");
        for (var index = 0; index < 1000; index++) expression = All(expression);
        Skill(bundle, "a")["required"] = expression;
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("depth"));
        AssertUnavailable(CurriculumEngine.Plan(bundle, "goal"));
    }

    [Fact]
    public void RejectsExpressionAndDependencyDepthLimits()
    {
        var bundle = Bundle("a", "b");
        JsonNode expression = Ref("a");
        for (var index = 0; index < 25; index++) expression = All(expression);
        Skill(bundle, "b")["required"] = expression;
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("expression depth"));
        var ids = Enumerable.Range(0, 66).Select(value => "s" + value).ToArray();
        bundle = Bundle(ids);
        for (var index = 1; index < ids.Length; index++) Skill(bundle, ids[index])["required"] = Ref(ids[index - 1]);
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("dependency depth"));
    }

    [Fact]
    public void UnknownGoalAndInvalidShapesReturnCompleteUnavailableContract()
    {
        AssertUnavailable(CurriculumEngine.Plan(Phase1(), "unknown"));
        AssertUnavailable(CurriculumEngine.Plan(new JsonObject(), "goal"));
        Assert.NotEmpty(CurriculumEngine.Validate(new JsonObject { ["sample"] = new JsonArray(), ["graph"] = new JsonObject() }));
        Assert.NotEmpty(CurriculumEngine.Validate(null!));
    }

    [Fact]
    public void RepeatedPlansAreDeterministicAndExplainPrerequisites()
    {
        var bundle = Bundle("a", "b");
        Skill(bundle, "b")["required"] = Ref("a");
        var first = CurriculumEngine.Plan(bundle, "goal");
        Assert.Equal(first.ToJsonString(), CurriculumEngine.Plan(bundle, "goal").ToJsonString());
        Assert.Contains("تمهيدًا لمهارة «b»", first["steps"]![0]!["reason"]!.GetValue<string>());
        Assert.Contains("هدف «هدفي»", first["steps"]![1]!["reason"]!.GetValue<string>());
    }

    private static void RemoveLesson(JsonObject bundle, string skill)
    {
        foreach (var owner in new[] { "graph", "sample" })
        {
            var array = (JsonArray)bundle[owner]!["lessons"]!;
            array.Remove(array.OfType<JsonObject>().Single(item => item["id"]!.GetValue<string>() == "lesson-" + skill));
        }
    }

    private static void AssertUnavailable(JsonObject plan)
    {
        Assert.Equal("unavailable", plan["status"]!.GetValue<string>());
        foreach (var key in new[] { "steps", "missingSkillIds", "uncoveredSkillIds", "chosenAlternatives" }) Assert.IsType<JsonArray>(plan[key]);
        Assert.True(plan.ContainsKey("goalId"));
        Assert.Equal("2.0.0", plan["plannerVersion"]!.GetValue<string>());
    }
}
