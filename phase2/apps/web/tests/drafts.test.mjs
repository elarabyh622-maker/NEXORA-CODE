import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';

const source = await readFile(new URL('../src/draftState.ts', import.meta.url), 'utf8');
const compiled = stripTypeScriptTypes(source, { mode: 'transform' });
const { receiveServerDraft, acknowledgeDraftSave, attemptKey } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('an answer typed before the remote read finishes is retained and compared', () => {
  const local = { answer: 'نصي الذي كتبته الآن', version: 1, dirty: true, loaded: false };
  const remote = { answer: 'نسخة من علامة تبويب أخرى', version: 2 };
  const next = receiveServerDraft(local, remote);
  assert.equal(next.answer, local.answer);
  assert.equal(next.version, 1);
  assert.equal(next.dirty, true);
  assert.deepEqual(next.remote, remote);
  assert.equal(next.loaded, true);
});

test('a save acknowledgement cannot replace an answer edited while saving', () => {
  const local = { answer: 'كتابة أحدث', version: 4, dirty: true, loaded: true, remote: { answer: 'نسخة أخرى', version: 5 } };
  const next = acknowledgeDraftSave(local, 'كتابة أرسلت سابقًا', { answer: 'كتابة أرسلت سابقًا', version: 6 });
  assert.equal(next.answer, 'كتابة أحدث');
  assert.equal(next.dirty, true);
  assert.equal(next.version, 6);
  assert.equal(next.remote, undefined);
});

test('a confirmed save clears dirty state only for the submitted answer', () => {
  const next = acknowledgeDraftSave({ answer: 'إجابتي', version: 0, dirty: true, loaded: true }, 'إجابتي', { answer: 'إجابتي', version: 1 });
  assert.equal(next.dirty, false);
  assert.equal(next.answer, 'إجابتي');
  assert.equal(next.version, 1);
});

test('retrying an uncertain attempt and reopening the lesson retains the same key', () => {
  const signature = JSON.stringify({ exerciseId: 'one', answer: 'إجابتي', hintsUsed: 1 });
  const state = receiveServerDraft({ answer: 'إجابتي', version: 2, dirty: false, loaded: true, hintsUsed: 1, attempt: { signature, key: 'first-attempt-key' } }, { answer: 'إجابتي', version: 2 });
  assert.equal(attemptKey(state, signature, () => 'incorrect-new-key'), 'first-attempt-key');
  assert.equal(state.hintsUsed, 1);
  assert.equal(attemptKey(state, 'different-payload', () => 'new-attempt-key'), 'new-attempt-key');
});
