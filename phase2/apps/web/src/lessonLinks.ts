import { segment } from './api';

const sampleLessonIds = new Set(['what-is-a-program', 'step-by-step', 'first-variable']);

export function lessonLink(lessonId: string, releaseId: string, exampleLanguage?: 'python' | 'javascript', goalId?: string) {
  const link = `#lesson/${segment(lessonId)}/${segment(releaseId)}`;
  return goalId ? `${link}/${exampleLanguage ?? ''}/${segment(goalId)}` : exampleLanguage ? `${link}/${exampleLanguage}` : link;
}

export function planLink(goalParam?: string) {
  if (!goalParam) return '#plan';
  try { return `#plan/${segment(decodeURIComponent(goalParam))}`; } catch { return '#plan'; }
}

export function linkedLessonRelease(lessonParam: string | undefined, releaseParam: string | undefined) {
  if (releaseParam) {
    try { return decodeURIComponent(releaseParam); } catch { return null; }
  }
  return lessonParam && sampleLessonIds.has(lessonParam) ? 'phase1-ar-v1' : null;
}
