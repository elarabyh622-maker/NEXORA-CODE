"""Read the fictional weekly sales data and build chronological examples."""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re


@dataclass(frozen=True)
class Week:
    week_start: date
    units_sold: int
    promotion: int


def _iso_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("expected a date in YYYY-MM-DD format")
    return date.fromisoformat(value)


def load_weeks(csv_path: Path) -> list[Week]:
    """Read a UTF-8 CSV and return one row per Monday, sorted by date."""
    weeks = []
    with csv_path.open(encoding="utf-8", newline="") as source:
        rows = csv.reader(source, strict=True)
        try:
            if next(rows, None) != ["week_start", "units_sold", "promotion"]:
                raise ValueError("expected headers week_start,units_sold,promotion")
            for line_number, columns in enumerate(rows, start=2):
                try:
                    week_text, units_text, promotion_text = columns
                    week_start = _iso_date(week_text)
                    if (week_start.weekday() != 0 or not re.fullmatch(r"[0-9]{1,7}", units_text)
                            or promotion_text not in {"0", "1"}):
                        raise ValueError("invalid weekly sales or promotion")
                    units = int(units_text)
                    if units > 1_000_000:
                        raise ValueError("units_sold exceeds the file contract")
                except ValueError as error:
                    raise ValueError(f"invalid sales record {line_number}") from error
                weeks.append(Week(week_start, units, int(promotion_text)))
        except csv.Error as error:
            raise ValueError("invalid CSV syntax") from error

    weeks.sort(key=lambda week: week.week_start)
    for previous, current in zip(weeks, weeks[1:]):
        if (current.week_start - previous.week_start).days != 7:
            raise ValueError("weekly sales must contain one record for each consecutive Monday")
    return weeks


def make_examples(weeks: list[Week]) -> list[dict]:
    """Use four previous weeks to predict the sales of each target week."""
    examples = []
    for index in range(4, len(weeks)):
        previous = weeks[index - 4:index]
        target = weeks[index]
        examples.append({
            "week_start": target.week_start.isoformat(),
            "actual_units": target.units_sold,
            "last_week_units": previous[-1].units_sold,
            "mean_last_4": sum(week.units_sold for week in previous) / 4,
            "promotion": target.promotion,
        })
    return examples


def split_examples(examples: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return training, validation, and holdout examples in time order."""
    count = len(examples)
    if count < 20:
        raise ValueError("at least 20 prediction examples are needed")
    dates = [_iso_date(row["week_start"]) for row in examples]
    if any(previous >= current for previous, current in zip(dates, dates[1:])):
        raise ValueError("prediction dates must be strictly increasing")

    validation_start = count * 70 // 100
    test_start = count * 85 // 100
    return examples[:validation_start], examples[validation_start:test_start], examples[test_start:]
