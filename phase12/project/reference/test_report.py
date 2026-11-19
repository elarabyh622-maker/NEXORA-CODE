import csv
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from clean import clean_sales
from metrics import summarize
from sales_report import HERE, build_report, monthly_comparison


class SalesReportTests(unittest.TestCase):
    def test_cleanup_reconciles_and_joins(self):
        clean, audit = clean_sales(HERE / "data")
        self.assertEqual(audit, {"raw_rows": 11, "accepted": 5, "duplicates": 1, "rejected": 5})
        self.assertEqual(clean["sale_id"].tolist(), ["S001", "S002", "S003", "S004", "S005"])
        self.assertEqual(clean["category"].tolist(), ["stationery", "stationery", "stationery", "accessories", "stationery"])
        self.assertEqual(clean["revenue_piastres"].tolist(), [25000, 5000, 36000, 40000, 0])

    def test_duplicate_product_keys_are_rejected(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            shutil.copyfile(HERE / "data/sales.csv", data / "sales.csv")
            (data / "products.csv").write_text("sku,category\nPEN,one\n PEN ,two\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                clean_sales(data)

    def test_empty_statistics(self):
        self.assertEqual(summarize([]), {
            "count": 0, "total_piastres": 0, "mean_piastres": None,
            "median_piastres": None, "range_piastres": None,
        })

    def test_previous_observed_month_revenue(self):
        clean, _ = clean_sales(HERE / "data")
        monthly = monthly_comparison(clean)
        self.assertEqual([row["month"] for row in monthly], ["2026-01", "2026-02", "2026-04"])
        self.assertEqual([row["orders"] for row in monthly], [2, 1, 2])
        self.assertEqual([row["revenue_piastres"] for row in monthly], [30000, 36000, 40000])
        self.assertEqual([row["previous_month"] for row in monthly], [None, "2026-01", "2026-02"])
        self.assertEqual([row["previous_revenue_piastres"] for row in monthly], [None, 30000, 36000])
        self.assertEqual([row["change_piastres"] for row in monthly], [None, 6000, 4000])
        zero_prior = clean.iloc[[1, 2]].copy()
        zero_prior.loc[zero_prior.index[0], "revenue_piastres"] = 0
        rows = monthly_comparison(zero_prior)
        self.assertEqual(rows[1]["previous_revenue_piastres"], 0)
        self.assertEqual(rows[1]["change_piastres"], 36000)

    def test_report_files_and_no_overwrite(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            build_report(HERE / "data", output)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["statistics"], {
                "count": 5, "total_piastres": 106000, "mean_piastres": 21200,
                "median_piastres": 25000, "range_piastres": 40000,
            })
            self.assertEqual((output / "monthly.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn('lang="ar" dir="rtl"', (output / "index.html").read_text(encoding="utf-8"))
            with (output / "monthly.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 3)
            with self.assertRaises(FileExistsError):
                build_report(HERE / "data", output)


if __name__ == "__main__":
    unittest.main()
