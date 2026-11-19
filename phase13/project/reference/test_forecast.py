import csv
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evaluate import evaluate_groups, summarize_errors
from forecast import HERE, build_report, choose_model, next_features
from models import baseline_predict, fit_model, model_predict
from prepare import load_weeks, make_examples, split_examples


SOURCE = HERE / "data/weekly_sales.csv"


class ForecastTests(unittest.TestCase):
    def test_target_week_outcome_is_not_an_input(self):
        weeks = load_weeks(SOURCE)
        modified = list(weeks)
        modified[4] = replace(modified[4], units_sold=999)
        old, new = make_examples(weeks)[0], make_examples(modified)[0]
        self.assertEqual(old["last_week_units"], weeks[3].units_sold)
        self.assertEqual(old["mean_last_4"], sum(week.units_sold for week in weeks[:4]) / 4)
        self.assertNotEqual(old.pop("actual_units"), new.pop("actual_units"))
        self.assertEqual(new, old)
        self.assertNotIn("actual_units", next_features(weeks, 1))

    def test_chronological_disjoint_split(self):
        rows = make_examples(load_weeks(SOURCE))
        train, validation, test = split_examples(rows)
        self.assertEqual((len(train), len(validation), len(test)), (47, 10, 11))
        self.assertEqual(train + validation + test, rows)
        self.assertLess(train[-1]["week_start"], validation[0]["week_start"])
        self.assertLess(validation[-1]["week_start"], test[0]["week_start"])

    def test_model_works_without_target_at_prediction_time(self):
        train, validation, _ = split_examples(make_examples(load_weeks(SOURCE)))
        model = fit_model(train)
        without_target = [{key: value for key, value in row.items() if key != "actual_units"} for row in validation]
        self.assertEqual(model_predict(model, validation), model_predict(model, without_target))
        self.assertEqual(baseline_predict(validation), baseline_predict(without_target))
        self.assertTrue(all(value >= 0 for value in model_predict(model, without_target)))

    def test_choose_only_lower_error_on_validation(self):
        self.assertEqual(choose_model(8, 4), "linear")
        self.assertEqual(choose_model(4, 8), "baseline")
        self.assertEqual(choose_model(4, 4), "baseline")

    def test_mean_absolute_error_and_signed_bias(self):
        result = summarize_errors([5, 10], [7, 8])
        self.assertEqual(result, {"count": 2, "mae": 2, "bias": 0})
        groups = evaluate_groups([{"promotion": 1, "actual_units": 5}], [7])
        self.assertEqual(groups["normal"], {"count": 0, "mae": None, "bias": None})
        self.assertEqual(groups["promotion"], {"count": 1, "mae": 2, "bias": 2})
        with self.assertRaises(ValueError):
            summarize_errors([1], [])

    def test_exports_untouched_test_weeks_and_next_week(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            summary = build_report(SOURCE, output, promotion=1)
            self.assertEqual(summary["split"], {"train": 47, "validation": 10, "test": 11})
            self.assertEqual(sum(row["count"] for row in summary["test_groups"].values()), 11)
            self.assertEqual(summary["next_week"]["promotion"], 1)
            with (output / "predictions.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            _, _, test = split_examples(make_examples(load_weeks(SOURCE)))
            self.assertEqual([row["week_start"] for row in rows], [row["week_start"] for row in test])
            self.assertGreater(summary["next_week"]["week_start"], rows[-1]["week_start"])
            chosen = summary["selected"]
            self.assertEqual([row["selected_units"] for row in rows], [row[f"{chosen}_units"] for row in rows])
            self.assertEqual((output / "predictions.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn("البيانات خيالية", (output / "report.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                build_report(SOURCE, output)


if __name__ == "__main__":
    unittest.main()
