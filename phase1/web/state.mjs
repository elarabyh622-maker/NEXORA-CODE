export const STORAGE_KEY = 'masar:phase1:ar:v1';
export const RELEASE_ID = 'phase1-ar-v1';

export function emptyState() {
  return { version: 1, releaseId: RELEASE_ID, goalId: 'explore', language: 'python', answers: {}, drafts: {}, hintLevels: {}, lastLessonId: null, feedback: '' };
}

export function persistState(storage, state) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify(state)); return true; }
  catch { return false; }
}

export function normaliseAnswer(value) {
  return String(value ?? '').normalize('NFKC').trim().replace(/[٠-٩]/g, digit => String(digit.charCodeAt(0) - 1632)).replace(/[۰-۹]/g, digit => String(digit.charCodeAt(0) - 1776)).replace(/\r\n?/g, '\n');
}

export function checkAnswer(exercise, value) {
  const normalized = normaliseAnswer(value);
  return normalized.length > 0 && exercise.acceptedAnswers.some(answer => normaliseAnswer(answer) === normalized);
}

export function sanitizeState(raw, sample, graph) {
  const state = emptyState();
  if (!raw || typeof raw !== 'object' || raw.version !== 1 || raw.releaseId !== RELEASE_ID) return state;
  if (graph.goals.some(goal => goal.id === raw.goalId)) state.goalId = raw.goalId;
  if (['python', 'javascript'].includes(raw.language)) state.language = raw.language;
  const ids = new Set(sample.lessons.flatMap(lesson => lesson.exercises.map(exercise => exercise.id)));
  for (const lesson of sample.lessons) for (const exercise of lesson.exercises) {
    const record = raw.answers?.[exercise.id];
    if (record && typeof record.value === 'string' && record.value.length <= 2000) {
      state.answers[exercise.id] = { value: record.value, correct: checkAnswer(exercise, record.value), assisted: record.assisted === true, attempts: Math.min(1000, Math.max(1, Number(record.attempts) || 1)), lessonId: lesson.id };
    }
    const draft = raw.drafts?.[exercise.id];
    if (typeof draft === 'string') state.drafts[exercise.id] = draft.slice(0, 2000);
    const level = raw.hintLevels?.[exercise.id];
    if (Number.isInteger(level) && level > 0) state.hintLevels[exercise.id] = Math.min(level, exercise.hints.length);
  }
  if (sample.lessons.some(lesson => lesson.id === raw.lastLessonId)) state.lastLessonId = raw.lastLessonId;
  if (typeof raw.feedback === 'string') state.feedback = raw.feedback.slice(0, 2000);
  // Unknown exercises and values never become local progress.
  for (const id of Object.keys(state.answers)) if (!ids.has(id)) delete state.answers[id];
  return state;
}

export function recordAnswer(state, lesson, exercise, value) {
  const result = structuredClone(state);
  result.lastLessonId = lesson.id;
  result.drafts[exercise.id] = String(value).slice(0, 2000);
  result.answers[exercise.id] = {
    value: String(value).slice(0, 2000), correct: checkAnswer(exercise, value),
    assisted: (state.hintLevels[exercise.id] ?? 0) > 0 || state.answers[exercise.id]?.assisted === true,
    attempts: Math.min(1000, (state.answers[exercise.id]?.attempts ?? 0) + 1), lessonId: lesson.id
  };
  return result;
}

export function lessonProgress(lesson, state) {
  const solved = lesson.exercises.filter(exercise => state.answers[exercise.id]?.correct).length;
  const independent = lesson.exercises.filter(exercise => exercise.independent).every(exercise => {
    const record = state.answers[exercise.id];
    return record?.correct && !record.assisted;
  });
  return { solved, total: lesson.exercises.length, complete: solved === lesson.exercises.length, independent };
}

export function completedSkills(sample, state) {
  return [...new Set(sample.lessons.filter(lesson => lessonProgress(lesson, state).complete).flatMap(lesson => lesson.skillIds))];
}
