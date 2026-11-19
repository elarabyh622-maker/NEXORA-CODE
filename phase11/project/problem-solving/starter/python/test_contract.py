import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from rules import solve

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE.parent / "fixtures.json").read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_all_fixtures(self):
        # One test intentionally stops on the first unfinished starter behavior.
        for case in CASES:
            data = copy.deepcopy(case["input"])
            before = copy.deepcopy(data)
            try:
                actual = {"result": solve(data)}
            except ValueError:
                actual = {"error": "invalid input"}
            self.assertEqual(actual, case["expected"], case["name"])
            self.assertEqual(data, before, "mutated input: " + case["name"])
            run = subprocess.run([sys.executable, str(HERE / "main.py")],
                                 input=json.dumps(case["input"], ensure_ascii=False),
                                 text=True, encoding="utf-8", capture_output=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, "", case["name"])
            self.assertEqual(json.loads(run.stdout), case["expected"], "CLI: " + case["name"])
        raw_invalid = ["{broken", '{"task":"count","text":"a","extra":NaN}',
                       '{"task":"count","text":"a","extra":Infinity}',
                       '{"task":"count","text":"a","extra":-Infinity}']
        for raw in raw_invalid:
            malformed = subprocess.run([sys.executable, str(HERE / "main.py")], input=raw,
                                       text=True, encoding="utf-8", capture_output=True, check=False)
            self.assertEqual(malformed.returncode, 0, malformed.stderr)
            self.assertEqual(malformed.stderr, "")
            self.assertEqual(json.loads(malformed.stdout), {"error": "invalid input"}, raw)
        print(f"{len(CASES)} fixtures: direct + CLI + unchanged input; invalid raw JSON: {len(raw_invalid)}")


if __name__ == "__main__":
    unittest.main()
