// Local sample planner. Deterministic greedy choices, not a global optimizer or mastery model.
const nonempty = value => typeof value === 'string' && value.trim().length > 0;
const unique = values => [...new Set(values)];

export function validateGraph(graph) {
  const errors = [];
  if (!graph || typeof graph !== 'object' || Array.isArray(graph)) {
    return { valid: false, errors: ['graph must be an object'] };
  }
  if (graph.schemaVersion !== 1) errors.push('schemaVersion must be 1');
  if (!nonempty(graph.releaseId)) errors.push('releaseId must be a nonempty string');
  const tables = {};
  for (const key of ['skills', 'lessons', 'goals']) {
    if (!Array.isArray(graph[key])) errors.push(`${key} must be an array`);
    const rows = Array.isArray(graph[key]) ? graph[key] : [];
    tables[key] = new Map();
    for (const [index, row] of rows.entries()) {
      if (!row || typeof row !== 'object' || Array.isArray(row) || !nonempty(row.id)) {
        errors.push(`${key}[${index}] must have a nonempty id`);
        continue;
      }
      if (tables[key].has(row.id)) errors.push(`duplicate ${key} id: ${row.id}`);
      tables[key].set(row.id, row);
      if (!nonempty(row.title)) errors.push(`${key}.${row.id}.title must be nonempty`);
    }
  }
  const edges = new Map([...tables.skills.keys()].map(id => [id, []]));
  function reference(id, path) {
    if (!nonempty(id) || !tables.skills.has(id)) errors.push(`${path}: missing skill reference ${String(id)}`);
  }
  function expression(expr, path, owner, ancestors = new Set()) {
    if (!expr || typeof expr !== 'object' || Array.isArray(expr)) {
      errors.push(`${path}: expected skill, allOf or anyOf expression`);
      return;
    }
    if (ancestors.has(expr)) { errors.push(`${path}: cyclic expression object`); return; }
    const keys = Object.keys(expr);
    if (keys.length !== 1 || !['skill', 'allOf', 'anyOf'].includes(keys[0])) {
      errors.push(`${path}: expression must contain exactly one of skill, allOf, anyOf`);
      return;
    }
    const key = keys[0];
    if (key === 'skill') {
      reference(expr.skill, path);
      if (tables.skills.has(expr.skill)) edges.get(owner).push(expr.skill);
      return;
    }
    if (!Array.isArray(expr[key]) || expr[key].length === 0) {
      errors.push(`${path}.${key}: group must be a nonempty array`);
      return;
    }
    const next = new Set(ancestors).add(expr);
    expr[key].forEach((child, index) => expression(child, `${path}.${key}[${index}]`, owner, next));
  }
  function skillList(values, path, allowEmpty = false) {
    if (!Array.isArray(values) || (!allowEmpty && values.length === 0)) {
      errors.push(`${path}: expected ${allowEmpty ? 'an' : 'a nonempty'} array`);
      return;
    }
    if (new Set(values).size !== values.length) errors.push(`${path}: duplicate skill references`);
    values.forEach(id => reference(id, path));
  }
  for (const skill of tables.skills.values()) {
    if (!nonempty(skill.description)) errors.push(`skills.${skill.id}.description must be nonempty`);
    if (skill.required !== null) expression(skill.required, `skills.${skill.id}.required`, skill.id);
    skillList(skill.recommended, `skills.${skill.id}.recommended`, true);
  }
  for (const lesson of tables.lessons.values()) {
    skillList(lesson.skillIds, `lessons.${lesson.id}.skillIds`);
    if (!nonempty(lesson.why)) errors.push(`lessons.${lesson.id}.why must be nonempty`);
  }
  for (const goal of tables.goals.values()) {
    skillList(goal.skillIds, `goals.${goal.id}.skillIds`);
    if (!nonempty(goal.description)) errors.push(`goals.${goal.id}.description must be nonempty`);
    if (!['sample', 'planned'].includes(goal.status)) errors.push(`goals.${goal.id}.status must be sample or planned`);
  }
  const visiting = new Set(), visited = new Set();
  function visit(id, chain) {
    if (visiting.has(id)) { errors.push(`dependency cycle: ${[...chain, id].join(' -> ')}`); return; }
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dependency of edges.get(id)) visit(dependency, [...chain, id]);
    visiting.delete(id);
    visited.add(id);
  }
  for (const id of edges.keys()) visit(id, []);
  return { valid: errors.length === 0, errors };
}

function satisfied(expr, available) {
  if (expr === null) return true;
  if ('skill' in expr) return available.has(expr.skill);
  if ('allOf' in expr) return expr.allOf.every(child => satisfied(child, available));
  return expr.anyOf.some(child => satisfied(child, available));
}

function lessonReady(lesson, available, skills) {
  // A lesson can introduce prerequisites before dependent skills within that same lesson.
  const local = new Set(available);
  let changed = true;
  while (changed) {
    changed = false;
    for (const id of lesson.skillIds) {
      if (!local.has(id) && satisfied(skills.get(id).required, local)) {
        local.add(id);
        changed = true;
      }
    }
  }
  return lesson.skillIds.every(id => local.has(id));
}

export function getReadyLessons(graph, achievedSkillIds = []) {
  if (!validateGraph(graph).valid) return [];
  const skills = new Map(graph.skills.map(skill => [skill.id, skill]));
  const available = new Set(Array.isArray(achievedSkillIds) ? achievedSkillIds : []);
  return graph.lessons.filter(lesson => lesson.skillIds.some(id => !available.has(id)) && lessonReady(lesson, available, skills)).map(lesson => lesson.id);
}

export function buildPlan(graph, { goalId, achievedSkillIds = [], preferredSkillIds = [] } = {}) {
  const empty = { goalId: goalId ?? null, status: 'unavailable', steps: [], missingSkillIds: [], uncoveredSkillIds: [], chosenAlternatives: [] };
  if (!validateGraph(graph).valid) return empty;
  const goal = graph.goals.find(item => item.id === goalId);
  if (!goal) return empty;
  const skills = new Map(graph.skills.map(skill => [skill.id, skill]));
  const achieved = new Set((Array.isArray(achievedSkillIds) ? achievedSkillIds : []).filter(id => skills.has(id)));
  const preferred = new Set(Array.isArray(preferredSkillIds) ? preferredSkillIds : []);
  const initial = { available: new Set(achieved), required: new Set(), steps: [], choices: [], active: new Set() };
  const clone = state => ({ available: new Set(state.available), required: new Set(state.required), steps: [...state.steps], choices: [...state.choices], active: new Set(state.active) });
  const adopt = (state, result) => Object.assign(state, result);
  function ensureExpression(expr, state, owner, path, internal = new Set()) {
    if (expr === null) return [];
    if ('skill' in expr) {
      if (!internal.has(expr.skill)) ensureSkill(expr.skill, state, owner);
      return [expr.skill];
    }
    if ('allOf' in expr) {
      return unique(expr.allOf.flatMap((child, index) => ensureExpression(child, state, owner, `${path}.allOf[${index}]`, internal)));
    }
    const candidates = expr.anyOf.map((child, index) => {
      const trial = clone(state);
      const selectedSkillIds = ensureExpression(child, trial, owner, `${path}.anyOf[${index}]`, internal);
      const available = new Set([...trial.available, ...internal]);
      const unresolved = [...trial.required].filter(id => !available.has(id)).length;
      return { index, trial, selectedSkillIds, score: [satisfied(child, available) ? 0 : 1, unresolved, trial.steps.length - state.steps.length, -selectedSkillIds.filter(id => preferred.has(id)).length, index] };
    });
    candidates.sort((a, b) => {
      for (let i = 0; i < a.score.length; i++) if (a.score[i] !== b.score[i]) return a.score[i] - b.score[i];
      return 0;
    });
    const selected = candidates[0];
    adopt(state, selected.trial);
    state.choices.push({ skillId: owner, path, alternativeIndex: selected.index, selectedSkillIds: selected.selectedSkillIds });
    return selected.selectedSkillIds;
  }
  function ensureSkill(id, state, forSkillId = null) {
    state.required.add(id);
    if (state.available.has(id) || state.active.has(id)) return;
    state.active.add(id);
    const skill = skills.get(id);
    const lesson = graph.lessons.find(item => item.skillIds.includes(id));
    if (!lesson) {
      ensureExpression(skill.required, state, id, 'required');
      state.active.delete(id);
      return;
    }
    const internal = new Set(lesson.skillIds);
    for (const taughtId of lesson.skillIds) {
      if (!state.available.has(taughtId)) ensureExpression(skills.get(taughtId).required, state, taughtId, 'required', internal);
    }
    if (lessonReady(lesson, state.available, skills) && !state.steps.some(step => step.lessonId === lesson.id)) {
      const skillIds = lesson.skillIds.filter(taughtId => !state.available.has(taughtId));
      if (skillIds.length) {
        const purpose = forSkillId ? `تمهيدًا لمهارة «${skills.get(forSkillId).title}»` : `للتقدم نحو هدف «${goal.title}»`;
        state.steps.push({ lessonId: lesson.id, skillIds, reason: `ندرس «${lesson.title}» ${purpose}. ${lesson.why} المهارات الجديدة: ${skillIds.map(taughtId => skills.get(taughtId).title).join('، ')}.` });
        for (const taughtId of skillIds) { state.available.add(taughtId); state.required.add(taughtId); }
      }
    }
    state.active.delete(id);
  }
  goal.skillIds.forEach(id => ensureSkill(id, initial));
  const missingSkillIds = [...initial.required].filter(id => !achieved.has(id));
  const uncoveredSkillIds = missingSkillIds.filter(id => !initial.available.has(id));
  return {
    goalId,
    status: goal.status === 'planned' ? 'planned' : uncoveredSkillIds.length ? (initial.steps.length || goal.skillIds.some(id => achieved.has(id)) ? 'partial' : 'unavailable') : 'sample',
    steps: initial.steps,
    missingSkillIds,
    uncoveredSkillIds,
    chosenAlternatives: initial.choices
  };
}
