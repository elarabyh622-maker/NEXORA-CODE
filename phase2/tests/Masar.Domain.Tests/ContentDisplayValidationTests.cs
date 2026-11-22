using System.Text.Json.Nodes;
using Xunit;
using static Masar.Domain.Tests.Fixtures;

namespace Masar.Domain.Tests;

public sealed class ContentDisplayValidationTests
{
    [Fact]
    public void AcceptsTheOriginalPhase1BundleAndAnUnlabeledSection()
    {
        Assert.Empty(CurriculumEngine.Validate(Phase1()));
        var bundle = Bundle("a");
        Assert.False(DisplayObject(bundle, "section").ContainsKey("language"));
        Assert.Empty(CurriculumEngine.Validate(bundle));
    }

    [Theory]
    [InlineData("csharp")]
    [InlineData("cpp")]
    [InlineData("java")]
    [InlineData("go")]
    public void AcceptsLocallyRunLanguagesInExamplesAndSections(string language)
    {
        var bundle = Bundle("a");
        DisplayObject(bundle, "section")["language"] = language;
        DisplayObject(bundle, "example")["language"] = language;
        Assert.Empty(CurriculumEngine.Validate(bundle));
    }

    [Theory]
    [InlineData("sample", "title")]
    [InlineData("sample", "intro")]
    [InlineData("sample", "lessons")]
    [InlineData("sample", "glossary")]
    [InlineData("lesson", "title")]
    [InlineData("lesson", "summary")]
    [InlineData("lesson", "why")]
    [InlineData("lesson", "minutes")]
    [InlineData("lesson", "takeaway")]
    [InlineData("lesson", "objectives")]
    [InlineData("lesson", "sections")]
    [InlineData("lesson", "examples")]
    [InlineData("section", "heading")]
    [InlineData("section", "body")]
    [InlineData("example", "title")]
    [InlineData("example", "language")]
    [InlineData("example", "code")]
    [InlineData("example", "explanation")]
    [InlineData("term", "term")]
    [InlineData("term", "technical")]
    [InlineData("term", "definition")]
    public void RejectsMissingDisplayFields(string owner, string key)
    {
        var bundle = Bundle("a");
        Assert.True(DisplayObject(bundle, owner).Remove(key));
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains($".{key} must ", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData("sample", "intro", "null", ".intro")]
    [InlineData("sample", "glossary", "{}", ".glossary")]
    [InlineData("sample", "glossary", "[]", ".glossary")]
    [InlineData("sample", "glossary", "[null]", ".glossary[0]")]
    [InlineData("term", "technical", "[]", ".glossary[0].technical")]
    [InlineData("term", "definition", "\" \"", ".glossary[0].definition")]
    [InlineData("lesson", "summary", "{}", ".summary")]
    [InlineData("lesson", "why", "false", ".why")]
    [InlineData("lesson", "minutes", "12", ".minutes")]
    [InlineData("lesson", "takeaway", "\" \"", ".takeaway")]
    [InlineData("lesson", "objectives", "[]", ".objectives")]
    [InlineData("lesson", "objectives", "[{}]", ".objectives[0]")]
    [InlineData("lesson", "objectives", "[\" \" ]", ".objectives[0]")]
    [InlineData("lesson", "sections", "null", ".sections")]
    [InlineData("lesson", "sections", "[]", ".sections")]
    [InlineData("lesson", "sections", "[\"heading\"]", ".sections[0]")]
    [InlineData("section", "heading", "true", ".sections[0].heading")]
    [InlineData("section", "body", "{}", ".sections[0].body")]
    [InlineData("section", "language", "null", ".sections[0].language")]
    [InlineData("section", "language", "0", ".sections[0].language")]
    [InlineData("section", "language", "\"\"", ".sections[0].language")]
    [InlineData("section", "language", "\"text\"", ".sections[0].language")]
    [InlineData("lesson", "examples", "[]", ".examples")]
    [InlineData("lesson", "examples", "[[]]", ".examples[0]")]
    [InlineData("example", "title", "4", ".examples[0].title")]
    [InlineData("example", "language", "false", ".examples[0].language")]
    [InlineData("example", "language", "\"unsupported\"", ".examples[0].language")]
    [InlineData("example", "code", "{}", ".examples[0].code")]
    [InlineData("example", "explanation", "\" \"", ".examples[0].explanation")]
    public void RejectsInvalidDisplayValuesAtTheirFieldPath(string owner, string key, string json, string errorPath)
    {
        var bundle = Bundle("a");
        DisplayObject(bundle, owner)[key] = JsonNode.Parse(json);
        Assert.Contains(CurriculumEngine.Validate(bundle), error => error.Contains($"{errorPath} must ", StringComparison.Ordinal));
    }

    private static JsonObject DisplayObject(JsonObject bundle, string owner)
    {
        var sample = bundle["sample"]!.AsObject();
        var lesson = sample["lessons"]![0]!.AsObject();
        return owner switch
        {
            "sample" => sample,
            "lesson" => lesson,
            "term" => sample["glossary"]![0]!.AsObject(),
            "section" => lesson["sections"]![0]!.AsObject(),
            "example" => lesson["examples"]![0]!.AsObject(),
            _ => throw new ArgumentOutOfRangeException(nameof(owner))
        };
    }
}
