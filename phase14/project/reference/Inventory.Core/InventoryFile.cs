using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Unicode;

namespace Nexora.Inventory;

public static class InventoryFile
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.Create(UnicodeRanges.BasicLatin, UnicodeRanges.Arabic),
        RespectRequiredConstructorParameters = true,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict
    };

    public static Inventory Load(string path)
    {
        var inventory = new Inventory();
        string json;
        try
        {
            json = File.ReadAllText(path);
        }
        catch (FileNotFoundException)
        {
            return inventory;
        }
        catch (DirectoryNotFoundException)
        {
            return inventory;
        }

        List<Product?>? products = JsonSerializer.Deserialize<List<Product?>>(json, Options);
        if (products is null)
        {
            throw new JsonException("ملف المخزون لازم يحتوي على قائمة أصناف.");
        }

        foreach (Product? product in products)
        {
            if (product is null)
            {
                throw new JsonException("قائمة المخزون فيها سجل فارغ.");
            }

            inventory.AddProduct(product);
        }

        return inventory;
    }

    public static void Save(string path, Inventory inventory)
    {
        string destination = Path.GetFullPath(path);
        string folder = Path.GetDirectoryName(destination)!;
        Directory.CreateDirectory(folder);
        string temporary = Path.Combine(folder, $"{Guid.NewGuid():N}.tmp");

        // اكتب النسخة الجديدة كاملة قبل استبدال ملف المخزون.
        try
        {
            string json = JsonSerializer.Serialize(inventory.Products, Options);
            File.WriteAllText(temporary, json);
            File.Move(temporary, destination, overwrite: true);
        }
        finally
        {
            File.Delete(temporary);
        }
    }
}
