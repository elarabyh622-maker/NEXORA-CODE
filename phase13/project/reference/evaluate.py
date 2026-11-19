"""مقاييس التنبؤ بمبيعات الأسابيع، بوحدة القطع المبيعة."""

from math import isfinite
from statistics import mean


def summarize_errors(actual: list[int], predicted: list[float]) -> dict[str, int | float | None]:
    """احسب متوسط الخطأ المطلق والانحياز، بإشارة التوقع ناقص الفعلي."""
    if len(actual) != len(predicted):
        raise ValueError("كل قيمة فعلية تحتاج توقعًا واحدًا")
    if not actual:
        return {"count": 0, "mae": None, "bias": None}

    errors = []
    for observed, estimate in zip(actual, predicted):
        try:
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
                   for value in (observed, estimate)):
                raise ValueError("قيم المبيعات والتوقعات يجب أن تكون أعدادًا منتهية")
            error = estimate - observed
            if not isfinite(error):
                raise ValueError("الفرق بين التوقع والفعلي خارج النطاق العددي")
        except OverflowError as exc:
            raise ValueError("قيمة خارج النطاق العددي") from exc
        errors.append(error)

    return {"count": len(errors), "mae": mean(abs(error) for error in errors), "bias": mean(errors)}


def evaluate_groups(rows: list[dict], predicted: list[float]) -> dict[str, dict[str, int | float | None]]:
    """لخّص الخطأ لكل من الأسابيع العادية وأسابيع العرض المخطط له."""
    if len(rows) != len(predicted):
        raise ValueError("كل أسبوع يحتاج توقعًا واحدًا")

    groups = {"normal": ([], []), "promotion": ([], [])}
    for row, estimate in zip(rows, predicted):
        promotion = row["promotion"]
        if type(promotion) is not int or promotion not in (0, 1):
            raise ValueError("استخدم 0 أو 1 لمؤشر العرض المخطط")
        name = "promotion" if promotion == 1 else "normal"
        actual_group, predicted_group = groups[name]
        actual_group.append(row["actual_units"])
        predicted_group.append(estimate)

    return {name: summarize_errors(actual, estimates) for name, (actual, estimates) in groups.items()}
