import json
import sys
from rules import solve


def reject_constant(token):
    # NaN and Infinity are accepted extensions in json.loads, not valid JSON.
    raise ValueError("invalid input")


def main():
    try:
        data = json.loads(sys.stdin.read(), parse_constant=reject_constant)
        result = {"result": solve(data)}
    except (ValueError, TypeError):
        result = {"error": "invalid input"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
