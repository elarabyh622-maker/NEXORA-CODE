import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { AccessGate, OffersPage, useAccess } from './Access';
import { applicationPath, errorText, request, segment } from './api';
import { Auth } from './Auth';
import { BRAND_ASSETS, BrandWordmark, PRODUCT_DESCRIPTOR, PRODUCT_NAME } from './brand';
import { exampleLanguageLabels, isLocalExampleLanguage } from './exampleLanguages';
import { useResource } from './hooks';
import { lessonLink, linkedLessonRelease } from './lessonLinks';
import { catalogReleaseOptions } from './releaseSelection';
import type { Catalog, ContentOverview, ExampleLanguage, Goal, LessonOverview } from './types';
import { ErrorBox, Heading, Icon, Loading } from './ui';
import { useSession } from './useSession';

const Admin = lazy(() => import('./Admin').then(module => ({ default: module.Admin })));
const AccountSettings = lazy(() => import('./AccountSettings').then(module => ({ default: module.AccountSettings })));
const AccountOperations = lazy(() => import('./AccountOperations').then(module => ({ default: module.AccountOperations })));
const CommercialSettings = lazy(() => import('./CommercialSettings').then(module => ({ default: module.CommercialSettings })));
const Lesson = lazy(() => import('./Lesson').then(module => ({ default: module.Lesson })));
const PlanPage = lazy(() => import('./Plans').then(module => ({ default: module.PlanPage })));
const ProgressPage = lazy(() => import('./Plans').then(module => ({ default: module.ProgressPage })));

function useRoute() {
  const [hash, setHash] = useState(window.location.hash || '#start');
  useEffect(() => { const change = () => setHash(window.location.hash || '#start'); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  return hash.slice(1).split('/');
}

function GoalCards({ goals, curriculum = false }: { goals: Goal[]; curriculum?: boolean }) {
  return <div className="goals">{goals.map(goal => <a key={goal.id} className="goal" href={`#plan/${segment(goal.id)}`}><div className="goal-top"><Icon name="route" /><span className={`pill ${goal.status === 'planned' ? '' : 'sample'}`}>{goal.status === 'planned' ? 'مخطط' : curriculum ? 'متاح للتعلّم' : 'عينة متاحة'}</span></div><h3>{goal.title}</h3><p>{goal.description}</p><span className="goal-link">استكشف الخطة <Icon name="arrow" /></span></a>)}</div>;
}

function LessonCards({ lessons, releaseId }: { lessons: LessonOverview[]; releaseId: string }) {
  return <div className="lesson-cards">{lessons.map((lesson, index) => (
    <a className="panel lesson-card" key={lesson.id} href={lessonLink(lesson.id, releaseId)}>
      <span className="step-number">{index + 1}</span><h3>{lesson.title}</h3>
      <p>{lesson.summary}</p><span className="field-help">{lesson.minutes} دقيقة تقريبًا</span>
    </a>
  ))}</div>;
}

function UnlockedLessons({ lessons, releaseId }: { lessons: LessonOverview[]; releaseId: string }) {
  return <section aria-labelledby="unlocked-lessons"><div className="section-title"><h2 id="unlocked-lessons">دروسك المفعّلة</h2></div>
    {lessons.length ? <LessonCards lessons={lessons} releaseId={releaseId} /> : <p className="muted">لا توجد دروس مفعّلة لحسابك في هذا الإصدار.</p>}
  </section>;
}

export default function App() {
  const [route, routeParam, routeRelease, routeLanguage, routeGoal] = useRoute();
  let planGoal: string | undefined = routeParam;
  if (route === 'plan' && routeParam) {
    try { planGoal = decodeURIComponent(routeParam); } catch { planGoal = undefined; }
  }
  const { session, checking, error: sessionError, refresh, authenticationChanged, hasUnsavedDrafts } = useSession();
  const user = session?.user ?? null;
  const [logoutError, setLogoutError] = useState('');
  const [sessionNotice, setSessionNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [planReleaseId, setPlanReleaseId] = useState('');
  const [preferredLanguage, setLanguage] = useState<ExampleLanguage>();
  const linkedLanguage = route === 'lesson' && (routeLanguage === 'javascript' || isLocalExampleLanguage(routeLanguage)) ? routeLanguage : undefined;
  const [progressRevision, setProgressRevision] = useState(0);
  const [catalogTick, setCatalogTick] = useState(0);
  const refreshOffersOnExit = useRef(false);
  const catalog = useResource<Catalog>('/catalog', catalogTick);
  const commercial = catalog.data?.accessRequired === true;
  const commercialSettings = commercial && Array.isArray(catalog.data?.offers);
  const reserveOffersLink = catalog.loading && applicationPath('/') === '/nexora-commercial/';
  const access = useAccess(commercial, session?.scope);
  const canReadContent = !!catalog.data && (!commercial || (!checking && access.active));
  const scopedAccess = commercial && (access.goalIds !== undefined || access.lessonIds !== undefined);
  const { published, activeId } = catalogReleaseOptions(catalog.data);
  const lessonRelease = route === 'lesson' ? linkedLessonRelease(routeParam, routeRelease) : null;
  const linkedReleaseId = lessonRelease && published.some(item => item.releaseId === lessonRelease) ? lessonRelease : null;
  const releaseId = linkedReleaseId ?? (route === 'plan' && planReleaseId ? planReleaseId : activeId);
  const needsContent = !['auth', 'admin', 'users', 'offers'].includes(route);
  const content = useResource<ContentOverview>(releaseId && canReadContent && needsContent ? `/content/${segment(releaseId)}?view=overview` : null,
    catalogTick + (commercial ? (session?.generation ?? 0) + access.version : 0), false, commercial ? session?.scope : undefined);
  const lesson = route === 'lesson' ? content.data?.sample.lessons.find(item => segment(item.id) === routeParam) : undefined;
  const exampleLanguages = lesson?.exampleLanguages ?? lesson?.examples?.map(example => example.language);
  const localLessonLanguage = exampleLanguages?.find(value => isLocalExampleLanguage(value) &&
    exampleLanguages.every(example => example === value || example === 'text'));
  const fixedLanguage = isLocalExampleLanguage(localLessonLanguage) && localLessonLanguage !== 'csharp' ? localLessonLanguage : undefined;
  const language = fixedLanguage ?? preferredLanguage ?? linkedLanguage ??
    (localLessonLanguage === 'csharp' ? localLessonLanguage : 'python');
  const mainRef = useRef<HTMLElement>(null);
  const [startupComplete, setStartupComplete] = useState(false);
  const startupReady = !checking && !catalog.loading && !access.loading && !content.loading;
  const management = !!user && ['Author', 'Reviewer', 'Admin'].includes(user.role);
  const canManageAccess = commercialSettings && user?.role === 'Admin';
  const reloadCatalog = () => setCatalogTick(value => value + 1);
  useEffect(() => { if (startupReady) setStartupComplete(true); }, [startupReady]);
  useEffect(() => {
    if (route === 'users' || !refreshOffersOnExit.current) return;
    refreshOffersOnExit.current = false;
    setCatalogTick(value => value + 1);
  }, [route]);
  useEffect(() => { if (route === 'start') setPlanReleaseId(''); }, [route]);
  useEffect(() => { mainRef.current?.focus(); window.scrollTo({ top: 0, behavior: 'instant' }); }, [route, routeParam]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (hasUnsavedDrafts()) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [hasUnsavedDrafts]);
  async function refreshProtection() {
    setSessionNotice('');
    setLogoutError('');
    if (await refresh(true)) setSessionNotice('تم التحقق من الحساب وتحديث حماية الجلسة.');
  }
  async function logout() {
    if (!session?.user) return;
    setBusy(true); setLogoutError(''); setSessionNotice('');
    try {
      await request('/auth/logout', { method: 'POST', scope: session.scope });
      const verified = await authenticationChanged();
      if (verified && !verified.user) window.location.hash = '#start';
    }
    catch (cause) { if (!session.scope.signal.aborted) setLogoutError(errorText(cause)); }
    finally { setBusy(false); }
  }
  function passwordUpdated() {
    setSessionNotice('تم حفظ كلمة المرور الجديدة. سجّل الدخول بها لمتابعة حسابك.');
    window.location.hash = '#auth';
    void authenticationChanged();
  }
  const navigation = [ ['start', 'نقطة البداية', 'home'], ['plan', 'خطتي التعليمية', 'route'], ['progress', 'تقدمي', 'chart'], ['glossary', 'قاموس المصطلحات', 'book'] ] as const;
  const selected = route === 'lesson' ? 'plan' : route;
  function page() {
    if (route === 'auth') {
      if (checking) return <Loading text="جارٍ التحقق من الجلسة…" />;
      if (!session) return null;
      if (user) return <AccountSettings key={session.generation} user={user} scope={session.scope} commercial={commercial}
        active={access.active && !access.loading} goals={catalog.data?.goals ?? []} onPasswordChanged={passwordUpdated} />;
      return <Auth key={session.generation} commercial={commercial} scope={session.scope} recovering={routeParam === 'recover'}
        contactUrl={catalog.data?.contactUrl} onPasswordReset={passwordUpdated} onIdentity={async id => {
          const matched = (await authenticationChanged())?.user?.id === id;
          if (matched) setSessionNotice('');
          return matched;
        }} />;
    }
    if (route === 'offers') {
      if (catalog.loading) return <Loading text="جارٍ قراءة أسعار المسارات…" />;
      if (catalog.error) return <ErrorBox message={catalog.error} retry={catalog.reload} />;
      if (commercialSettings && catalog.data) return <OffersPage catalog={catalog.data} user={user} scope={session?.scope} />;
      return <><Heading title="أسعار المسارات" /><a className="btn" href="#start">العودة إلى نقطة البداية</a></>;
    }
    if (route === 'users') {
      if (checking || catalog.loading) return <Loading />;
      if (canManageAccess && session && routeParam === 'requests') return <AccountOperations key={session.generation}
        scope={session.scope} goals={catalog.data?.goals ?? []} />;
      if (canManageAccess && session) return <CommercialSettings key={session.generation} scope={session.scope} onOffersChanged={() => { refreshOffersOnExit.current = true; }} />;
      return <><Heading title="إعدادات المستخدمين" /><p className="notice">هذه الصفحة متاحة لإدارة المنصة. <a href="#auth">الانتقال إلى الحساب</a></p></>;
    }
    if (route === 'admin') {
      if (checking) return <Loading />;
      if (management && user && session) return <Admin key={session.generation} commercial={commercial} commercialSettings={commercialSettings} user={user} scope={session.scope} onPublished={reloadCatalog} />;
      return <><Heading title="مساحة فريق المحتوى" /><p className="notice">هذه المساحة متاحة للحسابات المصرح لها بمراجعة المحتوى. <a href="#auth">الانتقال إلى الحساب</a></p></>;
    }
    if (commercial && (!access.active || checking)) {
      return checking ? <Loading text="جارٍ التحقق من الحساب…" /> : <AccessGate user={user} catalog={catalog.data!} loading={access.loading} error={access.error} reload={access.reload} />;
    }
    const restricted = () => <AccessGate user={user} catalog={catalog.data!} loading={access.loading} error={access.error} reload={access.reload} unavailable />;
    if (route === 'plan') {
      if (checking || catalog.loading || content.loading) return <Loading text="جارٍ قراءة الخطة والمحتوى…" />;
      if (scopedAccess && planGoal && !access.goalIds?.includes(planGoal)) return restricted();
      if (scopedAccess && content.data && !content.data.graph.goals.length)
        return <><Heading title="تابع تعلّمك" /><UnlockedLessons lessons={content.data.sample.lessons} releaseId={releaseId} /></>;
      return <><ErrorBox message={catalog.error} retry={catalog.reload} /><ErrorBox message={content.error} retry={content.reload} />
        {catalog.data && !releaseId && <p className="notice">لا يوجد محتوى مفعّل متاح الآن.</p>}
        {session && <PlanPage key={`${releaseId}/${session.generation}/${planGoal ?? ''}/${access.version}`} content={content.data} releaseId={releaseId} user={user} scope={session.scope} refreshProgress={progressRevision} onRelease={setPlanReleaseId} initialGoal={planGoal} allowedGoalIds={scopedAccess ? access.goalIds ?? [] : undefined} />}
      </>;
    }
    if (catalog.loading || (releaseId && content.loading)) return <Loading />;
    if (catalog.error) return <ErrorBox message={catalog.error} retry={catalog.reload} />;
    if (content.error) return <ErrorBox message={content.error} retry={content.reload} />;
    if (!releaseId || !content.data) return <section className="panel empty"><Heading title="نجهز خطوتك الأولى" /><p>لا يوجد محتوى منشور متاح الآن. حاول مجددًا لاحقًا.</p><button className="btn" onClick={catalog.reload}>تحديث المحتوى</button></section>;
    const data = content.data;
    if (route === 'progress') return checking ? <Loading /> : <ProgressPage key={session?.generation} user={user} scope={session?.scope} releaseId={releaseId} content={data} revision={progressRevision} />;
    if (route === 'lesson' && routeParam) {
      if (lessonRelease && lessonRelease !== releaseId)
        return <ErrorBox message="هذا الدرس غير متاح من الرابط الحالي. ارجع إلى خطتك لفتح الدروس المتاحة." />;
      let lessonId: string;
      try { lessonId = decodeURIComponent(routeParam); } catch { return <ErrorBox message="رابط الدرس غير صحيح. ارجع إلى الخطة واختر الدرس مجددًا." />; }
      if (scopedAccess && !data.sample.lessons.some(lesson => lesson.id === lessonId)) return restricted();
      const project = data.sample.projects?.find(item => item.lessonId === lessonId);
      return checking ? <Loading /> : <Lesson key={`${releaseId}/${session?.generation ?? 'public'}/${lessonId}`} releaseId={releaseId} lessonId={lessonId} goalParam={routeGoal} user={user} scope={session?.scope} language={language} store={session?.drafts} project={project} onAttempt={() => setProgressRevision(value => value + 1)} />;
    }
    if (route === 'glossary') return <><Heading title="كلمات جديدة، بمعنى واضح" eyebrow="قاموس المصطلحات">ارجع إلى هذه المعاني كلما احتجت. لا تحتاج إلى حفظها كلها دفعة واحدة.</Heading><dl className="glossary">{data.sample.glossary.map(item => <div className="panel" key={item.term}><dt>{item.term} <span lang="en" dir="ltr">{item.technical}</span></dt><dd>{item.definition}</dd></div>)}</dl></>;
    if (route !== 'start') return <><Heading title="لم نجد هذه الصفحة" /><a className="btn primary" href="#start">العودة إلى نقطة البداية</a></>;
    const goals = scopedAccess ? data.graph.goals.filter(goal => access.goalIds?.includes(goal.id)) : data.graph.goals;
    return <>
      {commercial && <p className="feedback success" role="status">الوصول مفعّل لحسابك. يمكنك متابعة خطتك ودروسك.</p>}
      <section className="hero" aria-labelledby="start-title">
        <div className="hero-copy">
          <h1 id="start-title">{PRODUCT_DESCRIPTOR}<br />من الصفر</h1>
          <p>اختر لغة أو تخصصًا يناسب هدفك. سنرتّب لك ما تحتاج إلى فهمه أولًا، ونرشدك إلى خطوتك التالية.</p>
          <a className="btn primary" href="#plan">{scopedAccess && !goals.length ? 'افتح دروسك' : 'استكشف خطتك'} <Icon name="arrow" /></a>
        </div>
        <div className="hero-art">
          <BrandWordmark />
        </div>
      </section>
      {!!goals.length && <section aria-labelledby="start-goals">
        <div className="section-title"><h2 id="start-goals">اختر نقطة البداية</h2></div>
        <GoalCards goals={goals} curriculum={!!data.sample.tracks} />
      </section>}
      <section className="panel intro"><h2>{data.sample.title}</h2><p>{data.sample.intro}</p></section>
      {scopedAccess ? <UnlockedLessons lessons={data.sample.lessons} releaseId={releaseId} /> : <section aria-labelledby="sample-lessons">
        <div className="section-title"><h2 id="sample-lessons">{data.sample.tracks ? 'وحدات المنهج' : 'دروس العينة'}</h2></div>
        {data.sample.tracks ? data.sample.tracks.map((track, index) => (
          <details className="panel curriculum-track" key={track.id} open={index === 0}>
            <summary>{track.title} · {track.lessonIds.length} درسًا</summary>
            <LessonCards lessons={data.sample.lessons.filter(lesson => track.lessonIds.includes(lesson.id))} releaseId={releaseId} />
          </details>
        )) : <LessonCards lessons={data.sample.lessons} releaseId={releaseId} />}
      </section>}
      {!!data.sample.projects?.length && <section aria-labelledby="curriculum-projects">
        <div className="section-title"><h2 id="curriculum-projects">مشروعات تطبيقية</h2></div>
        <div className="lesson-cards">{data.sample.projects.map(project => <a className="panel lesson-card" key={project.id} href={lessonLink(project.lessonId, releaseId)}><h3>{project.title}</h3><p>{project.summary}</p></a>)}</div>
      </section>}
      {!user && <aside className="account-invite"><div><h2>احفظ تقدمك</h2><p>أنشئ حسابًا لتحفظ خطتك ومسوداتك وتعود إليها لاحقًا.</p></div><a className="btn" href="#auth">دخول أو حساب جديد</a></aside>}
    </>;
  }
  const pageLabel = navigation.find(([id]) => id === selected)?.[1]
    ?? (route === 'auth' ? 'الحساب' : route === 'admin' ? 'إصدارات المحتوى' : route === 'users' ? 'إعدادات المستخدمين' : route === 'offers' ? 'أسعار المسارات' : 'التعلّم');

  return <>
    <a href="#main" className="skip-link" onClick={event => { event.preventDefault(); mainRef.current?.focus(); }}>انتقل إلى المحتوى</a>
    <div className="shell">
      <aside className="sidebar">
        <a href="#start" className="brand" aria-label={`${PRODUCT_NAME} — نقطة البداية`}>
          <picture className="brand-picture">
            <source srcSet={BRAND_ASSETS.iconWebp} type="image/webp" />
            <img className="brand-mark" src={BRAND_ASSETS.icon} width="48" height="48" alt="" />
          </picture>
          <span><strong dir="ltr" lang="en">{PRODUCT_NAME}</strong><small>{PRODUCT_DESCRIPTOR}</small></span>
        </a>
        <nav className="nav" aria-label="التنقل الرئيسي">
          {navigation.map(([id, title, icon]) => <a key={id} href={`#${id}`} className={selected === id ? 'active' : ''} aria-current={selected === id ? 'page' : undefined}><Icon name={icon} />{title}</a>)}
          {(commercialSettings || reserveOffersLink) && <a href={commercialSettings ? '#offers' : undefined}
            className={route === 'offers' ? 'active' : ''} aria-current={commercialSettings && route === 'offers' ? 'page' : undefined}
            aria-hidden={reserveOffersLink || undefined}><Icon name="route" />أسعار المسارات</a>}
          {management && <a href="#admin" className={route === 'admin' ? 'active' : ''} aria-current={route === 'admin' ? 'page' : undefined}><Icon name="book" />إصدارات المحتوى</a>}
          {canManageAccess && <a href="#users" className={route === 'users' ? 'active' : ''} aria-current={route === 'users' ? 'page' : undefined}><Icon name="person" />إعدادات المستخدمين</a>}
        </nav>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="topbar-title">{pageLabel}</span>
          <div className="topbar-actions">
            {checking ? <span className="muted">جارٍ التحقق…</span> : user ? <>
              <a className="account-link" href="#auth" aria-current={route === 'auth' ? 'page' : undefined}><Icon name="person" /><span>{user.displayName}</span></a>
              <button className="btn compact" onClick={logout} disabled={busy}>{busy ? 'جارٍ الخروج…' : 'خروج'}</button>
            </> : route !== 'auth' && <a className="btn compact" href="#auth">دخول / حساب جديد</a>}
          </div>
        </header>
        <main className="main" id="main" ref={mainRef} tabIndex={-1}>
          <ErrorBox message={sessionError || logoutError} retry={refreshProtection} />
          {needsContent && canReadContent && <div className="preferences">
            <label>لغة الأمثلة
              <select value={language} disabled={!!fixedLanguage} onChange={event => setLanguage(event.target.value as ExampleLanguage)}>
                {Object.entries(exampleLanguageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <span className="field-help">لغة القراءة فقط، ولا تغيّر هدفك أو خطتك.</span>
          </div>}
          {sessionNotice && <p className="feedback" role="status">{sessionNotice}</p>}
          <Suspense fallback={<Loading />}>
            {page()}
            <footer className="footer" aria-hidden={!startupComplete || undefined}>
              <span><bdi dir="ltr" lang="en">{PRODUCT_NAME}</bdi> · {PRODUCT_DESCRIPTOR}</span>
              <button className="btn text" disabled={checking} onClick={refreshProtection}>تحديث حماية الجلسة</button>
            </footer>
          </Suspense>
        </main>
      </div>
    </div>
  </>;
}
