from inventory import Inventory, Product


def main() -> None:
    inventory = Inventory()
    inventory.register(Product("PEN", 125))
    inventory.register(Product("NOTE", 360))
    inventory.receive("PEN", 5)
    inventory.receive("NOTE", 2)
    inventory.withdraw("PEN", 5)

    for sku in ("PEN", "NOTE"):
        print(f"{sku}: {inventory.quantity(sku)}")
    print(f"total_minor_units: {inventory.total_value()}")


if __name__ == "__main__":
    main()
