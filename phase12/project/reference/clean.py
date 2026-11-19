"""Validate and enrich sales from the synthetic CSV exports."""

from datetime import date
from pathlib import Path
import re

import pandas as pd


SALES_COLUMNS = ["sale_id", "sold_on", "sku", "quantity", "unit_price_piastres"]
PRODUCT_COLUMNS = ["sku", "category"]
OUTPUT_COLUMNS = [
    "sale_id", "sold_on", "sku", "category", "quantity",
    "unit_price_piastres", "revenue_piastres",
]
MAX_AMOUNT = 1_000_000


def _read_fields(path: Path, columns: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype="string", keep_default_na=False, usecols=columns)
    return frame[columns].apply(lambda column: column.str.strip())


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _parse_amount(values: pd.Series) -> pd.Series:
    # Strip leading zeros before checking length, so the integer cast stays bounded.
    digits = values.str.lstrip("0").replace("", "0")
    valid = values.str.fullmatch(r"[0-9]+") & digits.str.len().le(len(str(MAX_AMOUNT)))
    numbers = digits.where(valid).astype("Int64")
    return numbers.where(numbers.le(MAX_AMOUNT))


def clean_sales(data_dir: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    sales = _read_fields(data_dir / "sales.csv", SALES_COLUMNS)
    products = _read_fields(data_dir / "products.csv", PRODUCT_COLUMNS)
    if products["sku"].duplicated().any():
        raise ValueError("products.csv must contain unique SKU keys")

    raw_rows = len(sales)
    unique_sales = sales.drop_duplicates()
    duplicates = raw_rows - len(unique_sales)
    quantity = _parse_amount(unique_sales["quantity"])
    price = _parse_amount(unique_sales["unit_price_piastres"])

    accepted = (
        unique_sales["sale_id"].ne("")
        & ~unique_sales["sale_id"].duplicated(keep=False)
        & unique_sales["sold_on"].map(_valid_date).astype(bool)
        & unique_sales["sku"].ne("")
        & unique_sales["sku"].isin(products["sku"])
        & quantity.gt(0)
        & price.notna()
    )
    cleaned = unique_sales.loc[accepted].copy()
    cleaned["quantity"] = quantity.loc[accepted].astype("int64")
    cleaned["unit_price_piastres"] = price.loc[accepted].astype("int64")
    cleaned = cleaned.merge(products, on="sku", how="left", validate="many_to_one")
    cleaned["revenue_piastres"] = cleaned["quantity"] * cleaned["unit_price_piastres"]
    cleaned = cleaned[OUTPUT_COLUMNS].sort_values(["sold_on", "sale_id"], ignore_index=True)

    return cleaned, {
        "raw_rows": raw_rows,
        "accepted": len(cleaned),
        "duplicates": duplicates,
        "rejected": len(unique_sales) - len(cleaned),
    }
