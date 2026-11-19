"""Train and check a weekly sales forecast using fictional data."""

import argparse
import csv
from datetime import timedelta
import json
from pathlib import Path
from statistics import mean

from evaluate import evaluate_groups, summarize_errors
from models import baseline_predict, fit_model, model_predict
from prepare import load_weeks, make_examples, split_examples


HERE = Path(__file__).resolve().parent


def choose_model(baseline_mae: float, linear_mae: float) -> str:
    """Select on validation only, keeping the baseline on a tie."""
    return "linear" if linear_mae < baseline_mae else "baseline"


def compare(rows, model):
    actual = [row["actual_units"] for row in rows]
    predictions = {"baseline": baseline_predict(rows), "linear": model_predict(model, rows)}
    metrics = {name: summarize_errors(actual, values) for name, values in predictions.items()}
    return metrics, predictions


def next_features(weeks, promotion: int) -> dict:
    if promotion not in (0, 1):
        raise ValueError("مؤشر العرض يجب أن يكون 0 أو 1.")
    return {
        "week_start": (weeks[-1].week_start + timedelta(weeks=1)).isoformat(),
        "last_week_units": weeks[-1].units_sold,
        "mean_last_4": mean(week.units_sold for week in weeks[-4:]),
        "promotion": promotion,
    }


def render_test_chart(path, dates, actual, predicted):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(9, 4), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.plot(dates, actual, "o-", color="#123d31", label="Actual")
    axes.plot(dates, predicted, "s--", color="#996231", label="Selected forecast")
    axes.set_title("Held-out weeks")
    axes.set_ylabel("Units sold")
    axes.set_xlabel("Week starting")
    axes.tick_params(axis="x", labelrotation=35)
    axes.legend()
    axes.grid(axis="y", alpha=0.25)
    figure.savefig(path, dpi=150)


def write_report(path, summary):
    names = {"baseline": "متوسط الأسابيع الأربعة", "linear": "الانحدار الخطي"}
    captions = {"normal": "بدون عرض", "promotion": "مع عرض"}
    selected = summary["selected"]
    result = summary["test"][selected]
    lines = [
        "# تقرير توقع مبيعات المتجر التدريبي",
        "",
        f"اختارت مرحلة التحقق **{names[selected]}**. عند التعادل نحتفظ بمتوسط الأسابيع الأربعة.",
        f"بلغ متوسط الخطأ المطلق في الاختبار {result['mae']:.2f} وحدة عبر {result['count']} أسبوعًا.",
        f"الانحياز المحسوب (التوقع ناقص الفعلي) يساوي {result['bias']:+.2f} وحدة.",
        "",
        "الاختبار على أسابيع أحدث من أسابيع التحقق. حسبنا كل توقع بالبيانات التي كانت متاحة قبل أسبوعه.",
        "ظل الاختيار ثابتًا بعد رؤية نتائج الاختبار.",
        "",
        "![المبيعات الفعلية والتوقع في أسابيع الاختبار](predictions.png)",
        "",
        "| مجموعة الاختبار | عدد الأسابيع | متوسط الخطأ المطلق |",
        "| --- | ---: | ---: |",
    ]
    for group, metrics in summary["test_groups"].items():
        error = "—" if metrics["mae"] is None else f"{metrics['mae']:.2f}"
        lines.append(f"| {captions[group]} | {metrics['count']} | {error} |")
    next_week = summary["next_week"]
    lines += [
        "",
        f"التوقع لأسبوع {next_week['week_start']} هو {next_week['predicted_units']:.1f} وحدة "
        f"في وضع «{captions['promotion' if next_week['promotion'] else 'normal']}».",
        "العدد تقدير تقريبي. راجع حجم كل مجموعة قبل مقارنة الأخطاء.",
        "البيانات خيالية ومحدودة. لا يبيّن هذا التقرير أثر العروض سببيًا ولا يعمم النتيجة على متاجر أخرى.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(source: Path, output: Path, promotion: int = 0) -> dict:
    weeks = load_weeks(source)
    train, validation, test = split_examples(make_examples(weeks))
    model = fit_model(train)
    validation_metrics, _ = compare(validation, model)
    selected = choose_model(validation_metrics["baseline"]["mae"], validation_metrics["linear"]["mae"])
    test_metrics, test_predictions = compare(test, model)
    chosen_predictions = test_predictions[selected]

    next_row = next_features(weeks, promotion)
    forecast = model_predict(model, [next_row]) if selected == "linear" else baseline_predict([next_row])
    summary = {
        "split": {"train": len(train), "validation": len(validation), "test": len(test)},
        "validation": validation_metrics,
        "selected": selected,
        "test": test_metrics,
        "test_groups": evaluate_groups(test, chosen_predictions),
        "next_week": {
            "week_start": next_row["week_start"], "promotion": promotion, "predicted_units": forecast[0],
        },
    }

    output.mkdir(exist_ok=False)
    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("week_start", "actual_units", "baseline_units", "linear_units", "selected_units", "signed_error"))
        for i, row in enumerate(test):
            writer.writerow((row["week_start"], row["actual_units"], test_predictions["baseline"][i],
                             test_predictions["linear"][i], chosen_predictions[i],
                             chosen_predictions[i] - row["actual_units"]))
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8",
    )
    render_test_chart(output / "predictions.png", [row["week_start"] for row in test],
                      [row["actual_units"] for row in test], chosen_predictions)
    write_report(output / "report.md", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="جرّب توقع عدد وحدات المبيعات الأسبوعية.")
    parser.add_argument("--data", type=Path, default=HERE / "data/weekly_sales.csv", help="بيانات الأسابيع")
    parser.add_argument("--out-dir", type=Path, default=Path("output"), help="مجلد إخراج جديد")
    parser.add_argument("--next-promotion", type=int, choices=(0, 1), default=0, help="هل العرض مخطط للأسبوع القادم؟")
    args = parser.parse_args()
    try:
        build_report(args.data, args.out_dir, args.next_promotion)
    except (OSError, ValueError) as error:
        parser.exit(1, f"تعذر إنشاء التقرير. {error}\n")
    print(args.out_dir / "report.md")


if __name__ == "__main__":
    main()
