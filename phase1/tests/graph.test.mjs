import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validateGraph, buildPlan, getReadyLessons } from '../lib/graph.mjs';

const graph = JSON.parse(await readFile(new URL('../content/graph.json', import.meta.url), 'utf8'));
const ref = skill => ({ skill });
const all = (...items) => ({ allOf: items });
const any = (...items) => ({ anyOf: items });
const skill = (id, required = null) => ({ id, title: id, description: `تعلم ${id}`, required, recommended: [] });
const lesson = (id, skillIds = [id]) => ({ id: `lesson-${id}`, title: id, skillIds, why: `يساعد درس ${id} على فهم المفهوم.` });
function fixture(skills, taughtIds = skills.map(item => item.id), goalIds = [skills.at(-1).id]) {
  return { schemaVersion: 1, releaseId: 'test', skills, lessons: taughtIds.map(id => lesson(id)), goals: [{ id: 'goal', title: 'هدف', description: 'هدف تجربة', status: 'sample', skillIds: goalIds }] };
}
const ids = plan => plan.steps.map(step => step.lessonId);

test('the real sample validates and plans all three lessons with explanatory reasons', () => {
  assert.deepEqual(validateGraph(graph), { valid: true, errors: [] });
  for (const goalId of ['explore', 'python', 'web']) {
    const plan = buildPlan(graph, { goalId });
    assert.equal(plan.status, 'sample');
    assert.deepEqual(ids(plan), ['what-is-a-program', 'step-by-step', 'first-variable']);
    assert.equal(plan.missingSkillIds.length, 4);
    assert.deepEqual(plan.uncoveredSkillIds, []);
    assert.ok(plan.steps.every(step => step.reason.includes('المهارات الجديدة') && step.reason.length > 30));
  }
});

test('same-lesson prerequisites allow the first sample lesson to be ready', () => {
  assert.deepEqual(getReadyLessons(graph), ['what-is-a-program']);
  assert.deepEqual(getReadyLessons(graph, ['concept.program', 'concept.input-output']), ['step-by-step']);
  assert.deepEqual(getReadyLessons(graph, graph.goals[0].skillIds), []);
});

test('AND prerequisites are all planned in a usable order', () => {
  const data = fixture([skill('a'), skill('b'), skill('c', all(ref('a'), ref('b')))]);
  assert.deepEqual(ids(buildPlan(data, { goalId: 'goal' })), ['lesson-a', 'lesson-b', 'lesson-c']);
  assert.deepEqual(getReadyLessons(data), ['lesson-a', 'lesson-b']);
});

test('OR chooses only one feasible branch and respects preference on a tie', () => {
  const data = fixture([skill('a'), skill('b'), skill('c', any(ref('a'), ref('b')))]);
  const first = buildPlan(data, { goalId: 'goal' });
  assert.deepEqual(ids(first), ['lesson-a', 'lesson-c']);
  assert.deepEqual(first.chosenAlternatives[0].selectedSkillIds, ['a']);
  assert.deepEqual(ids(buildPlan(data, { goalId: 'goal', preferredSkillIds: ['b'] })), ['lesson-b', 'lesson-c']);
  assert.deepEqual(first, buildPlan(data, { goalId: 'goal' }));
});

test('nested AND/OR retains conjunctions and avoids unselected alternatives', () => {
  const data = fixture([skill('a'), skill('b'), skill('c'), skill('d'), skill('target', all(ref('a'), any(all(ref('b'), ref('c')), ref('d'))))]);
  const plan = buildPlan(data, { goalId: 'goal' });
  assert.deepEqual(ids(plan), ['lesson-a', 'lesson-d', 'lesson-target']);
  assert.deepEqual(plan.missingSkillIds, ['target', 'a', 'd']);
  assert.ok(!plan.missingSkillIds.includes('b'));
  const nested = fixture([skill('a'), skill('b'), skill('c'), skill('d'), skill('target', any(all(ref('a'), any(ref('b'), ref('c'))), ref('d')))]);
  const reused = buildPlan(nested, { goalId: 'goal', achievedSkillIds: ['a', 'c'] });
  assert.deepEqual(ids(reused), ['lesson-target']);
  assert.equal(reused.chosenAlternatives.length, 2);
  assert.deepEqual(reused.chosenAlternatives.at(-1).selectedSkillIds, ['a', 'c']);
});

test('existing skill transfer wins over preference and avoids repeating lessons', () => {
  const data = fixture([skill('a'), skill('b'), skill('c', any(ref('a'), ref('b')))]);
  const plan = buildPlan(data, { goalId: 'goal', achievedSkillIds: ['b', 'unknown', 'b'], preferredSkillIds: ['a'] });
  assert.deepEqual(ids(plan), ['lesson-c']);
  assert.deepEqual(plan.missingSkillIds, ['c']);
  assert.deepEqual(plan.chosenAlternatives[0].selectedSkillIds, ['b']);
  const moved = buildPlan(graph, { goalId: 'web', achievedSkillIds: ['concept.program', 'concept.input-output', 'concept.sequence'] });
  assert.deepEqual(ids(moved), ['first-variable']);
  assert.deepEqual(moved.missingSkillIds, ['concept.variable']);
  const done = buildPlan(graph, { goalId: 'python', achievedSkillIds: graph.goals[0].skillIds });
  assert.equal(done.status, 'sample');
  assert.deepEqual(done.steps, []);
  assert.deepEqual(done.missingSkillIds, []);
});

test('OR prefers a covered branch over an uncovered preferred branch', () => {
  const data = fixture([skill('missing'), skill('available'), skill('target', any(ref('missing'), ref('available')))], ['available', 'target']);
  const plan = buildPlan(data, { goalId: 'goal', preferredSkillIds: ['missing'] });
  assert.deepEqual(ids(plan), ['lesson-available', 'lesson-target']);
  assert.deepEqual(plan.uncoveredSkillIds, []);
});

test('an absent lesson exposes a partial plan and blocks dependent lessons', () => {
  const data = fixture([skill('base'), skill('gap', ref('base')), skill('target', ref('gap'))], ['base', 'target']);
  const plan = buildPlan(data, { goalId: 'goal' });
  assert.equal(plan.status, 'partial');
  assert.deepEqual(ids(plan), ['lesson-base']);
  assert.deepEqual(plan.uncoveredSkillIds, ['target', 'gap']);
  assert.equal(buildPlan(fixture([skill('gap')], []), { goalId: 'goal' }).status, 'unavailable');
});

test('planned goals remain planned and report absent curriculum explicitly', () => {
  for (const [goalId, gap] of [['react', 'react.component'], ['ai', 'ai.model']]) {
    const plan = buildPlan(graph, { goalId });
    assert.equal(plan.status, 'planned');
    assert.equal(plan.steps.length, 3);
    assert.deepEqual(plan.uncoveredSkillIds, [gap]);
    assert.ok(!plan.missingSkillIds.some(id => id.startsWith('python.')));
    const achieved = buildPlan(graph, { goalId, achievedSkillIds: graph.goals.find(item => item.id === goalId).skillIds });
    assert.equal(achieved.status, 'planned');
    assert.deepEqual(achieved.steps, []);
  }
});

test('unknown or omitted goals are unavailable, with no fabricated plan', () => {
  assert.equal(buildPlan(graph, { goalId: 'unknown' }).status, 'unavailable');
  assert.deepEqual(buildPlan(graph).steps, []);
});

test('required dependency cycles are rejected, including optional branches', () => {
  const data = fixture([skill('a', ref('b')), skill('b', ref('a'))]);
  assert.equal(validateGraph(data).valid, false);
  assert.ok(validateGraph(data).errors.some(error => error.includes('cycle')));
  assert.equal(buildPlan(data, { goalId: 'goal' }).status, 'unavailable');
  assert.deepEqual(getReadyLessons(data), []);
  assert.equal(validateGraph(fixture([skill('a', any(ref('a'), ref('b'))), skill('b')])).valid, false);
  assert.equal(validateGraph(fixture([skill('a', ref('a'))])).valid, false);
});

test('missing references are found in required, recommended, lessons, and goals', () => {
  for (const mutate of [
    data => { data.skills[0].required = ref('missing'); },
    data => { data.skills[0].recommended = ['missing']; },
    data => { data.lessons[0].skillIds = ['missing']; },
    data => { data.goals[0].skillIds = ['missing']; }
  ]) {
    const data = fixture([skill('a')]);
    mutate(data);
    const result = validateGraph(data);
    assert.equal(result.valid, false);
    assert.ok(result.errors.some(error => error.includes('missing skill reference')));
  }
});

test('empty, ambiguous, and malformed expressions cannot become vacuously satisfied', () => {
  for (const required of [{}, all(), any(), all(ref('a'), any()), { skill: 'a', anyOf: [ref('a')] }, { allOf: 'a' }, undefined]) {
    const data = fixture([skill('a'), { ...skill('b'), required }]);
    assert.equal(validateGraph(data).valid, false);
    assert.equal(buildPlan(data, { goalId: 'goal' }).status, 'unavailable');
  }
});

test('schema errors and duplicate IDs return validation errors without executing anything', () => {
  for (const data of [null, [], {}, { ...graph, skills: null }, fixture([skill('a'), skill('a')]), { ...graph, goals: [{ ...graph.goals[0], status: 'complete' }] }]) {
    assert.equal(validateGraph(data).valid, false);
    assert.deepEqual(getReadyLessons(data), []);
  }
  const circular = {};
  circular.allOf = [circular];
  const result = validateGraph(fixture([skill('a', circular)]));
  assert.ok(result.errors.some(error => error.includes('cyclic expression')));
});

test('inputs remain unchanged across preference and goal switches', () => {
  const before = JSON.stringify(graph);
  const achievedSkillIds = ['concept.program'];
  const preferredSkillIds = ['concept.variable'];
  buildPlan(graph, { goalId: 'react', achievedSkillIds, preferredSkillIds });
  assert.equal(JSON.stringify(graph), before);
  assert.deepEqual(achievedSkillIds, ['concept.program']);
  assert.deepEqual(preferredSkillIds, ['concept.variable']);
});

test('sample content matches graph lesson IDs, skill IDs, and release when present', async context => {
  let sample;
  try { sample = JSON.parse(await readFile(new URL('../content/sample.json', import.meta.url), 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return context.skip('sample.json not delivered yet'); throw error; }
  assert.equal(sample.releaseId, graph.releaseId);
  assert.deepEqual(sample.lessons.map(item => item.id), graph.lessons.map(item => item.id));
  for (const item of sample.lessons) {
    const mapped = graph.lessons.find(lesson => lesson.id === item.id);
    assert.deepEqual(item.skillIds, mapped.skillIds);
    assert.equal(item.title, mapped.title);
  }
});
