const fs = require("node:fs");

function firstLinearIndex(values, target) {
  for (let index = 0; index < values.length; index += 1) {
    if (values[index] === target) return index;
  }
  return -1;
}

function firstBinaryIndex(sortedValues, target) {
  // TODO: Find the first matching index in sortedValues.
  return -1;
}

function report(values, target) {
  const frequencies = new Map();
  for (const value of values) {
    frequencies.set(value, (frequencies.get(value) ?? 0) + 1);
  }
  const sortedValues = values.slice().sort((first, second) => first - second);
  return {
    linearIndex: firstLinearIndex(values, target),
    binaryIndex: firstBinaryIndex(sortedValues, target),
    occurrences: frequencies.get(target) ?? 0,
  };
}

function isSupportedInteger(value) {
  return Number.isInteger(value) && value >= -1000 && value <= 1000;
}

function main() {
  let data;
  try {
    data = JSON.parse(fs.readFileSync(0, "utf8"));
  } catch (error) {
    console.error("invalid input");
    return 2;
  }

  if (data !== null && typeof data === "object" && Object.keys(data).length === 2) {
    const { values, target } = data;
    if (Array.isArray(values) && values.length <= 50
        && values.every(isSupportedInteger) && isSupportedInteger(target)) {
      console.log(JSON.stringify(report(values, target)));
      return 0;
    }
  }

  console.error("invalid input");
  return 2;
}

process.exitCode = main();
