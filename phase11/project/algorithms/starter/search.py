import json
import sys


def first_linear_index(values, target):
    for index, value in enumerate(values):
        if value == target:
            return index
    return -1


def first_binary_index(sorted_values, target):
    # TODO: Find the first matching index in sorted_values.
    return -1


def report(values, target):
    frequencies = {}
    for value in values:
        frequencies[value] = frequencies.get(value, 0) + 1
    return {
        "linearIndex": first_linear_index(values, target),
        "binaryIndex": first_binary_index(sorted(values), target),
        "occurrences": frequencies.get(target, 0),
    }


def is_supported_integer(value):
    # JSON numbers use IEEE 754 in Node, including representations like 2.0.
    return type(value) in (int, float) and -1000 <= value <= 1000 and int(value) == value


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        print("invalid input", file=sys.stderr)
        return 2

    if type(data) is dict and set(data) == {"values", "target"}:
        values = data["values"]
        target = data["target"]
        if (type(values) is list and len(values) <= 50
                and all(is_supported_integer(value) for value in values)
                and is_supported_integer(target)):
            print(json.dumps(report(values, target), separators=(",", ":")))
            return 0

    print("invalid input", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
