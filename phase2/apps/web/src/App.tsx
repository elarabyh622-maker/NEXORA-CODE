import { useEffect, useRef, useState } from 'react';
import { Admin } from './Admin';
import { AccessGate, useAccess } from './Access';
import { errorText, request, segment } from './api';
import { Auth } from './Auth';
import { BRAND_ASSETS, PRODUCT_DESCRIPTOR, PRODUCT_NAME } from './brand';
import { useResource } from './hooks';
import { Lesson } from './Lesson';
import { lessonLink, linkedLessonRelease } from './lessonLinks';
import { GoalCards, PlanPage, ProgressPage } from './Plans';
import { catalogReleaseOptions } from './releaseSelection';
import type { Catalog, Content, Lesson as LessonData, Release } from './types';
import { ErrorBox, Heading, Icon, Loading } from './ui';
import { useSession } from './useSession';

function useRoute() {
  const [hash, setHash] = useState(window.location.hash || '#start');
  useEffect(() => { const change = () => setHash(window.location.hash || '#start'); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  return hash.slice(1).split('/');
}

function ReleasePicker({ releases, select }: { releases: Release[]; select: (id: string) => void }) {
  return <section className="panel release-picker" aria-labelledby="pick-release">
    <h2 id="pick-release">اختر إصدار المحتوى</h2>
    <p className="muted">اختر إصدارًا منشورًا لعرض دروسه وخططه.</p>
    <ul className="revision-list">{releases.map(release => <li key={release.id}>
      <div><h3>{release.title}</h3><p><bdi>{release.releaseId}</bdi></p></div>
      <button className="btn compact" onClick={() => select(release.releaseId)} aria-label={`عرض ${release.title}، ${release.releaseId}`}>عرض الإصدار</button>
    </li>)}</ul>
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
  const [selection, setReleaseId] = useState('');
  const [preferredLanguage, setLanguage] = useState<string>();
  const language = preferredLanguage ?? (route === 'lesson' && routeLanguage === 'javascript' ? 'javascript' : 'python');
  const [progressRevision, setProgressRevision] = useState(0);
  const [catalogTick, setCatalogTick] = useState(0);
  const catalog = useResource<Catalog>('/catalog', catalogTick);
  const commercial = catalog.data?.accessRequired === true;
  const access = useAccess(commercial, session?.scope);
  const canReadContent = !!catalog.data && (!commercial || (!checking && access.active));
  const { published, initialId, needsChoice } = catalogReleaseOptions(catalog.data, selection);
  const lessonRelease = route === 'lesson' ? linkedLessonRelease(routeParam, routeRelease) : null;
  const linkedReleaseId = lessonRelease && published.some(item => item.releaseId === lessonRelease) ? lessonRelease : null;
  const releaseId = linkedReleaseId ?? selection;
  const content = useResource<Content>(releaseId && canReadContent ? `/content/${segment(releaseId)}` : null, catalogTick + (commercial ? session?.generation ?? 0 : 0), false, commercial ? session?.scope : undefined);
  const mainRef = useRef<HTMLElement>(null);
  const management = !!user && ['Author', 'Reviewer', 'Admin'].includes(user.role);
  useEffect(() => { const next = linkedReleaseId || initialId; if (next) setReleaseId(next); }, [initialId, linkedReleaseId]);
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
  const navigation = [ ['start', 'نقطة البداية', 'home'], ['plan', 'خطتي التعليمية', 'route'], ['progress', 'تقدمي', 'chart'], ['glossary', 'قاموس المصطلحات', 'book'] ] as const;
  const selected = route === 'lesson' ? 'plan' : route;
  const picker = published.length > 0 && <ReleasePicker releases={published} select={setReleaseId} />;
  function page() {
    if (route === 'auth') {
      if (checking) return <Loading text="جارٍ التحقق من الجلسة…" />;
      return session && <Auth key={session.generation} commercial={commercial} user={user} scope={session.scope} onIdentity={async id => (await authenticationChanged())?.user?.id === id} />;
    }
    if (route === 'admin') {
      if (checking) return <Loading />;
      if (management && user && session) return <Admin key={session.generation} commercial={commercial} user={user} scope={session.scope} onPublished={() => setCatalogTick(value => value + 1)} />;
      return <><Heading title="مساحة فريق المحتوى" /><p className="notice">هذه المساحة متاحة للحسابات المصرح لها بمراجعة المحتوى. <a href="#auth">الانتقال إلى الحساب</a></p></>;
    }
    if (commercial && (!access.active || checking)) {
      return checking ? <Loading text="جارٍ التحقق من الحساب…" /> : <AccessGate user={user} catalog={catalog.data!} loading={access.loading} error={access.error} reload={access.reload} />;
    }
    if (route === 'plan') {
      if (checking || catalog.loading || content.loading || initialId) return <Loading text="جارٍ قراءة الخطة والمحتوى…" />;
      return <><ErrorBox message={catalog.error} retry={catalog.reload} /><ErrorBox message={content.error} retry={content.reload} />
        {!content.data && picker}
        {catalog.data && !published.length && <p className="notice">لا يوجد محتوى منشور متاح الآن.</p>}
        {session && <PlanPage key={`${releaseId}/${session.generation}/${planGoal ?? ''}`} content={content.data} releaseId={releaseId} user={user} scope={session.scope} refreshProgress={progressRevision} onRelease={setReleaseId} initialGoal={planGoal} />}
      </>;
    }
    if (catalog.loading || initialId || (releaseId && content.loading)) return <Loading />;
    if (catalog.error) return <ErrorBox message={catalog.error} retry={catalog.reload} />;
    if (content.error) return <><ErrorBox message={content.error} retry={content.reload} />{picker}</>;
    if (needsChoice) return <><Heading title="ابدأ بإصدار منشور" />{picker}</>;
    if (!releaseId || !content.data) return <section className="panel empty"><Heading title="نجهز خطوتك الأولى" /><p>لا يوجد محتوى منشور متاح الآن. حاول مجددًا لاحقًا.</p><button className="btn" onClick={catalog.reload}>تحديث المحتوى</button></section>;
    const data = content.data;
    if (route === 'progress') return checking ? <Loading /> : <ProgressPage key={session?.generation} user={user} scope={session?.scope} releaseId={releaseId} content={data} revision={progressRevision} />;
    if (route === 'lesson' && routeParam) {
      if (lessonRelease && lessonRelease !== releaseId)
        return <ErrorBox message="إصدار الدرس غير متاح للقراءة. اختر إصدارًا منشورًا." />;
      let lessonId: string;
      try { lessonId = decodeURIComponent(routeParam); } catch { return <ErrorBox message="رابط الدرس غير صحيح. ارجع إلى الخطة واختر الدرس مجددًا." />; }
      const project = data.sample.projects?.find(item => item.lessonId === lessonId);
      return checking ? <Loading /> : <Lesson key={`${releaseId}/${session?.generation ?? 'public'}/${lessonId}`} releaseId={releaseId} lessonId={lessonId} goalParam={routeGoal} user={user} scope={session?.scope} language={language} store={session?.drafts} project={project} onAttempt={() => setProgressRevision(value => value + 1)} />;
    }
    if (route === 'glossary') return <><Heading title="كلمات جديدة، بمعنى واضح" eyebrow="قاموس المصطلحات">ارجع إلى هذه المعاني كلما احتجت. لا تحتاج إلى حفظها كلها دفعة واحدة.</Heading><dl className="glossary">{data.sample.glossary.map(item => <div className="panel" key={item.term}><dt>{item.term} <span lang="en" dir="ltr">{item.technical}</span></dt><dd>{item.definition}</dd></div>)}</dl></>;
    if (route !== 'start') return <><Heading title="لم نجد هذه الصفحة" /><a className="btn primary" href="#start">العودة إلى نقطة البداية</a></>;
    const lessonCards = (lessons: LessonData[]) => <div className="lesson-cards">{lessons.map((lesson, index) => (
      <a className="panel lesson-card" key={lesson.id} href={lessonLink(lesson.id, releaseId)}>
        <span className="step-number">{index + 1}</span><h3>{lesson.title}</h3>
        <p>{lesson.summary}</p><span className="field-help">{lesson.minutes} دقيقة تقريبًا</span>
      </a>
    ))}</div>;
    return <>
      {commercial && <p className="feedback success" role="status">الوصول مفعّل لحسابك. يمكنك متابعة خطتك ودروسك.</p>}
      <section className="hero" aria-labelledby="start-title">
        <div className="hero-copy">
          <h1 id="start-title">{PRODUCT_DESCRIPTOR}<br />من الصفر</h1>
          <p>اختر لغة أو تخصصًا يناسب هدفك. سنرتّب لك ما تحتاج إلى فهمه أولًا، ونرشدك إلى خطوتك التالية.</p>
          <a className="btn primary" href="#plan">استكشف خطتك <Icon name="arrow" /></a>
        </div>
        <div className="hero-art">
          <img src={BRAND_ASSETS.wordmark} width="1445" height="530" alt={`${PRODUCT_NAME} — Learn to Think. Code to Create.`} lang="en" dir="ltr" />
        </div>
      </section>
      <section aria-labelledby="start-goals">
        <div className="section-title"><h2 id="start-goals">اختر نقطة البداية</h2></div>
        <GoalCards goals={data.graph.goals} curriculum={!!data.sample.tracks} />
      </section>
      <section className="panel intro"><h2>{data.sample.title}</h2><p>{data.sample.intro}</p></section>
      <section aria-labelledby="sample-lessons">
        <div className="section-title"><h2 id="sample-lessons">{data.sample.tracks ? 'وحدات المنهج' : 'دروس العينة'}</h2></div>
        {data.sample.tracks ? data.sample.tracks.map((track, index) => (
          <details className="panel curriculum-track" key={track.id} open={index === 0}>
            <summary>{track.title} · {track.lessonIds.length} درسًا</summary>
            {lessonCards(data.sample.lessons.filter(lesson => track.lessonIds.includes(lesson.id)))}
          </details>
        )) : lessonCards(data.sample.lessons)}
      </section>
      {!!data.sample.projects?.length && <section aria-labelledby="curriculum-projects">
        <div className="section-title"><h2 id="curriculum-projects">مشروعات تطبيقية</h2></div>
        <div className="lesson-cards">{data.sample.projects.map(project => <a className="panel lesson-card" key={project.id} href={lessonLink(project.lessonId, releaseId)}><h3>{project.title}</h3><p>{project.summary}</p></a>)}</div>
      </section>}
      {!user && <aside className="account-invite"><div><h2>احفظ تقدمك</h2><p>أنشئ حسابًا لتحفظ خطتك ومسوداتك وتعود إليها لاحقًا.</p></div><a className="btn" href="#auth">دخول أو حساب جديد</a></aside>}
    </>;
  }
  const pageLabel = navigation.find(([id]) => id === selected)?.[1]
    ?? (route === 'auth' ? 'الحساب' : route === 'admin' ? 'إصدارات المحتوى' : 'التعلّم');

  return <>
    <a href="#main" className="skip-link" onClick={event => { event.preventDefault(); mainRef.current?.focus(); }}>انتقل إلى المحتوى</a>
    <div className="shell">
      <aside className="sidebar">
        <a href="#start" className="brand" aria-label={`${PRODUCT_NAME} — نقطة البداية`}>
          <img className="brand-mark" src={BRAND_ASSETS.icon} width="48" height="48" alt="" />
          <span><strong dir="ltr" lang="en">{PRODUCT_NAME}</strong><small>{PRODUCT_DESCRIPTOR}</small></span>
        </a>
        <nav className="nav" aria-label="التنقل الرئيسي">
          {navigation.map(([id, title, icon]) => <a key={id} href={`#${id}`} className={selected === id ? 'active' : ''} aria-current={selected === id ? 'page' : undefined}><Icon name={icon} />{title}</a>)}
          {management && <a href="#admin" className={route === 'admin' ? 'active' : ''} aria-current={route === 'admin' ? 'page' : undefined}><Icon name="book" />إصدارات المحتوى</a>}
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
          {route !== 'auth' && canReadContent && <div className="preferences">
            {published.length > 0 && <label>إصدار المحتوى
              <select value={releaseId} onChange={event => { setReleaseId(event.target.value); if (route === 'lesson') window.location.hash = '#start'; }}>
                <option value="" disabled>اختر إصدارًا منشورًا</option>
                {!published.some(item => item.releaseId === releaseId) && releaseId && <option value={releaseId}>{releaseId}</option>}
                {published.map(item => <option key={item.id} value={item.releaseId}>{item.title} · {item.releaseId}</option>)}
              </select>
            </label>}
            <label>لغة الأمثلة
              <select value={language} onChange={event => setLanguage(event.target.value)}><option value="python">Python</option><option value="javascript">JavaScript</option></select>
            </label>
            <span className="field-help">لغة القراءة فقط، ولا تغيّر هدفك أو خطتك.</span>
          </div>}
          {sessionNotice && <p className="feedback" role="status">{sessionNotice}</p>}
          {page()}
          <footer className="footer">
            <span><bdi dir="ltr" lang="en">{PRODUCT_NAME}</bdi> · {PRODUCT_DESCRIPTOR}</span>
            <button className="btn text" disabled={checking} onClick={refreshProtection}>تحديث حماية الجلسة</button>
          </footer>
        </main>
      </div>
    </div>
  </>;
}
