const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

function runCli(input) {
  return spawnSync(process.execPath, [path.join(__dirname, "search.cjs")], {
    input,
    encoding: "utf8",
    timeout: 10000,
  });
}

function assertReport(values, target, expected) {
  const result = runCli(JSON.stringify({ values, target }));
  assert.equal(result.status, 0);
  assert.equal(result.stderr, "");
  assert.deepEqual(JSON.parse(result.stdout), expected);
}

function assertInvalid(input) {
  const result = runCli(input);
  assert.equal(result.status, 2);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr.trim(), "invalid input");
}

test("duplicate uses first index in sorted copy", () => {
  assertReport([12, 2, 12, 25], 12, { linearIndex: 0, binaryIndex: 1, occurrences: 2 });
  assertReport([30, -2, -2, 3], -2, { linearIndex: 1, binaryIndex: 0, occurrences: 2 });
  assertReport([2, 2, 30], 30, { linearIndex: 2, binaryIndex: 2, occurrences: 1 });
});

test("empty list", () => {
  assertReport([], 7, { linearIndex: -1, binaryIndex: -1, occurrences: 0 });
});

test("missing value", () => {
  assertReport([9, 1, 1], 4, { linearIndex: -1, binaryIndex: -1, occurrences: 0 });
});

test("invalid shape or value", () => {
  assertInvalid('{"values":[true],"target":1}');
  assertInvalid('{"values":[1001],"target":1}');
  assertInvalid('{"values":[1.5],"target":1}');
  assertInvalid('{"values":[],"target":1,"extra":0}');
  assertInvalid(JSON.stringify({ values: Array(51).fill(0), target: 1 }));
});

test("invalid JSON", () => {
  assertInvalid('{"values":');
});
