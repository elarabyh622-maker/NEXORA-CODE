"""Create a reproducible report from the supplied fictional store data."""

import argparse
import csv
from html import escape
import json
from pathlib import Path
import sqlite3

from clean import clean_sales
from metrics import render_monthly_chart, summarize


HERE = Path(__file__).resolve().parent
MONTHLY_COLUMNS = (
    "month", "orders", "revenue_piastres", "previous_month",
    "previous_revenue_piastres", "change_piastres",
)


def monthly_comparison(cleaned):
    """Load validated rows once and use SQLite to calculate the report."""
    database = sqlite3.connect(":memory:")
    try:
        database.row_factory = sqlite3.Row
        database.execute("""
            CREATE TABLE sales (
                sale_id TEXT PRIMARY KEY NOT NULL, sold_on TEXT NOT NULL,
                sku TEXT NOT NULL, category TEXT NOT NULL,
                quantity INTEGER NOT NULL, unit_price_piastres INTEGER NOT NULL,
                revenue_piastres INTEGER NOT NULL
            )
        """)
        columns = "sale_id sold_on sku category quantity unit_price_piastres revenue_piastres".split()
        database.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?, ?)",
                             cleaned[columns].itertuples(index=False, name=None))
        database.executescript((HERE / "queries.sql").read_text(encoding="utf-8"))
        query = "SELECT " + ", ".join(MONTHLY_COLUMNS) + " FROM monthly_comparison ORDER BY month"
        return [dict(row) for row in database.execute(query)]
    finally:
        database.close()


def money(amount):
    if amount is None:
        return "—"
    whole, fraction = divmod(abs(amount), 100)
    sign = "−" if amount < 0 else ""
    return f"{sign}{whole:,}.{fraction:02d} ج.م."


def write_dashboard(path, audit, statistics, monthly):
    rows = []
    for row in monthly:
        month = escape(row["month"])
        previous = escape(row["previous_month"] or "—")
        rows.append(f"<tr><th scope='row'><bdi>{month}</bdi></th>"
                    f"<td>{row['orders']}</td><td><bdi>{money(row['revenue_piastres'])}</bdi></td>"
                    f"<td><bdi>{previous}</bdi></td><td><bdi>{money(row['change_piastres'])}</bdi></td></tr>")
    table_body = "\n".join(rows) or '<tr><td colspan="5">لا توجد مبيعات مقبولة.</td></tr>'
    page = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>تقرير مبيعات المتجر التدريبي</title>
<style>
body {{font: 1rem/1.65 system-ui,sans-serif; color:#14362c; background:#f5f8f4; margin:0}}
main {{max-width:60rem; padding:1.25rem; margin:auto}}
section {{background:white; border:1px solid #c4d7cf; padding:1rem; margin-block:1rem; border-radius:.75rem}}
h1,h2 {{line-height:1.3}} dl {{display:grid; grid-template-columns:auto 1fr; gap:.35rem 1rem}}
dd {{margin:0}} img {{width:100%; height:auto}} .scroll {{overflow:auto}}
table {{border-collapse:collapse; width:100%; text-align:start}} th,td {{padding:.55rem; border-bottom:1px solid #c4d7cf}}
caption {{text-align:start; margin-block-end:.5rem}}
</style></head><body><main>
<h1>تقرير مبيعات المتجر التدريبي</h1>
<p>بيانات خيالية. كل سطر مقبول يمثل عملية بيع واحدة. الإيراد حاصل ضرب الكمية في سعر الوحدة قبل أي تكاليف.</p>
<section><h2>ملخص البيانات</h2><dl>
<dt>صفوف المصدر</dt><dd>{audit['raw_rows']}</dd><dt>مبيعات مقبولة</dt><dd>{audit['accepted']}</dd>
<dt>نسخ مكررة محذوفة</dt><dd>{audit['duplicates']}</dd><dt>صفوف مرفوضة</dt><dd>{audit['rejected']}</dd>
<dt>إجمالي الإيراد</dt><dd><bdi>{money(statistics['total_piastres'])}</bdi></dd>
</dl></section>
<section><h2>الإيراد حسب الشهر</h2>
<img src="monthly.png" alt="رسم أعمدة للإيراد الشهري. القيم الكاملة متاحة في الجدول التالي.">
<div class="scroll"><table><caption>المقارنة مع أقرب شهر سابق مُمثل في البيانات</caption>
<thead><tr><th scope="col">الشهر</th><th scope="col">عدد العمليات</th><th scope="col">الإيراد</th>
<th scope="col">الشهر السابق المُمثل</th><th scope="col">الفرق في الإيراد</th></tr></thead>
<tbody>{table_body}</tbody></table></div>
<p>غياب شهر من المصدر لا يكفي لاستنتاج أن إيراده صفر. يصف التقرير السجلات المقبولة فقط ولا يفسر أسباب التغير.</p>
</section></main></body></html>"""
    path.write_text(page, encoding="utf-8")


def build_report(data_dir: Path, output: Path) -> None:
    cleaned, audit = clean_sales(data_dir)
    monthly = monthly_comparison(cleaned)
    statistics = summarize(cleaned["revenue_piastres"].astype(int).tolist())
    if (sum(row["revenue_piastres"] for row in monthly) != statistics["total_piastres"]
            or sum(row["orders"] for row in monthly) != statistics["count"]
            or audit["raw_rows"] != audit["accepted"] + audit["duplicates"] + audit["rejected"]):
        raise ValueError("فشل التحقق من مطابقة عدد الصفوف أو الإيرادات.")

    output.mkdir(exist_ok=False)
    cleaned.to_csv(output / "cleaned_sales.csv", index=False, encoding="utf-8")
    with (output / "monthly.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MONTHLY_COLUMNS)
        writer.writeheader()
        writer.writerows(monthly)
    (output / "summary.json").write_text(
        json.dumps({"quality": audit, "statistics": statistics}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    render_monthly_chart([(row["month"], row["revenue_piastres"]) for row in monthly], output / "monthly.png")
    write_dashboard(output / "index.html", audit, statistics, monthly)


def main() -> None:
    parser = argparse.ArgumentParser(description="أنشئ تقرير مبيعات تدريبي من ملفات CSV.")
    parser.add_argument("--data-dir", type=Path, default=HERE / "data", help="مجلد بيانات التدريب")
    parser.add_argument("--out-dir", type=Path, default=Path("output"), help="اسم مجلد إخراج جديد")
    args = parser.parse_args()
    try:
        build_report(args.data_dir, args.out_dir)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"تعذر إنشاء التقرير. {error}\n")
    print(args.out_dir / "index.html")


if __name__ == "__main__":
    main()
