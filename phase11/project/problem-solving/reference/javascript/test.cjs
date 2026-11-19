"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawnSync} = require("node:child_process");
const {solve} = require("./rules.cjs");
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures.json"), "utf8"));

for (const fixture of cases) {
  const data = JSON.parse(JSON.stringify(fixture.input));
  const before = JSON.parse(JSON.stringify(data));
  let actual;
  try {
    actual = {result: solve(data)};
  } catch (error) {
    if (error.message !== "invalid input") throw error;
    actual = {error: "invalid input"};
  }
  assert.deepEqual(actual, fixture.expected, fixture.name);
  assert.deepEqual(data, before, "mutated input: " + fixture.name);
  const run = spawnSync(process.execPath, [path.join(__dirname, "main.cjs")], {
    input: JSON.stringify(fixture.input), encoding: "utf8"
  });
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stderr, "", fixture.name);
  assert.deepEqual(JSON.parse(run.stdout), fixture.expected, "CLI: " + fixture.name);
}
const rawInvalid = ["{broken", '{"task":"count","text":"a","extra":NaN}',
  '{"task":"count","text":"a","extra":Infinity}',
  '{"task":"count","text":"a","extra":-Infinity}'];
for (const raw of rawInvalid) {
  const malformed = spawnSync(process.execPath, [path.join(__dirname, "main.cjs")], {
    input: raw, encoding: "utf8"
  });
  assert.equal(malformed.status, 0, malformed.stderr);
  assert.equal(malformed.stderr, "");
  assert.deepEqual(JSON.parse(malformed.stdout), {error: "invalid input"}, raw);
}
console.log(`${cases.length} fixtures: direct + CLI + unchanged input; invalid raw JSON: ${rawInvalid.length}`);
