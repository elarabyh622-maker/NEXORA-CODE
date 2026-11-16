// Offline reference generation from the unchanged phase-one implementation.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { buildPlan } from '../../../phase1/lib/graph.mjs';

const graph = JSON.parse(await readFile(new URL('../../../phase1/content/graph.json', import.meta.url), 'utf8'));
const base = ['concept.program', 'concept.input-output', 'concept.sequence', 'concept.variable'];
const cases = graph.goals.flatMap(goal => Array.from({ length: 5 }, (_, index) => {
  const achievedSkillIds = base.slice(0, index);
  const preferredSkillIds = index % 2 ? ['concept.variable'] : [];
  return { goalId: goal.id, achievedSkillIds, preferredSkillIds, expected: buildPlan(graph, { goalId: goal.id, achievedSkillIds, preferredSkillIds }) };
}));
const directory = new URL('./Fixtures/', import.meta.url);
await mkdir(directory, { recursive: true });
await writeFile(new URL('phase1-plans.json', directory), JSON.stringify(cases, null, 2) + '\n', 'utf8');
console.log(`Generated ${cases.length} reference plans from phase1/lib/graph.mjs.`);
