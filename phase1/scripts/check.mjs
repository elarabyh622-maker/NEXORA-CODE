import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { validateGraph, buildPlan } from '../lib/graph.mjs';
const root = new URL('../', import.meta.url);
const load = async file => JSON.parse(await readFile(new URL(file, root), 'utf8'));
const sample = await load('content/sample.json');
const graph = await load('content/graph.json');
assert.equal(sample.schemaVersion, 1);
assert.equal(sample.releaseId, graph.releaseId);
assert.equal(sample.lessons.length, 3);
assert.deepEqual(sample.lessons.map(lesson => lesson.id), graph.lessons.map(lesson => lesson.id));
const nonempty = value => typeof value === 'string' && value.trim().length > 0;
const exerciseIds = new Set();
let exercises = 0;
for (const lesson of sample.lessons) {
  for (const key of ['id','title','summary','why','minutes','takeaway']) assert.ok(nonempty(lesson[key]), `${lesson.id}: ${key}`);
  assert.deepEqual(lesson.skillIds, graph.lessons.find(item => item.id === lesson.id).skillIds);
  assert.ok(lesson.objectives.length > 0 && lesson.objectives.every(nonempty));
  assert.ok(lesson.sections.length >= 3 && lesson.sections.every(section => nonempty(section.heading) && nonempty(section.body)));
  assert.ok(lesson.sections.every(section=>!section.language || ['python','javascript'].includes(section.language)));
  assert.ok(lesson.examples.length > 0 && lesson.examples.every(example => nonempty(example.title) && nonempty(example.code) && nonempty(example.explanation) && ['text','python','javascript'].includes(example.language)));
  assert.equal(lesson.exercises.length, 3);
  assert.ok(lesson.exercises.some(exercise => exercise.independent === true));
  for (const exercise of lesson.exercises) {
    assert.ok(!exerciseIds.has(exercise.id), `duplicate exercise ${exercise.id}`); exerciseIds.add(exercise.id);
    for (const key of ['id','prompt','explanation']) assert.ok(nonempty(exercise[key]));
    assert.ok(['choice','text'].includes(exercise.type));
    assert.ok(exercise.acceptedAnswers.length > 0 && exercise.acceptedAnswers.every(nonempty));
    assert.ok(exercise.hints.length > 0 && exercise.hints.every(nonempty));
    if (exercise.type === 'choice') {
      assert.ok(exercise.options.length >= 2);
      assert.equal(new Set(exercise.options.map(option => option.id)).size, exercise.options.length);
      assert.ok(exercise.acceptedAnswers.every(answer => exercise.options.some(option => option.id === answer)));
    }
    exercises++;
  }
}
assert.ok(sample.glossary.length > 0 && sample.glossary.every(term => nonempty(term.term) && nonempty(term.technical) && nonempty(term.definition)));
assert.deepEqual(validateGraph(graph), {valid:true, errors:[]});
assert.equal(buildPlan(graph, {goalId:'explore'}).steps.length, 3);
for (const file of ['web/app.mjs','web/state.mjs','scripts/serve.mjs','lib/graph.mjs']) {
  const result = spawnSync(process.execPath, ['--check', fileURLToPath(new URL(file, root))], {encoding:'utf8'});
  assert.equal(result.status, 0, `${file}: ${result.stderr}`);
}
const source = await readFile(new URL('web/app.mjs', root), 'utf8');
assert.ok(!/\beval\s*\(|new\s+Function\b|innerHTML\s*=|outerHTML\s*=/.test(source), 'unsafe source-code execution or HTML sinks');
console.log(JSON.stringify({result:'PASSED', release:sample.releaseId, lessons:sample.lessons.length, exercises, glossary:sample.glossary.length, checks:['content contract','graph coverage','JavaScript syntax','no executable learner code / raw HTML sinks']},null,2));
