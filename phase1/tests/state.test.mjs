import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyState, normaliseAnswer, checkAnswer, recordAnswer, lessonProgress, sanitizeState, completedSkills, persistState, STORAGE_KEY } from '../web/state.mjs';

const exercise = { id: 'q1', type: 'text', acceptedAnswers: ['12'], independent: true, hints: ['فكر في الناتج'] };
const lesson = { id: 'l1', skillIds: ['s1'], exercises: [exercise] };
const sample = { lessons: [lesson] };
const graph = { goals: [{ id: 'explore' }] };

test('Arabic digits and outer whitespace are accepted, but no evaluation occurs', () => {
  assert.equal(normaliseAnswer(' ١٢ '), '12');
  assert.equal(checkAnswer(exercise, '١٢'), true);
  assert.equal(checkAnswer(exercise, '6+6'), false);
  assert.equal(checkAnswer({ ...exercise, acceptedAnswers: [''] }, ''), false);
});
test('One wrong attempt never completes the lesson', () => {
  const state = recordAnswer(emptyState(), lesson, exercise, '13');
  assert.equal(lessonProgress(lesson, state).complete, false);
  assert.deepEqual(completedSkills(sample, state), []);
});
test('Correct answer records practice and preserves hint use', () => {
  const oldState = emptyState(); oldState.hintLevels.q1 = 1;
  const state = recordAnswer(oldState, lesson, exercise, '12');
  assert.equal(lessonProgress(lesson, state).complete, true);
  assert.equal(lessonProgress(lesson, state).independent, false);
  assert.deepEqual(completedSkills(sample, state), ['s1']);
  assert.equal(oldState.answers.q1, undefined);
});
test('A new unassisted attempt can show independent sample practice', () => {
  const state = recordAnswer(emptyState(), lesson, exercise, '12');
  assert.equal(lessonProgress(lesson, state).independent, true);
});
test('Corrupted or other-release saved state is discarded safely', () => {
  assert.deepEqual(sanitizeState(null, sample, graph), emptyState());
  assert.deepEqual(sanitizeState({ ...emptyState(), releaseId: 'older' }, sample, graph), emptyState());
});
test('Stored correctness is recomputed and unknown exercises are dropped', () => {
  const stored = { ...emptyState(), answers: { q1: { value: 'wrong', correct: true, attempts: 1 }, hidden: { value: '12', correct: true } } };
  const state = sanitizeState(stored, sample, graph);
  assert.equal(state.answers.q1.correct, false);
  assert.equal(state.answers.hidden, undefined);
});
test('Saving reports failure when storage is unavailable, without losing the in-memory answer', () => {
  const state = recordAnswer(emptyState(), lesson, exercise, '12');
  assert.equal(persistState({setItem(){throw new Error('Quota exceeded');}}, state), false);
  assert.equal(state.answers.q1.correct, true);
});
test('Saving reports success only after the storage write succeeds', () => {
  const records = new Map();
  assert.equal(persistState({setItem(key,value){records.set(key,value);}}, emptyState()), true);
  assert.deepEqual(JSON.parse(records.get(STORAGE_KEY)), emptyState());
});
