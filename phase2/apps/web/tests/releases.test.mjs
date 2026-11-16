import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';

const source = await readFile(new URL('../src/releaseSelection.ts', import.meta.url), 'utf8');
const compiled = stripTypeScriptTypes(source, { mode: 'transform' });
const { catalogReleaseOptions } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const published = { id: 'release-b-id', releaseId: 'release-b', title: 'الإصدار المنشور', status: 'published' };
const retired = { id: 'release-a-id', releaseId: 'release-a', title: 'الإصدار المتقاعد', status: 'retired' };
const catalog = (releases, activeReleaseId) => ({ releases, activeReleaseId, goals: [] });

test('a published replacement without an active release must be selected explicitly', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([published], null), ''), {
    published: [published], initialId: '', needsChoice: true,
  });
});

test('an activated published release opens automatically for a new visitor', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([published], published.releaseId), ''), {
    published: [published], initialId: published.releaseId, needsChoice: false,
  });
});

test('changing the default does not replace an explicitly selected release or historical plan', () => {
  const options = catalogReleaseOptions(catalog([published], published.releaseId), retired.releaseId);
  assert.equal(options.initialId, '');
  assert.equal(options.needsChoice, false);
});

test('the chooser remains hidden when there is no published replacement', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([retired], null), ''), {
    published: [], initialId: '', needsChoice: false,
  });
});
