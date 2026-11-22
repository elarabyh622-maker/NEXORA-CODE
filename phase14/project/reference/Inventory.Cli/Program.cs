using System.Globalization;
using System.Text;
using System.Text.Json;
using Nexora.Inventory;

Console.OutputEncoding = Encoding.UTF8;

try
{
    return Run(args);
}
catch (NotImplementedException)
{
    Console.Error.WriteLine("أكمل مهمة صرف الكمية في RemoveStock الأول.");
    return 1;
}
catch (OverflowException)
{
    Console.Error.WriteLine("الرصيد بعد الإضافة أكبر من الحد الأقصى لنوع int.");
    return 1;
}
catch (Exception error) when (error is ArgumentException or FormatException or InvalidOperationException
    or KeyNotFoundException or JsonException or IOException or UnauthorizedAccessException)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static int Run(string[] command)
{
    string path = Path.Combine(".local", "inventory.json");
    if (command is ["--file", var file, .. var remaining])
    {
        path = file;
        command = remaining;
    }

    switch (command)
    {
        case [] or ["--help"]:
            ShowUsage(Console.Out);
            return 0;
        case ["list"]:
            Inventory inventory = InventoryFile.Load(path);
            if (inventory.Products.Count == 0)
            {
                Console.WriteLine("المخزون فارغ.");
            }

            foreach (Product product in inventory.Products)
            {
                Console.WriteLine($"{product.Sku}\t{product.Name}\t{product.Quantity}");
            }

            return 0;
        case ["add", var sku, var name]:
            Change(path, inventory => inventory.AddProduct(sku, name));
            return 0;
        case ["receive", var sku, var quantity]:
            int received = ParseQuantity(quantity);
            Change(path, inventory => inventory.ReceiveStock(sku, received));
            return 0;
        case ["issue", var sku, var quantity]:
            int issued = ParseQuantity(quantity);
            Change(path, inventory => inventory.RemoveStock(sku, issued));
            return 0;
        default:
            ShowUsage(Console.Error);
            return 1;
    }
}

static int ParseQuantity(string text)
{
    if (!int.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out int quantity))
    {
        throw new FormatException("اكتب الكمية كعدد صحيح موجب باستخدام الأرقام 0 إلى 9.");
    }

    return quantity;
}

static void Change(string path, Action<Inventory> applyMovement)
{
    string destination = Path.GetFullPath(path);
    Directory.CreateDirectory(Path.GetDirectoryName(destination)!);

    // احتفظ بالقفل من القراءة لحد الحفظ لمنع كاتبين من تعديل نفس الرصيد في نفس الوقت.
    using FileStream writeLock = File.Open(destination + ".lock", FileMode.OpenOrCreate, FileAccess.Write, FileShare.None);
    Inventory inventory = InventoryFile.Load(destination);
    applyMovement(inventory);
    InventoryFile.Save(destination, inventory);
    Console.WriteLine("تم حفظ المخزون.");
}

static void ShowUsage(TextWriter output)
{
    output.WriteLine("dotnet run --project Inventory.Cli -- [--file <path>] list");
    output.WriteLine("dotnet run --project Inventory.Cli -- [--file <path>] add <sku> <name>");
    output.WriteLine("dotnet run --project Inventory.Cli -- [--file <path>] receive <sku> <quantity>");
    output.WriteLine("dotnet run --project Inventory.Cli -- [--file <path>] issue <sku> <quantity>");
}
