using System.Text;
using System.Text.Json.Nodes;

namespace Masar.Domain;

/// <summary>Compares a submitted answer with trusted server content; never executes code.</summary>
public static class ExerciseEvaluator
{
    public static JsonObject Evaluate(JsonObject exercise, string answer, int hintsUsed)
    {
        var errors = new List<string>();
        if (exercise is null || !BundleValidator.WithinStructuralLimits(exercise, errors))
            return Result(false, hintsUsed > 0, "تعذر تقييم التمرين لأن محتواه غير صالح.");
        BundleValidator.ValidateExercise(exercise, "exercise", errors, new HashSet<string>(StringComparer.Ordinal));
        if (errors.Count != 0)
            return Result(false, hintsUsed > 0, "تعذر تقييم التمرين لأن محتواه غير صالح.");
        if (hintsUsed < 0 || answer is null || answer.Length > DomainLimits.MaxAnswerLength || !TryNormalize(answer, out var normalized))
            return Result(false, hintsUsed > 0, "الإجابة أو عدد التلميحات غير صالح.");
        var accepted = (JsonArray)exercise["acceptedAnswers"]!;
        var correct = normalized.Length > 0 && accepted.Any(item =>
            TryNormalize(item!.GetValue<string>(), out var expected) && normalized == expected);
        return Result(correct, hintsUsed > 0, exercise["explanation"]!.GetValue<string>());
    }

    internal static bool TryNormalize(string value, out string normalized)
    {
        normalized = "";
        try
        {
            var text = value.Normalize(NormalizationForm.FormKC).Trim();
            var chars = text.ToCharArray();
            for (var index = 0; index < chars.Length; index++)
            {
                if (chars[index] is >= '\u0660' and <= '\u0669') chars[index] = (char)('0' + chars[index] - '\u0660');
                else if (chars[index] is >= '\u06f0' and <= '\u06f9') chars[index] = (char)('0' + chars[index] - '\u06f0');
            }
            normalized = new string(chars);
            return true;
        }
        catch (ArgumentException) { return false; }
    }

    private static JsonObject Result(bool correct, bool assisted, string explanation) => new()
    {
        ["correct"] = correct, ["assisted"] = assisted, ["explanation"] = explanation
    };
}
