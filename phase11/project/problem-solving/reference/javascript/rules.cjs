"use strict";

function integerIn(value, low, high) {
  return Number.isInteger(value) && low <= value && value <= high;
}
function validText(text) {
  if (typeof text !== "string" || text.length > 200) return false;
  for (const character of text) {
    if (character !== " " && !(character >= "a" && character <= "z")) return false;
  }
  return true;
}
function validItems(items) {
  return Array.isArray(items) && items.length <= 30 &&
    items.every(value => integerIn(value, -20, 20));
}
function wordCounts(text) {
  const counts = new Map();
  for (const word of text.split(" ")) {
    if (word !== "") counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return Array.from(counts);
}
function pairSum(items, target) {
  let left = 0, right = items.length - 1;
  while (left < right) {
    const total = items[left] + items[right];
    if (total === target) return [left, right];
    if (total < target) left++;
    else right--;
  }
  return [];
}
function maxWindow(items, k) {
  if (k === 0) return 0;
  let current = 0;
  for (let i = 0; i < k; i++) current += items[i];
  let best = current;
  for (let right = k; right < items.length; right++) {
    current += items[right] - items[right - k];
    best = Math.max(best, current);
  }
  return best;
}
function solve(data) {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("invalid input");
  }
  const {task, text, items, target, k} = data;
  if (!["count", "pair", "window", "report"].includes(task)) throw new Error("invalid input");
  if (["count", "report"].includes(task) && !validText(text)) throw new Error("invalid input");
  if (["pair", "window", "report"].includes(task) && !validItems(items)) throw new Error("invalid input");
  if (task === "pair") {
    if (!integerIn(target, -40, 40) || items.some((value, i) => i > 0 && items[i - 1] > value)) {
      throw new Error("invalid input");
    }
    return pairSum(items, target);
  }
  if (["window", "report"].includes(task)) {
    if (!integerIn(k, 0, items.length)) throw new Error("invalid input");
    if (task === "window") return maxWindow(items, k);
    return {counts: wordCounts(text), maxWindow: maxWindow(items, k)};
  }
  return wordCounts(text);
}

module.exports = {solve, wordCounts, pairSum, maxWindow};
