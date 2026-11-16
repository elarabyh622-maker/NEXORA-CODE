import { useEffect, useState } from 'react';
import { ApiError, errorText, request, segment, type SessionScope } from './api';
import type { LabEvidence } from './CodeLab';
import { useResource } from './hooks';
import { lessonLink } from './lessonLinks';
import type { Content, Goal, Plan, Progress, Revision, SavedPlan, User } from './types';
import { ErrorBox, Heading, Icon, Loading } from './ui';

export function PlanSteps({ plan, content, currentRelease }: { plan: Plan; content: Content | null; currentRelease: string }) {
  const exampleLanguage = content?.sample.tracks && plan.goalId === 'web' ? 'javascript' : undefined;
  return <><ol className="plan-list">{plan.steps.map((step, index) => {
    const lesson = content?.sample.lessons.find(item => item.id === step.lessonId);
    return <li className="plan-step" key={step.lessonId}><span className="step-number" aria-hidden="true">{index + 1}</span><div><h3>{lesson?.title ?? step.lessonId}</h3><p className="muted">{lesson?.summary}</p><p className="reason">{step.reason}</p>{plan.releaseId === currentRelease && <a className="btn compact" href={lessonLink(step.lessonId, plan.releaseId, exampleLanguage, plan.goalId)}>افتح الدرس <Icon name="arrow" /></a>}</div></li>;
  })}</ol>{plan.steps.length === 0 && <p className="notice">لا توجد خطوات جديدة في هذه الخطة وفق الممارسة المسجلة. يمكنك الرجوع إلى الدروس للمراجعة.</p>}
    {plan.uncoveredSkillIds.length > 0 && <p className="notice">بعض مهارات هذا الهدف لم يتوفر محتواها بعد. الخطة المعروضة تغطي الجزء المتاح فقط.</p>}
  </>;
}

export function PlanPage({ content, releaseId, user, scope, onRelease, refreshProgress, initialGoal }: { content: Content | null; releaseId: string; user: User | null; scope: SessionScope; onRelease: (id: string) => void; refreshProgress: number; initialGoal?: string }) {
  const goals = content?.graph.goals ?? [];
  const [goalId, setGoalId] = useState(goals.find(goal => goal.id === initialGoal)?.id ?? goals[0]?.id ?? '');
  const [preview, setPreview] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [historyPlan, setHistoryPlan] = useState<SavedPlan | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [conflicted, setConflicted] = useState(false);
  const [version, setVersion] = useState(0);
  const current = useResource<SavedPlan>(user ? '/me/plan' : null, version, true, scope);
  const history = useResource<{ revisions: Revision[] }>(user ? '/me/plan/history' : null, version, false, scope);
  const [previewTick, setPreviewTick] = useState(0);
  useEffect(() => {
    setPreview(null); setError(''); setNotice('');
    if (!goalId || !content) return;
    const controller = new AbortController();
    const active = () => !controller.signal.aborted && !scope.signal.aborted;
    setBusy(true);
    request<Plan>('/plan-previews', { method: 'POST', scope, signal: controller.signal, body: { releaseId, goalId } })
      .then(plan => { if (active()) setPreview(plan); })
      .catch(cause => { if (active()) setError(errorText(cause)); }).finally(() => { if (active()) setBusy(false); });
    return () => controller.abort();
  }, [releaseId, goalId, scope, content, refreshProgress, previewTick]);
  async function save() {
    if (!user || !preview || current.loading || current.error) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await request<SavedPlan>('/learning-plans', { method: 'POST', scope, body: {
        releaseId, goalId, ...(current.data ? { expectedCurrentRevision: current.data.revision } : {}),
      } });
      if (scope.signal.aborted) return;
      setNotice(`تم حفظ الخطة · المراجعة ${saved.revision}. يمكنك الرجوع إلى المراجعات السابقة أدناه.`);
      setVersion(value => value + 1); setConflicted(false);
    } catch (cause) {
      if (scope.signal.aborted) return;
      setError(errorText(cause));
      if (cause instanceof ApiError && cause.status === 409) { setConflicted(true); setVersion(value => value + 1); }
    } finally { setBusy(false); }
  }
  async function openRevision(id: string) {
    setHistoryBusy(true); setError('');
    try {
      const plan = await request<SavedPlan>(`/learning-plans/${segment(id)}`, { scope });
      if (!scope.signal.aborted) setHistoryPlan(plan);
    }
    catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setHistoryBusy(false); }
  }
  const goal = goals.find(item => item.id === goalId);
  return <><Heading title="طريق واضح، خطوة بخطوة" eyebrow="خطتي التعليمية">اختر هدفًا، وافهم سبب كل خطوة. حفظ هدف جديد ينشئ مراجعة تحتفظ بما سبقها.</Heading>
    <div className="split"><div className="stack">{content ? <section className="panel"><label>ما الذي تريد استكشافه؟<select value={goalId} onChange={event => { setGoalId(event.target.value); setConflicted(false); }} disabled={busy}>{goals.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><p className="muted">{goal?.description}</p>{goal?.status === 'planned' && <p className="notice">هذا الهدف مخطط. يمكنك دراسة المقدمة المتاحة. محتوى التخصص لم يُبنَ بعد.</p>}</section> : releaseId && <p className="notice">لا يتوفر محتوى هذا الإصدار للقراءة الآن. يمكنك الاطلاع على خطتك المحفوظة وتاريخها.</p>}
      <ErrorBox message={error} retry={() => setPreviewTick(value => value + 1)} />
      {busy && <Loading text="جارٍ إعداد خطتك…" />}
      {preview && <section aria-label="معاينة الخطة"><div className="section-title"><h2>معاينة خطتك</h2><span className="pill">{preview.steps.length} خطوات متاحة</span></div><PlanSteps plan={preview} content={content} currentRelease={releaseId} /></section>}
      {user ? <><ErrorBox message={current.error} retry={current.reload} />{current.loading && <Loading text="جارٍ قراءة خطتك المحفوظة…" />}{conflicted && <p className="notice">تمت قراءة أحدث خطة. راجعها أدناه قبل حفظ اختيارك كمراجعة جديدة.</p>}{content && <button className="btn primary" disabled={busy || !preview || current.loading || !!current.error} onClick={save}>{current.data ? 'حفظ الاختيار كمراجعة جديدة' : 'حفظ خطتي'}</button>}</> : content && <p className="notice"><a href="#auth">سجّل الدخول</a> لحفظ هذه الخطة والعودة إليها من حسابك.</p>}
      {notice && <p className="feedback success" role="status">{notice}</p>}
    </div><aside className="stack"><section className="panel side-summary"><h2>كل خطوة لها سبب</h2><p>المعاينة تستفيد من التمارين التي مارستها في هذا الإصدار. القراءة وحدها لا تغير تقدمك.</p>{content && <p>يضم هذا الإصدار {content.sample.lessons.length} درسًا.</p>}</section>
      {current.data && <section className="panel side-summary"><h2>خطتك المحفوظة</h2><p>المراجعة {current.data.revision}</p><p>{goals.find(item => item.id === current.data?.goalId)?.title ?? current.data.goalId}</p><p className="field-help">الإصدار: <bdi>{current.data.releaseId}</bdi></p>{current.data.releaseId !== releaseId && <><p>هذه الخطة مرتبطة بإصدار آخر. لم نغيّرها عند نشر محتوى جديد.</p><button className="btn" onClick={() => onRelease(current.data!.releaseId)}>عرض إصدار الخطة</button></>}<details><summary>عرض الخطوات المحفوظة</summary><PlanSteps plan={current.data.plan} content={current.data.releaseId === releaseId ? content : null} currentRelease={content ? releaseId : ''} /></details></section>}
    </aside></div>
    {user && <section className="panel history"><h2>تاريخ خطتك</h2><ErrorBox message={history.error} retry={history.reload} />{history.loading && <Loading />}{history.data?.revisions.length === 0 && <p className="muted">لم تحفظ خطة بعد.</p>}<ul className="revision-list">{history.data?.revisions.map(item => <li key={item.id}><div><strong>المراجعة {item.revision}</strong><p>{goals.find(goal => goal.id === item.goalId)?.title ?? item.goalId} · <bdi>{item.releaseId}</bdi></p><time dateTime={item.createdAt}>{new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(item.createdAt))}</time></div><button className="btn compact" disabled={historyBusy} onClick={() => openRevision(item.id)}>عرض المراجعة</button></li>)}</ul>
      {historyPlan && <div className="history-detail"><h3>المراجعة {historyPlan.revision}</h3><p className="muted">الإصدار <bdi>{historyPlan.releaseId}</bdi></p><PlanSteps plan={historyPlan.plan} content={historyPlan.releaseId === releaseId ? content : null} currentRelease={content ? releaseId : ''} />{historyPlan.releaseId !== releaseId && <button className="btn" onClick={() => onRelease(historyPlan.releaseId)}>عرض محتوى هذا الإصدار</button>}<button className="btn text" onClick={() => setHistoryPlan(null)}>إغلاق المعاينة</button></div>}
    </section>}
  </>;
}

export function ProgressPage({ user, scope, releaseId, content, revision }: { user: User | null; scope?: SessionScope; releaseId: string; content: Content; revision: number }) {
  const resource = useResource<Progress>(user ? `/me/progress?releaseId=${segment(releaseId)}` : null, revision, false, scope);
  const evidence = useResource<LabEvidence[]>(user && scope ? `/lab/evidence?releaseId=${segment(releaseId)}` : null, revision, true, scope);
  const labSkills = new Set(evidence.data?.map(item => item.skillId));
  return <><Heading title="أثر خطواتك الصغيرة" eyebrow="تقدمي">سجل التمارين وتقييمات المختبر لهذا الإصدار من المحتوى.</Heading>
    {!user ? <section className="panel empty"><Icon name="chart" /><h2>احفظ محاولاتك في حسابك</h2><p>يمكنك استكشاف الدروس دون حساب. سجّل الدخول لتظهر ممارستك هنا.</p><a className="btn primary" href="#auth">تسجيل الدخول</a></section> : <><ErrorBox message={resource.error} retry={resource.reload} />{resource.loading && <Loading />}{resource.data && <>
      <div className="stats"><section className="panel stat"><strong>{resource.data.solved} / {resource.data.total}</strong><span>تمارين أجبت عنها بشكل صحيح</span></section><section className="panel stat"><strong>{resource.data.completedLessonIds.length}</strong><span>دروس اكتملت تمارينها</span></section><section className="panel stat"><strong>{resource.data.attemptsCount}</strong><span>محاولات محفوظة</span></section></div>
      <p className="notice">هذا سجل ممارسة أولي، وليس شهادة إتقان. حل التمرين الصحيح أكثر من مرة لا يزيد عدد التمارين المحلولة.</p>
      <div className="split"><section className="panel"><h2>درسًا بعد درس</h2>{resource.data.lessons.map(item => <div className="lesson-progress" key={item.lessonId}><div className="section-title"><h3>{content.sample.lessons.find(lesson => lesson.id === item.lessonId)?.title ?? item.lessonId}</h3><span className="pill">{item.complete ? 'اكتملت التمارين' : 'قيد الممارسة'}</span></div><progress aria-label={`تقدم ${content.sample.lessons.find(lesson => lesson.id === item.lessonId)?.title ?? item.lessonId}`} max={Math.max(item.total, 1)} value={item.solved} /><p>{item.solved} من {item.total} تمارين</p><a className="btn compact" href={lessonLink(item.lessonId, releaseId)}>مراجعة الدرس</a></div>)}</section><section className="panel side-summary"><h2>المهارات التي تمرنت عليها</h2><ul className="skill-list">{resource.data.skills.map(item => <li key={item.skillId}><span>{content.graph.skills.find(skill => skill.id === item.skillId)?.title ?? item.skillId}</span><span className="pill">{labSkills.has(item.skillId) ? 'دليل من المختبر' : item.status === 'practiced' ? 'مارستها' : 'لم تُمارس بعد'}</span></li>)}</ul></section></div>
    </>}
      {(evidence.loading || evidence.error || evidence.data) && <section className="panel lab-evidence">
        <h2>أدلة المهارة من المختبر</h2>
        <ErrorBox message={evidence.error} retry={evidence.reload} />
        {evidence.loading && <Loading text="جارٍ قراءة أدلة المهارة…" />}
        {evidence.data?.length === 0 && <p className="muted">ستظهر أدلة المهارة هنا بعد اجتياز تقييمات المختبر.</p>}
        {!!evidence.data?.length && <ul className="skill-list">{evidence.data.map(item => <li key={`${item.skillId}/${item.exerciseId}`}>
          <span>{content.graph.skills.find(skill => skill.id === item.skillId)?.title ?? <bdi>{item.skillId}</bdi>}</span>
          <time dateTime={item.awardedAt}>{new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium' }).format(new Date(item.awardedAt))}</time>
        </li>)}</ul>}
        {!!evidence.data?.length && <a className="btn" href="#plan">معاينة الخطوة التالية في خطتي</a>}
      </section>}
    </>}
  </>;
}

export function GoalCards({ goals, curriculum = false }: { goals: Goal[]; curriculum?: boolean }) {
  return <div className="goals">{goals.map(goal => <a key={goal.id} className="goal" href={`#plan/${segment(goal.id)}`}><div className="goal-top"><Icon name="route" /><span className={`pill ${goal.status === 'planned' ? '' : 'sample'}`}>{goal.status === 'planned' ? 'مخطط' : curriculum ? 'متاح للتعلّم' : 'عينة متاحة'}</span></div><h3>{goal.title}</h3><p>{goal.description}</p><span className="goal-link">استكشف الخطة <Icon name="arrow" /></span></a>)}</div>;
}
