import { useEffect, useState } from 'react';
import { ApiError, applicationPath, errorText, request, segment, type SessionScope } from './api';
import { CodeLab } from './CodeLab';
import { useResource } from './hooks';
import { planLink } from './lessonLinks';
import { acknowledgeDraftSave, attemptKey, receiveServerDraft } from './draftState';
import type { Attempt, CurriculumProject, Draft, DraftState, Exercise as ExerciseType, Lesson as LessonType, User } from './types';
import { ErrorBox, Heading, Loading } from './ui';

export function Exercise({ exercise, releaseId, lessonId, user, scope, store, onAttempt }: { exercise: ExerciseType; releaseId: string; lessonId: string; user: User | null; scope?: SessionScope; store?: Map<string, DraftState>; onAttempt: () => void }) {
  const storeKey = `${releaseId}/${exercise.id}`;
  const path = `/me/drafts/${segment(releaseId)}/${segment(exercise.id)}`;
  const [draft, setDraft] = useState<DraftState>(() => store?.get(storeKey) ?? { answer: '', version: 0, dirty: false, loaded: false });
  const [busy, setBusy] = useState(false);
  const [draftLoading, setDraftLoading] = useState(!!user);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [hintsUsed, setHintsUsed] = useState(() => store?.get(storeKey)?.hintsUsed ?? 0);
  const [result, setResult] = useState<Attempt | null>(null);
  const [reload, setReload] = useState(0);
  function update(change: (current: DraftState) => DraftState) {
    setDraft(current => {
      if (scope?.signal.aborted) return current;
      const next = change(current);
      store?.set(storeKey, next);
      return next;
    });
  }
  useEffect(() => {
    if (!user || !scope) return;
    const controller = new AbortController();
    setDraftLoading(true);
    request<Draft>(path, { scope, signal: controller.signal }).then(remote => {
      if (controller.signal.aborted || scope.signal.aborted) return;
      update(current => receiveServerDraft(current, remote));
    }).catch(cause => {
      if (controller.signal.aborted || scope.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 404) update(current => ({ ...current, loaded: true, version: 0 }));
      else setError(errorText(cause));
    }).finally(() => { if (!controller.signal.aborted) setDraftLoading(false); });
    return () => controller.abort();
    // This component is keyed by account/release/exercise; changes never share drafts across identities.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, user?.id, scope, reload]);

  async function save() {
    if (!draft.loaded || !user || !scope || scope.signal.aborted) return;
    setBusy(true); setError(''); setNotice('');
    const submitted = draft.answer;
    try {
      const saved = await request<Draft>(path, { method: 'PUT', scope, body: { answer: submitted, expectedVersion: draft.remote?.version ?? draft.version } });
      if (scope.signal.aborted) return;
      update(current => acknowledgeDraftSave(current, submitted, saved));
      setNotice('تم حفظ المسودة في حسابك.');
    } catch (cause) {
      if (scope.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 409 && cause.code !== 'session_changed') {
        setError('حُفظت نسخة أخرى من هذه الإجابة. نصك ما زال هنا؛ قارن النسختين قبل الحفظ.');
        try { const remote = await request<Draft>(path, { scope }); update(current => ({ ...current, remote })); }
        catch (readError) { if (!scope.signal.aborted) setError(`نصك ما زال هنا. ${errorText(readError)}`); }
      } else setError(errorText(cause));
    } finally { setBusy(false); }
  }
  async function submit() {
    if (!user || !scope || scope.signal.aborted || !draft.answer.trim()) return;
    setBusy(true); setError(''); setNotice(''); setResult(null);
    const signature = JSON.stringify({ releaseId, lessonId, exerciseId: exercise.id, answer: draft.answer, hintsUsed });
    const idempotencyKey = attemptKey(draft, signature);
    update(current => ({ ...current, attempt: { signature, key: idempotencyKey } }));
    try {
      const response = await request<Attempt>('/practice/attempts', { method: 'POST', scope, body: { releaseId, lessonId, exerciseId: exercise.id, answer: draft.answer, hintsUsed, idempotencyKey } });
      if (scope.signal.aborted) return;
      setResult(response); onAttempt();
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="exercise" aria-labelledby={`exercise-${exercise.id}`}>
    <p className="eyebrow">{exercise.independent ? 'جرّب الفكرة في موقف جديد' : 'تدرب خطوة بخطوة'}</p>
    <h3 id={`exercise-${exercise.id}`}>{exercise.prompt}</h3>
    <fieldset disabled={!user || busy}>
      <legend className="sr-only">إجابة التمرين</legend>
      {exercise.type === 'choice' ? <div className="choice-options">{exercise.options.map(option => <label className="choice" key={option.id}>
        <input type="radio" name={exercise.id} value={option.id} checked={draft.answer === option.id} onChange={e => { update(current => ({ ...current, answer: e.target.value, dirty: true })); setResult(null); setNotice(''); }} /><span>{option.text}</span>
      </label>)}</div> : <label>إجابتك<textarea rows={3} maxLength={4096} value={draft.answer} onChange={e => { const answer = e.target.value; update(current => ({ ...current, answer, dirty: true })); setResult(null); setNotice(''); }} /></label>}
    </fieldset>
    {!user ? <p className="notice">يمكنك قراءة التمرين الآن. <a href="#auth">سجّل الدخول</a> لتصحيح إجابتك وحفظ تقدمك.</p> : <>
      <p className="field-help" role="status">{draftLoading ? 'جارٍ قراءة المسودة المحفوظة…' : !draft.loaded ? 'لم نتمكن من قراءة مسودتك؛ أعد تحميلها قبل الحفظ.' : draft.dirty ? 'لديك نص غير محفوظ. يبقى أثناء التنقل هنا، واحفظه قبل إغلاق الصفحة.' : draft.version > 0 ? `مسودة محفوظة · النسخة ${draft.version}` : 'لم تحفظ مسودة بعد.'}</p>
      {draft.remote && <aside className="notice conflict"><h4>النسخة المحفوظة الأخرى · {draft.remote.version}</h4><p className="preserve-text">{exercise.options.find(option => option.id === draft.remote?.answer)?.text ?? (draft.remote.answer || 'إجابة فارغة')}</p><p>إجابتك الحالية أعلاه لم تتغير. حفظ نسختك سيستبدل هذه النسخة.</p></aside>}
      <div className="actions"><button className="btn primary" disabled={busy || !draft.answer.trim()} onClick={submit}>{busy ? 'جارٍ تنفيذ الطلب…' : 'تحقق من إجابتي'}</button><button className="btn" disabled={busy || draftLoading || !draft.loaded || (!draft.dirty && !draft.remote)} onClick={save}>{draft.remote ? 'حفظ نسختي بدل المحفوظة' : 'حفظ المسودة'}</button>
        {!draft.loaded && !draftLoading && <button className="btn" disabled={busy} onClick={() => { setError(''); setReload(value => value + 1); }}>إعادة قراءة المسودة</button>}
      </div>
    </>}
    {exercise.hints.length > hintsUsed && <button className="btn text" disabled={busy} onClick={() => { const next = hintsUsed + 1; setHintsUsed(next); update(current => ({ ...current, hintsUsed: next })); }}>أحتاج تلميحًا ({hintsUsed + 1}/{exercise.hints.length})</button>}
    {exercise.hints.slice(0, hintsUsed).map((hint, index) => <p key={index} className="hint">{hint}</p>)}
    <ErrorBox message={error} />
    {notice && <p className="feedback" role="status">{notice}</p>}
    {result && <div className={`feedback ${result.correct ? 'success' : 'retry'}`} role="status"><strong>{result.correct ? 'إجابة صحيحة' : 'جرّب مرة أخرى'}</strong><p>{result.explanation}</p>{result.assisted && <p>استعنت بتلميح في هذه المحاولة.</p>}{result.alreadyRecorded && <p>هذه المحاولة محفوظة بالفعل؛ لم تُحتسب مرتين.</p>}</div>}
  </section>;
}

export function Lesson({ releaseId, lessonId, goalParam, user, scope, language, store, project, onAttempt }: { releaseId: string; lessonId: string; goalParam?: string; user: User | null; scope?: SessionScope; language: string; store?: Map<string, DraftState>; project?: CurriculumProject; onAttempt: () => void }) {
  const resource = useResource<LessonType>(`/content/${segment(releaseId)}/lessons/${segment(lessonId)}`, 0, false, scope);
  if (resource.loading) return <Loading />;
  if (resource.error) return <ErrorBox message={resource.error} retry={resource.reload} />;
  const lesson = resource.data;
  if (!lesson) return null;
  const exampleLanguages = lesson.examples.map(example => example.language).filter(item => item !== 'text');
  const exampleLanguage = exampleLanguages.includes(language) ? language : exampleLanguages[0] ?? language;
  return <><div className="breadcrumbs"><a href={planLink(goalParam)}>خطتي التعليمية</a><span aria-hidden="true">/</span><span>{lesson.title}</span></div>
    <Heading title={lesson.title} eyebrow={`${lesson.minutes} دقيقة تقريبًا · على مهلك`}>{lesson.summary}</Heading>
    <div className="lesson-layout"><article className="panel lesson-body"><section className="objectives"><h2>بعد هذه الخطوة، تستطيع أن…</h2><ul>{lesson.objectives.map(item => <li key={item}>{item}</li>)}</ul></section>
      {lesson.sections.filter(section => !section.language || section.language === exampleLanguage).map((section, index) => <section className="lesson-section" key={index}><h2>{section.heading}</h2><p>{section.body}</p></section>)}
      {lesson.examples.filter(example => example.language === 'text' || example.language === exampleLanguage).map((example, index) => <section className="example" key={index}><h2>{example.title}</h2><pre dir={example.language === 'text' ? 'auto' : 'ltr'}><code>{example.code}</code></pre><p>{example.explanation}</p></section>)}
      {project && <section className="lesson-section objectives" aria-label="المشروع التطبيقي">
        <h2>{project.title}</h2><p>{project.summary}</p>
        <ul>{project.criteria.map(criterion => <li key={criterion}>{criterion}</li>)}</ul>
        {project.download && <div className="actions"><a className="btn" href={applicationPath(project.download)} download>نزّل ملفات البداية</a></div>}
      </section>}
      <section className="exercise-list"><h2>الآن دورك</h2><p className="muted">فكر وتتبع الخطوات. بعد إرسال الإجابة، يصححها النظام ويحفظ المحاولة في حسابك.</p>{lesson.exercises.map(exercise => <Exercise key={`${user?.id ?? 'guest'}/${releaseId}/${exercise.id}`} {...{ exercise, releaseId, lessonId, user, scope, store, onAttempt }} />)}</section>
      <CodeLab {...{ releaseId, lessonId, goalParam, user, scope, language, store, onAttempt }} />
      <aside className="takeaway"><h2>الفكرة التي تأخذها معك</h2><p>{lesson.takeaway}</p></aside>
    </article><aside className="panel side-summary"><h2>لماذا هذه الخطوة؟</h2><p>{lesson.why}</p><hr /><h3>اقرأ، ثم تتبع</h3><p>تتبّع الأمثلة خطوة بخطوة وتوقّع نتيجتها قبل قراءة الشرح.</p><a className="btn" href={planLink(goalParam)}>راجع الخطوة التالية في خطتك</a></aside></div>
  </>;
}
