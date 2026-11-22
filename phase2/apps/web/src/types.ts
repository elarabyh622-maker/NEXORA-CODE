export type User = { id: string; userName: string; displayName: string; role: string };
export type Goal = { id: string; title: string; description: string; status: string; skillIds: string[] };
export type Release = { id: string; releaseId: string; title: string; status: string; version?: number };
export type CommercialOffer = { goalId: string; price: number; currency: string };
export type CommercialEntitlement = { required: boolean; active: boolean; goalIds?: string[]; lessonIds?: string[] };
export type CommercialTarget = { id: string; title: string };
export type CommercialTargets = { goals: CommercialTarget[]; lessons: CommercialTarget[] };
export type CommercialAccount = { userName: string; displayName: string; fullAccess: boolean; goalIds: string[]; lessonIds: string[] };
export type AccessCancellation = { id: string; status: 'pending' | 'approved' | 'declined'; requestedAt: string };
export type Purchase = CommercialOffer & { id: string; status: 'pending' | 'link-ready' | 'confirmed' | 'closed'; checkoutUrl: string | null; requestedAt: string };
export type Catalog = { releases: Release[]; goals: Goal[]; activeReleaseId: string | null; accessRequired?: boolean; contactUrl?: string | null; offers?: CommercialOffer[] };
export type Exercise = { id: string; type: 'choice' | 'text'; prompt: string; options: { id: string; text: string }[]; hints: string[]; independent: boolean };
export type ExampleLanguage = 'python' | 'javascript' | 'csharp' | 'cpp' | 'java' | 'go';
export type Lesson = { id: string; title: string; summary: string; why: string; minutes: string; skillIds: string[]; objectives: string[];
  sections: { heading: string; body: string; language?: ExampleLanguage }[];
  examples: { title: string; language: 'text' | ExampleLanguage; code: string; explanation: string }[];
  exercises: Exercise[]; takeaway: string };
export type CurriculumProject = { id: string; title: string; lessonId: string; summary: string; criteria: string[]; download?: string };
export type CurriculumTrack = { id: string; title: string; lessonIds: string[] };
export type LessonOverview = Pick<Lesson, 'id' | 'title' | 'summary' | 'minutes'> & (
  { exampleLanguages: ('text' | ExampleLanguage)[]; examples?: never } |
  { exampleLanguages?: never; examples: Lesson['examples'] }
);
export type ContentOverview = Release & { sample: { title: string; intro: string; lessons: LessonOverview[];
  glossary: { term: string; technical: string; definition: string }[];
  tracks?: CurriculumTrack[]; projects?: CurriculumProject[];
}; graph: { goals: Goal[]; skills: { id: string; title: string }[] } };
export type Plan = { releaseId: string; goalId: string; status: string; plannerVersion: string; steps: { lessonId: string; skillIds: string[]; reason: string }[]; missingSkillIds: string[]; uncoveredSkillIds: string[]; chosenAlternatives: unknown[] };
export type SavedPlan = { id: string; revision: number; releaseId: string; goalId: string; status: string; plan: Plan };
export type Revision = { id: string; revision: number; releaseId: string; goalId: string; createdAt: string };
export type Progress = { releaseId: string; completedLessonIds: string[]; practicedSkillIds: string[]; correctExerciseIds: string[]; attemptsCount: number; solved: number; total: number; lessons: { lessonId: string; solved: number; total: number; complete: boolean }[]; skills: { skillId: string; status: string }[] };
export type Draft = { answer: string; version: number };
export type Attempt = { id: string; correct: boolean; assisted: boolean; explanation: string; alreadyRecorded: boolean };
export type DraftState = Draft & { dirty: boolean; loaded: boolean; remote?: Draft; hintsUsed?: number; attempt?: { signature: string; key: string } };
