"""Run the expense tracker's command-line contract against a compiled executable."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ExpensesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "my expenses.tsv"

    def run_command(self, *arguments, success=True):
        result = subprocess.run(
            [self.executable, self.data.name, *arguments],
            cwd=self.data.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())
        return result

    def test_empty_list_does_not_create_data(self):
        self.assertEqual(self.run_command("list").stdout, "")
        self.assertFalse(self.data.exists())

    def test_add_persists_and_list_keeps_insertion_order(self):
        for category, amount in (("transport", "1200"), ("food", "3250"), ("food", "750")):
            self.assertEqual(self.run_command("add", category, amount).stdout, "")
        expected = "transport\t1200\nfood\t3250\nfood\t750\n"
        self.assertEqual(self.run_command("list").stdout, expected)
        self.assertEqual(self.data.read_bytes(), expected.encode("ascii"))

    def test_accepts_crlf_and_last_line_without_newline(self):
        self.data.write_bytes(b"food\t100\r\ntransport\t200")
        self.assertEqual(self.run_command("list").stdout, "food\t100\ntransport\t200\n")
        self.run_command("add", "home-office", "300")
        self.assertEqual(
            self.run_command("list").stdout, "food\t100\ntransport\t200\nhome-office\t300\n"
        )

    def test_invalid_arguments_do_not_create_or_change_data(self):
        self.run_command("add", "food", "+100", success=False)
        self.assertFalse(self.data.exists())
        self.run_command("add", "food", "100")
        original = self.data.read_bytes()
        for arguments in (
            ("add", "Food", "100"),
            ("add", "-food", "100"),
            ("add", "food-", "100"),
            ("add", "food drink", "100"),
            ("add", "food2", "100"),
            ("add", "a" * 25, "100"),
            ("add", "total", "100"),
            ("add", "food", ""),
            ("add", "food", "0"),
            ("add", "food", "-1"),
            ("add", "food", "1.25"),
            ("add", "food", "100 "),
            ("add", "food", " 100"),
            ("add", "food", "1x"),
            ("add", "food", "1000000001"),
            ("add", "food", "18446744073709551616"),
            ("add", "food"),
            ("list", "extra"),
            ("missing-command",),
        ):
            with self.subTest(arguments=arguments):
                self.run_command(*arguments, success=False)
                self.assertEqual(self.data.read_bytes(), original)

    def test_corrupt_data_rejects_reads_and_writes(self):
        for invalid_row in (
            b"\n",
            b"food,100\n",
            b"food\t\n",
            b"food\t-100\n",
            b"total\t100\n",
            b"food\t100\textra\n",
            b"food\t100\r",
        ):
            with self.subTest(invalid_row=invalid_row):
                original = b"food\t100\n" + invalid_row
                self.data.write_bytes(original)
                for arguments in (("list",), ("summary",), ("add", "food", "100")):
                    result = self.run_command(*arguments, success=False)
                    self.assertIn("line 2", result.stderr)
                    self.assertEqual(self.data.read_bytes(), original)
                self.assertFalse(self.data.with_name(self.data.name + ".pending").exists())

    def test_add_rejects_existing_pending_write(self):
        self.data.write_bytes(b"food\t100\n")
        pending = self.data.with_name(self.data.name + ".pending")
        pending.mkdir()
        self.run_command("add", "food", "50", success=False)
        self.assertEqual(self.data.read_bytes(), b"food\t100\n")
        self.assertTrue(pending.is_dir())

    def test_boundary_rows_protect_existing_data(self):
        original = b"food\t1000000000\n" * 10_000
        self.data.write_bytes(original)
        self.run_command("add", "food", "1", success=False)
        self.assertEqual(self.data.read_bytes(), original)
        self.data.write_bytes(original + b"food\t1\n")
        result = self.run_command("list", success=False)
        self.assertIn("line 10001", result.stderr)

    def test_summary_empty_result(self):
        self.assertEqual(self.run_command("summary").stdout, "total\t0\n")
        self.assertFalse(self.data.exists())

    def test_summary_groups_and_sorts_categories(self):
        original = b"transport\t1200\nfood\t3250\nfood\t750\n"
        self.data.write_bytes(original)
        expected = "food\t4000\ntransport\t1200\ntotal\t5200\n"
        self.assertEqual(self.run_command("summary").stdout, expected)
        self.assertEqual(self.run_command("summary").stdout, expected)
        self.assertEqual(self.data.read_bytes(), original)

    def test_summary_uses_64_bit_totals(self):
        self.data.write_bytes(b"food\t1000000000\n" * 3 + b"home-office\t1000000000\n")
        expected = "food\t3000000000\nhome-office\t1000000000\ntotal\t4000000000\n"
        self.assertEqual(self.run_command("summary").stdout, expected)


    def check_incomplete_summary(self):
        self.data.write_bytes(b"food\t100\n")
        result = self.run_command("summary", success=False)
        self.assertIn("Summary is incomplete", result.stderr)
        self.assertEqual(self.data.read_bytes(), b"food\t100\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--without-summary", action="store_true", help="Check starter behavior")
    args = parser.parse_args()
    ExpensesTest.executable = args.executable.resolve(strict=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExpensesTest)
    if args.without_summary:
        suite = unittest.TestSuite(
            test for test in suite if not test.id().rsplit(".", 1)[-1].startswith("test_summary_")
        )
        suite.addTest(ExpensesTest("check_incomplete_summary"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
