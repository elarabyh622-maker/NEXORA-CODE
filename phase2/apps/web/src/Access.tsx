import { useCallback, useEffect, useState } from 'react';
import { ACCESS_INVALIDATED, errorText, request, type SessionScope } from './api';
import type { Catalog, CommercialEntitlement, CommercialOffer, User } from './types';
import { ErrorBox, Heading, Loading } from './ui';

type AccessState = { scope?: SessionScope; entitlement?: CommercialEntitlement; loading: boolean; error: string; version: number };

function accessKey(value?: CommercialEntitlement) {
  return JSON.stringify([value?.active, value?.goalIds && [...value.goalIds].sort(), value?.lessonIds && [...value.lessonIds].sort()]);
}

// Entitlement is never persisted in browser storage or reused for a different session.
export function useAccess(required: boolean, scope?: SessionScope) {
  const [state, setState] = useState<AccessState>({ loading: false, error: '', version: 0 });
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!required || !scope?.userId) return;
    const controller = new AbortController();
    let pending = false;
    async function check() {
      if (pending || controller.signal.aborted) return;
      pending = true;
      try {
        const result = await request<CommercialEntitlement>('/me/access', { scope, signal: controller.signal });
        if (!controller.signal.aborted && !scope?.signal.aborted) {
          setState(previous => ({ scope, entitlement: result, loading: false, error: '',
            version: previous.version + Number(accessKey(previous.entitlement) !== accessKey(result)) }));
        }
      } catch (cause) {
        if (!controller.signal.aborted && !scope?.signal.aborted)
          setState(previous => ({ scope, loading: false, error: errorText(cause), version: previous.version + 1 }));
      } finally { pending = false; }
    }
    setState(previous => ({ scope, loading: true, error: '', version: previous.version }));
    const visible = () => { if (document.visibilityState === 'visible') void check(); };
    const denied = () => {
      controller.abort();
      setState(previous => ({ scope, loading: true, error: '', version: previous.version + 1 }));
      setRevision(value => value + 1);
    };
    window.addEventListener('focus', visible);
    window.addEventListener('pageshow', visible);
    window.addEventListener(ACCESS_INVALIDATED, denied);
    document.addEventListener('visibilitychange', visible);
    const interval = window.setInterval(visible, 30000);
    void check();
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener('focus', visible);
      window.removeEventListener('pageshow', visible);
      window.removeEventListener(ACCESS_INVALIDATED, denied);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [required, scope, revision]);
  const current = state.scope === scope && !scope?.signal.aborted;
  const entitlement = current ? state.entitlement : undefined;
  return {
    active: !required || entitlement?.active === true,
    goalIds: entitlement?.goalIds,
    lessonIds: entitlement?.lessonIds,
    version: state.version,
    loading: required && !!scope?.userId && (!current || state.loading),
    error: current ? state.error : '',
    reload,
  };
}

function contactLink(value?: string | null) {
  if (!value) return null;
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
}

export function formatOffer(offer: CommercialOffer) {
  return new Intl.NumberFormat('ar-EG', { style: 'currency', currency: offer.currency, minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(offer.price);
}

function OfferList({ catalog }: { catalog: Catalog }) {
  const goals = catalog.goals.filter(goal => goal.status !== 'planned');
  const prices = new Map(catalog.offers?.map(offer => [offer.goalId, offer]));
  if (goals.length === 0) return <p className="muted">لا توجد مسارات معروضة حاليًا.</p>;
  return <ul className="revision-list offer-list">{goals.map(goal => {
    const offer = prices.get(goal.id);
    return <li key={goal.id}><div><h3>{goal.title}</h3><p>{goal.description}</p></div>
      <span className={offer ? 'offer-price' : 'muted'}>{offer ? <bdi>{formatOffer(offer)}</bdi> : 'السعر غير محدد بعد'}</span>
    </li>;
  })}</ul>;
}

export function OffersPage({ catalog, user }: { catalog: Catalog; user: User | null }) {
  const contact = contactLink(catalog.contactUrl);
  return <><Heading title="أسعار المسارات">لكل مسار سعره. تفعّل الإدارة الوصول لحسابك بعد تأكيد السداد خارج المنصة.</Heading>
    <section className="panel" aria-label="أسعار المسارات"><OfferList catalog={catalog} />
      <div className="actions">{!user && <a className="btn primary" href="#auth">تسجيل الدخول أو إنشاء حساب</a>}
        {contact && <a className="btn" href={contact} target="_blank" rel="noopener noreferrer">تواصل بشأن الشراء</a>}
      </div>
    </section>
  </>;
}

export function AccessGate({ user, catalog, loading, error, reload, unavailable = false }: {
  user: User | null; catalog: Catalog; loading: boolean; error: string; reload: () => void; unavailable?: boolean;
}) {
  const contact = contactLink(catalog.contactUrl);
  return <section className="panel stack" aria-labelledby="access-heading">
    <Heading title="ابدأ رحلتك مع NEXORA CODE" eyebrow="الوصول إلى المنصة" />
    <h2 id="access-heading">{unavailable ? 'هذا المحتوى غير مفعّل لحسابك' : user ? 'تحقق من تفعيل حسابك' : 'منصة تعلّم مدفوعة'}</h2>
    <p>ادرس المسارات والدروس التي تفعّلها الإدارة لحسابك بعد تأكيد السداد خارج المنصة.</p>
    {user && <p>الحساب: <bdi>{user.userName}</bdi></p>}
    {loading ? <Loading text="جارٍ التحقق من حالة الوصول…" /> : user && !error && !unavailable && <p role="status" className="notice">الوصول غير مفعّل لهذا الحساب حاليًا.</p>}
    <ErrorBox message={error} retry={reload} />
    <div className="actions">
      {!user && <a className="btn primary" href="#auth">تسجيل الدخول أو إنشاء حساب</a>}
      {contact && <a className="btn" href={contact} target="_blank" rel="noopener noreferrer">تواصل مع إدارة المنصة بشأن الشراء</a>}
      {user && <button className="btn" disabled={loading} onClick={reload}>تحديث حالة الوصول</button>}
      {unavailable && <a className="btn" href="#start">ارجع إلى محتواك</a>}
    </div>
    {!contact && <p className="field-help">لمعرفة تفاصيل الشراء والتفعيل، تواصل مع مسؤول المنصة عبر وسيلة التواصل التي حصلت منها على رابطها.</p>}
    {catalog.offers && <div><h2>أسعار المسارات</h2><OfferList catalog={catalog} /></div>}
  </section>;
}

export function AccessAdmin({ scope }: { scope: SessionScope }) {
  const [userName, setUserName] = useState('');
  const [action, setAction] = useState<'grant' | 'revoke'>('grant');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!confirmed || busy || !userName.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await request(`/admin/access/${action}`, { method: 'POST', scope, body: { userName: userName.trim() } });
      if (scope.signal.aborted) return;
      setNotice(`${action === 'grant' ? 'تم تفعيل' : 'تم إلغاء'} الوصول للحساب ${userName.trim()}.`);
      setConfirmed(false);
      window.dispatchEvent(new Event(ACCESS_INVALIDATED));
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel history">
    <h2>إدارة الوصول المدفوع</h2>
    <p>فعّل الوصول فقط بعد التحقق من الشراء خارج المنصة. إلغاء الوصول يمنع متابعة المحتوى دون حذف تقدم الحساب.</p>
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <label>اسم المستخدم<input value={userName} dir="auto" required minLength={3} maxLength={40} disabled={busy} autoComplete="off" onChange={event => { setUserName(event.target.value); setConfirmed(false); setNotice(''); setError(''); }} /></label>
      <label>الإجراء<select value={action} disabled={busy} onChange={event => { setAction(event.target.value as 'grant' | 'revoke'); setConfirmed(false); setNotice(''); setError(''); }}><option value="grant">تفعيل الوصول</option><option value="revoke">إلغاء الوصول</option></select></label>
      <label className="check-label"><input type="checkbox" required checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />{action === 'grant' ? 'تحققت من الشراء وراجعت اسم الحساب المطلوب تفعيله.' : 'راجعت اسم الحساب وأؤكد إلغاء وصوله إلى المحتوى.'}</label>
      <ErrorBox message={error} />
      {error && <p className="field-help">إذا تعذر تأكيد النتيجة، يمكنك إعادة الإجراء نفسه لهذا الحساب. لا تنشئ هذه العملية عملية دفع.</p>}
      {notice && <p className="feedback success" role="status">{notice}</p>}
      <button className="btn primary" disabled={busy || !confirmed || !userName.trim()}>{busy ? 'جارٍ تحديث الوصول…' : action === 'grant' ? 'تأكيد تفعيل الوصول' : 'تأكيد إلغاء الوصول'}</button>
    </form>
  </section>;
}
