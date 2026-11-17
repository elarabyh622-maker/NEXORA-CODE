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

test('published content without an active release stays inactive for visitors', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([published], null)), {
    published: [published], activeId: '',
  });
});

test('an activated published release opens automatically for a new visitor', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([published], published.releaseId)), {
    published: [published], activeId: published.releaseId,
  });
});

test('an invalid retired selection does not open retired content', () => {
  assert.deepEqual(catalogReleaseOptions(catalog([published, retired], retired.releaseId)), {
    published: [published], activeId: '',
  });
});
