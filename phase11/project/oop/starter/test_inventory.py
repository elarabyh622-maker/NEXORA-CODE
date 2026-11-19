import unittest

from inventory import Inventory, Product


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = Inventory()
        self.product = Product("PEN", 125)
        self.inventory.register(self.product)

    def test_empty_inventory_has_zero_value(self) -> None:
        self.assertEqual(Inventory().total_value(), 0)

    def test_two_inventories_have_independent_quantities(self) -> None:
        another = Inventory()
        another.register(self.product)
        self.inventory.receive("PEN", 3)

        self.assertEqual(self.inventory.quantity("PEN"), 3)
        self.assertEqual(another.quantity("PEN"), 0)

    def test_withdraw_full_stock(self) -> None:
        self.inventory.receive("PEN", 3)
        self.inventory.withdraw("PEN", 3)

        self.assertEqual(self.inventory.quantity("PEN"), 0)
        self.assertEqual(self.inventory.total_value(), 0)

    def test_overdraw_preserves_quantity_and_value(self) -> None:
        self.inventory.receive("PEN", 3)
        with self.assertRaises(ValueError):
            self.inventory.withdraw("PEN", 4)

        self.assertEqual(self.inventory.quantity("PEN"), 3)
        self.assertEqual(self.inventory.total_value(), 375)

    def test_invalid_amount_preserves_quantity(self) -> None:
        self.inventory.receive("PEN", 3)
        for amount in (0, -1, True, "2", 2.0):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.inventory.withdraw("PEN", amount)
                with self.assertRaises(ValueError):
                    self.inventory.receive("PEN", amount)
                self.assertEqual(self.inventory.quantity("PEN"), 3)

    def test_duplicate_and_unknown_sku(self) -> None:
        self.inventory.receive("PEN", 2)
        with self.assertRaises(ValueError):
            self.inventory.register(Product("PEN", 90))
        with self.assertRaises(KeyError):
            self.inventory.receive("pen", 1)
        self.assertEqual(self.inventory.total_value(), 250)

    def test_sums_lines_in_integer_minor_units(self) -> None:
        self.inventory.register(Product("NOTE", 360))
        self.inventory.register(Product("SAMPLE", 0))
        self.inventory.receive("PEN", 2)
        self.inventory.receive("NOTE", 3)
        self.inventory.receive("SAMPLE", 4)

        self.assertEqual(self.inventory.quantity("SAMPLE"), 4)
        self.assertEqual(self.inventory.total_value(), 1330)

    def test_product_validates_price_and_sku(self) -> None:
        for sku, price in (("", 1), (" PEN ", 1), ("PEN", -1), ("PEN", True), ("PEN", 1.0)):
            with self.subTest(sku=sku, price=price):
                with self.assertRaises(ValueError):
                    Product(sku, price)
