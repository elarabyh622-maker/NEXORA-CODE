def integer_in(value, low, high):
    # bool is a subclass of int in Python; the contract excludes it.
    return type(value) in (int, float) and low <= value <= high and int(value) == value


def valid_text(text):
    if not isinstance(text, str) or len(text) > 200:
        return False
    for character in text:
        if character != " " and not ("a" <= character <= "z"):
            return False
    return True


def valid_items(items):
    return isinstance(items, list) and len(items) <= 30 and all(
        integer_in(value, -20, 20) for value in items
    )


def word_counts(text):
    counts = {}
    for word in text.split(" "):
        if word:
            counts[word] = counts.get(word, 0) + 1
    return [[word, count] for word, count in counts.items()]


def pair_sum(items, target):
    left, right = 0, len(items) - 1
    while left < right:
        total = items[left] + items[right]
        if total == target:
            return [left, right]
        if total < target:
            left += 1
        else:
            right -= 1
    return []


def max_window(items, k):
    if k == 0:
        return 0
    current = 0
    for i in range(k):
        current += items[i]
    best = current
    for right in range(k, len(items)):
        current += items[right] - items[right - k]
        best = max(best, current)
    return best


def solve(data):
    if not isinstance(data, dict):
        raise ValueError("invalid input")
    task = data.get("task")
    if task not in ("count", "pair", "window", "report"):
        raise ValueError("invalid input")
    text, items = data.get("text"), data.get("items")
    if task in ("count", "report") and not valid_text(text):
        raise ValueError("invalid input")
    if task in ("pair", "window", "report") and not valid_items(items):
        raise ValueError("invalid input")
    if task == "pair":
        target = data.get("target")
        if not integer_in(target, -40, 40) or any(
            items[i] > items[i + 1] for i in range(len(items) - 1)
        ):
            raise ValueError("invalid input")
        return pair_sum(items, target)
    if task in ("window", "report"):
        k = data.get("k")
        if not integer_in(k, 0, len(items)):
            raise ValueError("invalid input")
        k = int(k)
        if task == "window":
            return max_window(items, k)
        return {"counts": word_counts(text), "maxWindow": max_window(items, k)}
    return word_counts(text)
