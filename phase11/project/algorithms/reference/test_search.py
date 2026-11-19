import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).with_name("search.py")


def run_cli(data):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=data,
        text=True,
        capture_output=True,
        timeout=10,
    )


class SearchCliTests(unittest.TestCase):
    def assert_report(self, values, target, expected):
        result = run_cli(json.dumps({"values": values, "target": target}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_invalid(self, data):
        result = run_cli(data)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "invalid input")

    def test_duplicate_uses_first_index_in_sorted_copy(self):
        self.assert_report([12, 2, 12, 25], 12,
                           {"linearIndex": 0, "binaryIndex": 1, "occurrences": 2})
        self.assert_report([30, -2, -2, 3], -2,
                           {"linearIndex": 1, "binaryIndex": 0, "occurrences": 2})
        self.assert_report([2, 2, 30], 30,
                           {"linearIndex": 2, "binaryIndex": 2, "occurrences": 1})

    def test_empty_list(self):
        self.assert_report([], 7, {"linearIndex": -1, "binaryIndex": -1, "occurrences": 0})

    def test_missing_value(self):
        self.assert_report([9, 1, 1], 4,
                           {"linearIndex": -1, "binaryIndex": -1, "occurrences": 0})

    def test_invalid_shape_or_value(self):
        self.assert_invalid('{"values":[true],"target":1}')
        self.assert_invalid('{"values":[1001],"target":1}')
        self.assert_invalid('{"values":[1.5],"target":1}')
        self.assert_invalid('{"values":[],"target":1,"extra":0}')
        self.assert_invalid(json.dumps({"values": [0] * 51, "target": 1}))

    def test_invalid_json(self):
        self.assert_invalid('{"values":')


if __name__ == "__main__":
    unittest.main()
