using System.Text.Json.Nodes;
using Xunit;
using static Masar.Domain.Tests.Fixtures;

namespace Masar.Domain.Tests;

public sealed class ExerciseEvaluatorTests
{
    [Theory]
    [InlineData("9")]
    [InlineData(" ٩ ")]
    [InlineData("۹")]
    [InlineData("９")]
    [InlineData("\u00a09\u00a0")]
    public void NormalizesArabicPersianAndCompatibilityDigitsAndTrim(string answer)
    {
        var result = ExerciseEvaluator.Evaluate(Exercise(), answer, 0);
        Assert.True(result["correct"]!.GetValue<bool>());
        Assert.False(result["assisted"]!.GetValue<bool>());
        Assert.Equal("شرح موثوق من المؤلف.", result["explanation"]!.GetValue<string>());
        Assert.Equal(3, result.Count);
    }

    [Fact]
    public void NormalizesTrustedAnswersTooAndPreservesMeaningfulCaseAndWhitespace()
    {
        Assert.True(ExerciseEvaluator.Evaluate(Exercise(" ۹ "), "9", 0)["correct"]!.GetValue<bool>());
        Assert.True(ExerciseEvaluator.Evaluate(Exercise("ﬁle"), "file", 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(Exercise("Points"), "points", 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(Exercise("أهلًا سارة"), "أهلًا  سارة", 0)["correct"]!.GetValue<bool>());
    }

    [Theory]
    [InlineData(1)]
    [InlineData(20)]
    public void MarksHintsAssistedRegardlessOfCorrectnessWithoutClaimingMastery(int hints)
    {
        foreach (var answer in new[] { "9", "wrong" })
        {
            var result = ExerciseEvaluator.Evaluate(Exercise(), answer, hints);
            Assert.True(result["assisted"]!.GetValue<bool>());
            Assert.False(result.ContainsKey("mastery"));
            Assert.False(result.ContainsKey("achievedSkillIds"));
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData(" \t\n")]
    [InlineData("null")]
    [InlineData("console.log(9)")]
    [InlineData("System.Environment.Exit(0)")]
    public void NeverAcceptsEmptyOrExecutesSubmittedCode(string answer)
    {
        Assert.False(ExerciseEvaluator.Evaluate(Exercise(), answer, 0)["correct"]!.GetValue<bool>());
    }

    [Fact]
    public void ClientCorrectFlagCannotOverrideComputedResultAndInputIsUnchanged()
    {
        var exercise = Exercise();
        exercise["correct"] = true;
        var before = exercise.ToJsonString();
        Assert.False(ExerciseEvaluator.Evaluate(exercise, "wrong", 0)["correct"]!.GetValue<bool>());
        Assert.Equal(before, exercise.ToJsonString());
    }

    [Fact]
    public void ChoiceMatchesOptionIdRatherThanDisplayText()
    {
        var exercise = Exercise("yes", "choice");
        Assert.True(ExerciseEvaluator.Evaluate(exercise, " yes ", 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(exercise, "نعم", 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(exercise, "no", 0)["correct"]!.GetValue<bool>());
    }

    [Fact]
    public void RejectsInvalidAnswerLengthsUnicodeAndNegativeHintCounts()
    {
        Assert.False(ExerciseEvaluator.Evaluate(Exercise(), new string('9', 4097), 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(Exercise(), "9", -1)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(Exercise(), null!, 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(Exercise(), "\ud800", 0)["correct"]!.GetValue<bool>());
        Assert.False(ExerciseEvaluator.Evaluate(null!, "9", 0)["correct"]!.GetValue<bool>());
    }

    [Fact]
    public void RejectsMalformedUnicodeFromBothParsedJsonAndHandBuiltContent()
    {
        var bundle = Bundle("a");
        bundle["bad"] = JsonNode.Parse("\"\\ud800\"");
        Assert.NotEmpty(CurriculumEngine.Validate(bundle));
        var exercise = Exercise();
        exercise["prompt"] = JsonNode.Parse("\"\\ud800\"");
        Assert.False(ExerciseEvaluator.Evaluate(exercise, "9", 0)["correct"]!.GetValue<bool>());
        exercise = Exercise();
        exercise["hints"] = new JsonArray("\ud800");
        Assert.False(ExerciseEvaluator.Evaluate(exercise, "9", 0)["correct"]!.GetValue<bool>());
        bundle = Bundle("a");
        bundle["\ud800"] = "bad property name";
        Assert.NotEmpty(CurriculumEngine.Validate(bundle));
        bundle = JsonNode.Parse("{\"\\ud800\":1}")!.AsObject();
        Assert.NotEmpty(CurriculumEngine.Validate(bundle));
    }

    [Theory]
    [InlineData("unknown-type")]
    [InlineData("empty-answers")]
    [InlineData("whitespace-answer")]
    [InlineData("non-string-answer")]
    [InlineData("duplicate-normalized-answer")]
    [InlineData("nonexistent-option")]
    [InlineData("duplicate-option")]
    [InlineData("one-option")]
    [InlineData("invalid-option-text")]
    [InlineData("text-with-options")]
    [InlineData("no-hints")]
    [InlineData("bad-hint")]
    [InlineData("bad-independent")]
    [InlineData("no-prompt")]
    [InlineData("no-explanation")]
    public void BundleValidationAndDirectEvaluationBothRejectMalformedExercises(string scenario)
    {
        var bundle = Bundle("a");
        var exercise = Exercise("yes", "choice");
        switch (scenario)
        {
            case "unknown-type": exercise["type"] = "code"; break;
            case "empty-answers": exercise["acceptedAnswers"] = new JsonArray(); break;
            case "whitespace-answer": exercise["acceptedAnswers"] = new JsonArray(" "); break;
            case "non-string-answer": exercise["acceptedAnswers"] = new JsonArray(9); break;
            case "duplicate-normalized-answer": exercise["acceptedAnswers"] = new JsonArray("yes", " yes "); break;
            case "nonexistent-option": exercise["acceptedAnswers"] = new JsonArray("missing"); break;
            case "duplicate-option": exercise["options"]![1]!["id"] = " yes "; break;
            case "one-option": exercise["options"]!.AsArray().RemoveAt(1); break;
            case "invalid-option-text": exercise["options"]![0]!["text"] = 123; break;
            case "text-with-options": exercise["type"] = "text"; break;
            case "no-hints": exercise.Remove("hints"); break;
            case "bad-hint": exercise["hints"] = new JsonArray(1); break;
            case "bad-independent": exercise["independent"] = "true"; break;
            case "no-prompt": exercise.Remove("prompt"); break;
            case "no-explanation": exercise.Remove("explanation"); break;
        }
        bundle["sample"]!["lessons"]![0]!["exercises"] = new JsonArray(exercise);
        Assert.NotEmpty(CurriculumEngine.Validate(bundle));
        var result = ExerciseEvaluator.Evaluate(exercise, "yes", 0);
        Assert.False(result["correct"]!.GetValue<bool>());
        Assert.Contains("غير صالح", result["explanation"]!.GetValue<string>());
    }

    [Fact]
    public void EnforcesExerciseCountAndAnswerSizeLimits()
    {
        var bundle = Bundle("a");
        var exercise = (JsonObject)bundle["sample"]!["lessons"]![0]!["exercises"]![0]!;
        exercise["acceptedAnswers"] = new JsonArray(new string('x', 4097));
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("invalid or empty answer"));
        var many = new JsonArray();
        for (var index = 0; index < 129; index++)
        {
            var next = Exercise();
            next["id"] = "e" + index;
            many.Add(next);
        }
        bundle["sample"]!["lessons"]![0]!["exercises"] = many;
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains("1..128 exercises"));
    }
}
