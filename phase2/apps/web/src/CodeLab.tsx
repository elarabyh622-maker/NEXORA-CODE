import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { ApiError, errorText, request, segment, type SessionScope } from './api';
import { acknowledgeDraftSave, receiveServerDraft } from './draftState';
import { useResource } from './hooks';
import { planLink } from './lessonLinks';
import type { DraftState, User } from './types';
import { ErrorBox, Loading } from './ui';
import './code-lab.css';

type LabExercise = {
  id: string;
  language: 'python' | 'javascript';
  title: string;
  prompt: string;
  starterCode: string;
  sampleInput: string;
  sampleOutput: string;
};
type LabDraft = { code: string; version: number };
type RunMode = 'run' | 'assess';
type Run = {
  id: string;
  status: 'completed' | 'timed_out' | 'output_limit' | 'code_error' | 'infrastructure_error' | 'running';
  verdict: 'not_evaluated' | 'passed' | 'needs_work';
  stdout: string;
  stderr: string;
  passedCases?: number;
  totalCases?: number;
  alreadyRecorded: boolean;
};
type RunSubmission = { mode: RunMode; code: string; input?: string; key: string; sentAt: string; runId?: string };
type LabDraftState = DraftState & { pendingRun?: RunSubmission };

export type LabEvidence = { skillId: string; exerciseId: string; awardedAt: string };

type LessonLabProps = {
  releaseId: string;
  lessonId: string;
  goalParam?: string;
  user: User | null;
  scope?: SessionScope;
  store?: Map<string, DraftState>;
  onAttempt: () => void;
};

const languages = { python: 'Python', javascript: 'JavaScript' };
const modes = { run: 'تشغيل تجريبي', assess: 'تقييم الحل' };
const encoder = new TextEncoder();
const timeFormat = new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium', timeStyle: 'short' });
const MAX_CODE_BYTES = 16_384;
const MAX_INPUT_BYTES = 4_096;

function runStatus(run: Run, mode: RunMode): string {
  switch (run.status) {
    case 'running': return 'جارٍ تنفيذ المحاولة…';
    case 'infrastructure_error': return 'تعذّر تشغيل المحاولة بسبب عطل في الخدمة. يمكنك إعادة المحاولة.';
    case 'timed_out': return 'تجاوزت المحاولة الوقت المسموح للتشغيل.';
    case 'output_limit': return 'تجاوزت المحاولة الحد المسموح للمخرجات.';
    case 'code_error': return 'توقف التنفيذ بسبب خطأ في الكود.';
    case 'completed':
      if (mode === 'run') return 'اكتمل التشغيل التجريبي.';
      if (run.verdict === 'passed') return 'اجتاز الحل حالات التقييم.';
      if (run.verdict === 'needs_work') return 'يحتاج الحل إلى مراجعة بعض الحالات.';
      return 'انتهت المحاولة دون نتيجة تقييم.';
  }
}

function waitForPoll(signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 900);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

function LabEditor({ exercise, available, releaseId, lessonId, goalParam, user, scope, store, onAttempt }: LessonLabProps & {
  exercise: LabExercise;
  available: boolean;
}) {
  const titleId = useId();
  const codeId = useId();
  const inputId = useId();
  const storeKey = `lab/${releaseId}/${exercise.id}`;
  const path = `/lab/drafts/${segment(releaseId)}/${segment(exercise.id)}`;
  const canEdit = !!user && !!scope;
  const [draft, setDraft] = useState<LabDraftState>(() => store?.get(storeKey) ??
    { answer: exercise.starterCode, version: 0, dirty: false, loaded: false });
  const currentDraft = useRef(draft);
  const lifetime = useRef<AbortController | null>(null);
  const [draftLoading, setDraftLoading] = useState(canEdit);
  const [draftReload, setDraftReload] = useState(0);
  const [autosavePaused, setAutosavePaused] = useState(false);
  const operation = useRef<'save' | 'run' | null>(null);
  const [busy, setBusy] = useState<'save' | 'run' | null>(null);
  const [draftError, setDraftError] = useState('');
  const [runError, setRunError] = useState('');
  const [input, setInput] = useState(exercise.sampleInput);
  const [result, setResult] = useState<{ run: Run; submission: RunSubmission } | null>(null);

  const updateDraft = useCallback((change: (value: LabDraftState) => LabDraftState) => {
    if (scope?.signal.aborted) return;
    const next = change(currentDraft.current);
    currentDraft.current = next;
    store?.set(storeKey, next);
    setDraft(next);
  }, [scope, store, storeKey]);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!canEdit || !scope) return;
    const controller = new AbortController();
    const active = () => !controller.signal.aborted && !scope.signal.aborted;
    setDraftLoading(true);
    setDraftError('');
    request<LabDraft>(path, { scope, signal: controller.signal }).then(saved => {
      if (active()) updateDraft(value => receiveServerDraft(
        { ...value, dirty: value.dirty && value.answer !== saved.code, remote: undefined },
        { answer: saved.code, version: saved.version },
      ));
    }).catch(error => {
      if (!active()) return;
      if (error instanceof ApiError && error.status === 404) {
        updateDraft(value => ({
          ...value, answer: value.dirty ? value.answer : exercise.starterCode,
          version: 0, loaded: true, remote: undefined,
        }));
      } else {
        updateDraft(value => ({ ...value, loaded: false }));
        setDraftError(errorText(error));
      }
    }).finally(() => { if (active()) setDraftLoading(false); });
    return () => controller.abort();
  }, [canEdit, scope, path, draftReload, updateDraft, exercise.starterCode]);

  const saveDraft = useCallback(async () => {
    const current = currentDraft.current;
    if (!scope || !lifetime.current || !current.loaded || operation.current ||
        encoder.encode(current.answer).length > MAX_CODE_BYTES) return;
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal]);
    const submitted = current.answer;
    operation.current = 'save';
    setBusy('save');
    setDraftError('');
    try {
      const saved = await request<LabDraft>(path, {
        method: 'PUT', scope, signal,
        body: { code: submitted, expectedVersion: current.remote?.version ?? current.version },
      });
      if (signal.aborted) return;
      updateDraft(value => acknowledgeDraftSave(value, submitted, { answer: saved.code, version: saved.version }));
      setAutosavePaused(false);
    } catch (error) {
      if (signal.aborted) return;
      setAutosavePaused(true);
      if (error instanceof ApiError && error.status === 409 && error.code !== 'session_changed') {
        setDraftLoading(true);
        updateDraft(value => ({ ...value, loaded: false, remote: undefined }));
        setDraftReload(value => value + 1);
      } else setDraftError(errorText(error));
    } finally {
      operation.current = null;
      if (!signal.aborted) setBusy(null);
    }
  }, [path, scope, updateDraft]);

  const codeTooLarge = encoder.encode(draft.answer).length > MAX_CODE_BYTES;
  useEffect(() => {
    if (!canEdit || busy || draftLoading || autosavePaused || !draft.loaded || !draft.dirty || draft.remote || codeTooLarge) return;
    const timer = window.setTimeout(() => void saveDraft(), 1200);
    return () => window.clearTimeout(timer);
  }, [canEdit, busy, draftLoading, autosavePaused, draft, codeTooLarge, saveDraft]);

  async function execute(submission: RunSubmission) {
    if (!scope || !lifetime.current || operation.current) return;
    const signal = AbortSignal.any([scope.signal, lifetime.current.signal]);
    operation.current = 'run';
    setBusy('run');
    setRunError('');
    setResult(null);
    const isRetry = currentDraft.current.pendingRun?.key === submission.key;
    updateDraft(value => ({ ...value, pendingRun: submission }));
    let activeRun = submission;
    try {
      let run = activeRun.runId
        ? await request<Run>(`/lab/runs/${segment(activeRun.runId)}`, { scope, signal })
        : await request<Run>('/lab/runs', {
          method: 'POST', scope, signal,
          body: {
            releaseId, lessonId, exerciseId: exercise.id, code: submission.code, mode: submission.mode,
            idempotencyKey: submission.key, ...(submission.input === undefined ? {} : { input: submission.input }),
          },
        });
      activeRun = { ...submission, runId: run.id };
      updateDraft(value => ({ ...value, pendingRun: activeRun }));
      for (let poll = 0; run.status === 'running' && poll < 24; poll++) {
        await waitForPoll(signal);
        signal.throwIfAborted();
        run = await request<Run>(`/lab/runs/${segment(run.id)}`, { scope, signal });
      }
      if (signal.aborted) return;
      if (run.status === 'running') return;
      setResult({ run, submission: activeRun });
      updateDraft(value => ({ ...value, pendingRun: undefined }));
      if (submission.mode === 'assess' && run.verdict === 'passed') onAttempt();
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && !activeRun.runId &&
          ((!isRetry && error.code === 'lab_unavailable') || (error.status >= 400 && error.status < 500))) {
        updateDraft(value => ({ ...value, pendingRun: undefined }));
      } else if (error instanceof ApiError && activeRun.runId && error.status === 404) {
        updateDraft(value => ({ ...value, pendingRun: { ...activeRun, runId: undefined } }));
      }
      setRunError(error instanceof ApiError && error.code === 'lab_unavailable'
        ? 'بيئة التشغيل غير متاحة الآن. يمكنك متابعة الدرس أو حفظ مسودتك.'
        : errorText(error));
    } finally {
      operation.current = null;
      if (!signal.aborted) setBusy(null);
    }
  }

  function start(mode: RunMode) {
    void execute({
      mode, code: draft.answer, input: mode === 'run' ? input : undefined,
      key: crypto.randomUUID(), sentAt: new Date().toISOString(),
    });
  }

  const pending = draft.pendingRun;
  const inputTooLarge = encoder.encode(input).length > MAX_INPUT_BYTES;
  const runDisabled = !available || !!busy || !!pending || !draft.answer.trim() || codeTooLarge;
  const resultIsStale = result && (draft.answer !== result.submission.code ||
    (result.submission.mode === 'run' && input !== result.submission.input));
  const draftMessage = draftLoading ? 'جارٍ قراءة المسودة المحفوظة…'
    : !draft.loaded ? 'أعد قراءة المسودة قبل الحفظ.'
    : draft.remote ? 'حُفظت نسخة أخرى أثناء عملك. قارنها مع الكود الحالي.'
    : draft.dirty && codeTooLarge ? 'اختصر الكود حتى تتمكن من حفظه.'
    : draft.dirty && autosavePaused ? 'توقف الحفظ التلقائي. اضغط على حفظ المسودة لإعادة المحاولة.'
    : draft.dirty ? 'تغييرات غير محفوظة · جارٍ انتظار الحفظ التلقائي.'
    : draft.version ? `مسودة محفوظة · النسخة ${draft.version}`
    : 'لم تحفظ مسودة لهذا التمرين بعد.';

  return <article className="lab-exercise" aria-labelledby={titleId}>
    <div className="lab-exercise-heading">
      <h3 id={titleId}>{exercise.title}</h3>
      <bdi className="lab-language" lang="en">{languages[exercise.language]}</bdi>
    </div>
    <p className="lab-prompt">{exercise.prompt}</p>
    <details className="lab-example">
      <summary>مثال على المدخلات والمخرجات</summary>
      <dl className="lab-example-values">
        <div><dt>المدخلات</dt><dd>{exercise.sampleInput ? <pre dir="ltr">{exercise.sampleInput}</pre> : 'بلا مدخلات'}</dd></div>
        <div><dt>المخرجات المتوقعة</dt><dd>{exercise.sampleOutput ? <pre dir="ltr">{exercise.sampleOutput}</pre> : 'بلا مخرجات'}</dd></div>
      </dl>
    </details>
    <div className="lab-editor">
      <label htmlFor={codeId}>الكود</label>
      <textarea id={codeId} dir="ltr" rows={8} spellCheck={false} autoCapitalize="off" autoComplete="off"
        readOnly={!canEdit} value={draft.answer} aria-invalid={codeTooLarge || undefined}
        aria-describedby={codeTooLarge ? `${codeId}-limit` : undefined}
        onChange={event => {
          const code = event.target.value;
          updateDraft(value => ({ ...value, answer: code, dirty: true }));
        }} />
      {codeTooLarge && <p id={`${codeId}-limit`} className="field-help">الكود أطول من الحد المسموح (16 كيلوبايت).</p>}
    </div>
    {!canEdit ? <p className="notice"><a href="#auth">سجّل الدخول</a> لتعديل الكود وحفظه وتشغيله.</p> : <>
      <div className="lab-draft">
        <p className="field-help" role="status">{busy === 'save' ? 'جارٍ حفظ المسودة…' : draftMessage}</p>
        <ErrorBox message={draftError} />
        {draft.remote && <aside className="notice lab-conflict">
          <h4>النسخة المحفوظة · {draft.remote.version}</h4>
          {draft.remote.answer ? <pre dir="ltr" tabIndex={0}>{draft.remote.answer}</pre> : <p>هذه النسخة فارغة.</p>}
          <div className="actions">
            <button className="btn" type="button" disabled={!!busy || draftLoading} onClick={() => {
              updateDraft(value => value.remote
                ? receiveServerDraft({ ...value, dirty: false, remote: undefined }, value.remote)
                : value);
              setAutosavePaused(false);
            }}>
              استخدام النسخة المحفوظة
            </button>
            <button className="btn" type="button" disabled={!!busy || draftLoading || codeTooLarge} onClick={saveDraft}>استبدال المحفوظة بنسختي</button>
          </div>
        </aside>}
        {!draft.remote && <button className="btn" type="button" disabled={!!busy || draftLoading || !draft.loaded || !draft.dirty || codeTooLarge} onClick={saveDraft}>حفظ المسودة</button>}
        {!draft.loaded && !draftLoading && <button className="btn" type="button" disabled={!!busy} onClick={() => setDraftReload(value => value + 1)}>إعادة قراءة المسودة</button>}
      </div>
      <div className="lab-run-controls">
        <label htmlFor={inputId}>مدخلات التشغيل التجريبي</label>
        <textarea id={inputId} dir="ltr" rows={2} spellCheck={false} autoCapitalize="off" autoComplete="off"
          value={input} onChange={event => setInput(event.target.value)}
          aria-invalid={inputTooLarge || undefined} aria-describedby={inputTooLarge ? `${inputId}-limit` : undefined} />
        {inputTooLarge && <p id={`${inputId}-limit`} className="field-help">المدخلات أطول من الحد المسموح (4 كيلوبايت).</p>}
        <p className="field-help">جرّب الكود بالمدخلات أعلاه. يختبر التقييم الحل بحالات محددة ويسجّل دليل المهارة عند اجتيازها.</p>
        <div className="actions">
          <button className="btn lab-run-button" type="button" disabled={runDisabled || inputTooLarge} onClick={() => start('run')}>جرّب الكود</button>
          <button className="btn" type="button" disabled={runDisabled} onClick={() => start('assess')}>تحقّق من الحل</button>
        </div>
      </div>
      <ErrorBox message={runError} />
      {pending && <div className="notice">
        <p role="status">{busy === 'run' ? `جارٍ تنفيذ ${modes[pending.mode]}…`
          : pending.runId ? 'يمكنك متابعة حالة المحاولة المرسلة.' : 'لم نتأكد من وصول المحاولة. يمكنك إعادة إرسالها بالمفتاح نفسه.'}</p>
        {busy !== 'run' && <button className="btn" type="button" disabled={!!busy} onClick={() => void execute(pending)}>
          {pending.runId ? 'متابعة حالة المحاولة' : 'إعادة إرسال المحاولة'}
        </button>}
      </div>}
      {result && <section className="lab-result">
        <h4>{modes[result.submission.mode]}</h4>
        <time className="field-help" dateTime={result.submission.sentAt}>{timeFormat.format(new Date(result.submission.sentAt))}</time>
        <div role="status">
          {resultIsStale && <p className="lab-stale">هذه النتيجة لنسخة سابقة من الكود أو المدخلات.</p>}
          <p>{runStatus(result.run, result.submission.mode)}</p>
          {result.submission.mode === 'assess' && result.run.passedCases != null && result.run.totalCases != null &&
            <p>اجتاز الحل {result.run.passedCases} من {result.run.totalCases} حالات.</p>}
          {result.run.alreadyRecorded && <p>هذه المحاولة مسجّلة من قبل.</p>}
        </div>
        {result.run.stdout && <div><h4>المخرجات</h4><pre dir="ltr" tabIndex={0}>{result.run.stdout}</pre></div>}
        {result.run.stderr && <div><h4>رسائل التنفيذ</h4><pre dir="ltr" tabIndex={0}>{result.run.stderr}</pre></div>}
        {result.run.status === 'completed' && result.run.verdict === 'passed' && result.submission.mode === 'assess' &&
          <div className="actions">
            <a className="btn" href="#progress">عرض دليل المهارة في تقدّمي</a>
            <a className="btn" href={planLink(goalParam)}>معاينة الخطوة التالية في خطتي</a>
          </div>}
      </section>}
    </>}
  </article>;
}

export function CodeLab({ language, ...lesson }: LessonLabProps & { language: string }) {
  const [selectedId, setSelectedId] = useState('');
  const path = `/lab/exercises/${segment(lesson.releaseId)}/${segment(lesson.lessonId)}`;
  const lab = useResource<{ available: boolean; exercises: LabExercise[] }>(path, 0, true);
  if (lab.loading) return <Loading text="جارٍ البحث عن تمارين البرمجة…" />;
  if (lab.error) return <section className="code-lab" aria-labelledby="code-lab-title">
    <h2 id="code-lab-title">مختبر البرمجة</h2>
    <ErrorBox message="تعذر تحميل المختبر. يمكنك متابعة الدرس والمحاولة مجددًا." retry={lab.reload} />
  </section>;
  if (!lab.data?.exercises.length) return null;
  const exercises = lab.data.exercises;
  const exercise = exercises.find(item => item.id === selectedId) ??
    exercises.find(item => item.language === language) ?? exercises[0];
  return <section className="code-lab" aria-labelledby="code-lab-title">
    <h2 id="code-lab-title">مختبر البرمجة</h2>
    {!lab.data.available && <div className="notice">
      <p>بيئة التشغيل غير متاحة الآن. يمكنك قراءة التمرين، وتعديل الكود وحفظه بعد تسجيل الدخول.</p>
      <button className="btn" type="button" onClick={lab.reload}>تحقّق من توفر التشغيل</button>
    </div>}
    {exercises.length > 1 && <label className="lab-picker">اختر تمرين البرمجة
      <select value={exercise.id} onChange={event => setSelectedId(event.target.value)}>
        {exercises.map(item => <option key={item.id} value={item.id}>{item.title} · {languages[item.language]}</option>)}
      </select>
    </label>}
    <LabEditor key={exercise.id} exercise={exercise} available={lab.data.available} {...lesson} />
  </section>;
}
