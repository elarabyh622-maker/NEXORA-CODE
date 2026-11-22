using System.Text;
using System.Text.Json;
using Nexora.Inventory;

Console.OutputEncoding = Encoding.UTF8;

(string Name, Action Run)[] tests =
[
    (nameof(AddProductNormalizesSku), AddProductNormalizesSku),
    (nameof(ReceiveStockProtectsQuantity), ReceiveStockProtectsQuantity),
    (nameof(RemoveStockValidatesBeforeChanging), RemoveStockValidatesBeforeChanging),
    (nameof(SaveAndReloadPreserveInventory), SaveAndReloadPreserveInventory),
    (nameof(LoadRejectsInvalidData), LoadRejectsInvalidData)
];

int failures = 0;
foreach ((string name, Action run) in tests)
{
    try
    {
        run();
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception error)
    {
        failures++;
        Console.Error.WriteLine($"FAIL {name} ({error.GetType().Name}) {error.Message}");
    }
}

Console.WriteLine($"{tests.Length - failures}/{tests.Length} passed.");
return failures == 0 ? 0 : 1;

static void AddProductNormalizesSku()
{
    var inventory = new Inventory();
    inventory.AddProduct(" p-102 ", "قلم حبر");
    inventory.AddProduct("p-101", " دفتر جيب ");

    RequireEqual(new Product("P-101", "دفتر جيب", 0), inventory.GetProduct(" p-101"));
    RequireEqual("P-101", inventory.Products[0].Sku);
    RequireThrows<InvalidOperationException>(() => inventory.AddProduct("P-101", "صنف مكرر"));
    RequireThrows<ArgumentException>(() => inventory.AddProduct(" ", "صنف"));
    RequireThrows<ArgumentException>(() => inventory.AddProduct("P-103", " "));
    RequireEqual(2, inventory.Products.Count);
}

static void ReceiveStockProtectsQuantity()
{
    var inventory = new Inventory();
    inventory.AddProduct("P-101", "دفتر جيب");

    RequireThrows<ArgumentOutOfRangeException>(() => inventory.ReceiveStock("P-101", 0));
    RequireThrows<ArgumentOutOfRangeException>(() => inventory.ReceiveStock("P-101", -1));
    RequireThrows<KeyNotFoundException>(() => inventory.ReceiveStock("P-999", 1));
    RequireEqual(0, inventory.GetProduct("P-101").Quantity);
    RequireEqual(int.MaxValue, inventory.ReceiveStock("p-101", int.MaxValue));
    RequireThrows<OverflowException>(() => inventory.ReceiveStock("P-101", 1));
    RequireEqual(int.MaxValue, inventory.GetProduct("P-101").Quantity);
}

static void RemoveStockValidatesBeforeChanging()
{
    var inventory = new Inventory();
    inventory.AddProduct("P-101", "دفتر جيب");
    inventory.ReceiveStock("P-101", 12);

    RequireThrows<ArgumentOutOfRangeException>(() => inventory.RemoveStock("P-101", 0));
    RequireThrows<ArgumentOutOfRangeException>(() => inventory.RemoveStock("P-101", -1));
    RequireThrows<KeyNotFoundException>(() => inventory.RemoveStock("P-999", 1));
    RequireThrows<InvalidOperationException>(() => inventory.RemoveStock("P-101", 13));
    RequireEqual(12, inventory.GetProduct("P-101").Quantity);
    RequireEqual(7, inventory.RemoveStock(" p-101 ", 5));
    RequireEqual(7, inventory.GetProduct("P-101").Quantity);
    RequireEqual(0, inventory.RemoveStock("P-101", 7));
    RequireEqual(0, inventory.GetProduct("P-101").Quantity);
    RequireThrows<InvalidOperationException>(() => inventory.RemoveStock("P-101", 1));
    RequireEqual(0, inventory.GetProduct("P-101").Quantity);
}

static void SaveAndReloadPreserveInventory()
{
    WithTemporaryFile(path =>
    {
        Inventory inventory = InventoryFile.Load(path);
        RequireEqual(0, inventory.Products.Count);
        inventory.AddProduct("P-101", "دفتر جيب");
        inventory.ReceiveStock("P-101", 12);
        InventoryFile.Save(path, inventory);

        Inventory reopened = InventoryFile.Load(path);
        RequireEqual(new Product("P-101", "دفتر جيب", 12), reopened.GetProduct("P-101"));
        reopened.ReceiveStock("P-101", 3);
        InventoryFile.Save(path, reopened);
        RequireEqual(15, InventoryFile.Load(path).GetProduct("P-101").Quantity);
    });
}

static void LoadRejectsInvalidData()
{
    WithTemporaryFile(path =>
    {
        File.WriteAllText(path, "[");
        RequireThrows<JsonException>(() => InventoryFile.Load(path));

        File.WriteAllText(path, "[null]");
        RequireThrows<JsonException>(() => InventoryFile.Load(path));

        File.WriteAllText(path, """[{"sku":"P-101","name":"دفتر"}]""");
        RequireThrows<JsonException>(() => InventoryFile.Load(path));

        File.WriteAllText(path, """[{"sku":"P-101","name":"دفتر","quantity":"7"}]""");
        RequireThrows<JsonException>(() => InventoryFile.Load(path));

        File.WriteAllText(path, """[{"sku":"P-101","name":"دفتر","quantity":-1}]""");
        RequireThrows<ArgumentOutOfRangeException>(() => InventoryFile.Load(path));

        File.WriteAllText(path, """
            [{"sku":"P-101","name":"دفتر","quantity":1},{"sku":" p-101 ","name":"دفتر ثاني","quantity":5}]
            """);
        RequireThrows<InvalidOperationException>(() => InventoryFile.Load(path));
    });
}

static void WithTemporaryFile(Action<string> check)
{
    DirectoryInfo directory = Directory.CreateTempSubdirectory("nexora-inventory-tests-");
    string path = Path.Combine(directory.FullName, "inventory.json");
    try
    {
        check(path);
    }
    finally
    {
        File.Delete(path);
        directory.Delete();
    }
}

static void RequireEqual<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
    {
        throw new Exception($"القيمة المتوقعة {expected} والقيمة الفعلية {actual}.");
    }
}

static void RequireThrows<TException>(Action action) where TException : Exception
{
    try
    {
        action();
    }
    catch (TException)
    {
        return;
    }

    throw new Exception($"كان المتوقع ظهور الخطأ {typeof(TException).Name}.");
}
