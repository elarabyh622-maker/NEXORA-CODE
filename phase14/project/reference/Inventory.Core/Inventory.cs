namespace Nexora.Inventory;

public sealed class Inventory
{
    private readonly Dictionary<string, Product> products = new(StringComparer.OrdinalIgnoreCase);

    public IReadOnlyList<Product> Products => products.Values.OrderBy(product => product.Sku, StringComparer.Ordinal).ToArray();

    public void AddProduct(string sku, string name)
    {
        AddProduct(new Product(sku, name, 0));
    }

    public int ReceiveStock(string sku, int quantity)
    {
        ValidateMovementQuantity(quantity);
        Product product = GetProduct(sku);
        int newQuantity = checked(product.Quantity + quantity);
        products[product.Sku] = product with { Quantity = newQuantity };
        return newQuantity;
    }

    public int RemoveStock(string sku, int quantity)
    {
        ValidateMovementQuantity(quantity);
        Product product = GetProduct(sku);
        if (quantity > product.Quantity)
        {
            throw new InvalidOperationException("الكمية المطلوبة أكبر من الرصيد المتاح.");
        }

        int remaining = product.Quantity - quantity;
        products[product.Sku] = product with { Quantity = remaining };
        return remaining;
    }

    public Product GetProduct(string sku)
    {
        string normalizedSku = NormalizeSku(sku);
        if (products.TryGetValue(normalizedSku, out Product? product))
        {
            return product;
        }

        throw new KeyNotFoundException($"كود الصنف {normalizedSku} غير موجود.");
    }

    internal void AddProduct(Product product)
    {
        string sku = NormalizeSku(product.Sku);
        if (string.IsNullOrWhiteSpace(product.Name))
        {
            throw new ArgumentException("اكتب اسم الصنف.");
        }

        if (product.Quantity < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(product), "رصيد الصنف لازم يبدأ من صفر أو أكثر.");
        }

        if (!products.TryAdd(sku, new Product(sku, product.Name.Trim(), product.Quantity)))
        {
            throw new InvalidOperationException($"كود الصنف {sku} مستخدم بالفعل.");
        }
    }

    private static string NormalizeSku(string sku)
    {
        if (string.IsNullOrWhiteSpace(sku))
        {
            throw new ArgumentException("اكتب كود الصنف.");
        }

        return sku.Trim().ToUpperInvariant();
    }

    private static void ValidateMovementQuantity(int quantity)
    {
        if (quantity <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(quantity), "كمية الحركة لازم تكون أكبر من صفر.");
        }
    }
}
