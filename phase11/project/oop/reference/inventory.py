from dataclasses import dataclass


def _check_amount(amount: int) -> None:
    if type(amount) is not int or amount <= 0:
        raise ValueError("Amount must be a positive integer")


@dataclass(frozen=True)
class Product:
    sku: str
    unit_price: int

    def __post_init__(self) -> None:
        if type(self.sku) is not str or not self.sku or self.sku != self.sku.strip():
            raise ValueError("SKU must be nonempty text without surrounding whitespace")
        if type(self.unit_price) is not int or self.unit_price < 0:
            raise ValueError("Unit price must be a nonnegative integer")


class StockLine:
    def __init__(self, product: Product) -> None:
        self._product = product
        self._quantity = 0

    @property
    def quantity(self) -> int:
        return self._quantity

    @property
    def value(self) -> int:
        return self._quantity * self._product.unit_price

    def receive(self, amount: int) -> None:
        _check_amount(amount)
        self._quantity += amount

    def withdraw(self, amount: int) -> None:
        _check_amount(amount)
        if amount > self._quantity:
            raise ValueError("Not enough stock")
        self._quantity -= amount


class Inventory:
    def __init__(self) -> None:
        self._lines: dict[str, StockLine] = {}

    def register(self, product: Product) -> None:
        if not isinstance(product, Product):
            raise ValueError("Expected a Product")
        if product.sku in self._lines:
            raise ValueError("SKU already registered")
        self._lines[product.sku] = StockLine(product)

    def receive(self, sku: str, amount: int) -> None:
        self._lines[sku].receive(amount)

    def withdraw(self, sku: str, amount: int) -> None:
        self._lines[sku].withdraw(amount)

    def quantity(self, sku: str) -> int:
        return self._lines[sku].quantity

    def total_value(self) -> int:
        return sum(line.value for line in self._lines.values())
