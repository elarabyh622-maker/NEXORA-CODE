"use strict";
const fs = require("node:fs");
const {solve} = require("./rules.cjs");

function main() {
  let output;
  try {
    const data = JSON.parse(fs.readFileSync(0, "utf8"));
    output = {result: solve(data)};
  } catch (error) {
    // Keep unexpected programming mistakes visible while reporting bad input.
    if (!(error instanceof SyntaxError) && error.message !== "invalid input") throw error;
    output = {error: "invalid input"};
  }
  console.log(JSON.stringify(output));
}

if (require.main === module) main();
module.exports = {main};
