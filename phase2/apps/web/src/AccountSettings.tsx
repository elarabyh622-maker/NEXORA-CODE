import { useState, type FormEvent } from 'react';
import { formatOffer } from './Access';
import { errorText, request, type SessionScope } from './api';
import { useResource } from './hooks';
import type { AccessCancellation, Goal, Purchase, User } from './types';
import { ErrorBox, Heading, Loading } from './ui';
import './account.css';

export function RecoveryCode({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(value); setCopied(true); }
    catch { setCopied(false); }
  }
  return <div className="notice stack">
    <p>احفظ الرمز في مكان آمن. يظهر مرة واحدة ويُستخدم مرة واحدة.</p>
    <code className="recovery-code" dir="ltr">{value}</code>
    {navigator.clipboard && <button type="button" className="btn compact" onClick={copy}>{copied ? 'تم النسخ' : 'نسخ الرمز'}</button>}
  </div>;
}

function PasswordPanel({ scope, onChanged }: { scope: SessionScope; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    if (data.get('newPassword') !== data.get('confirmPassword')) {
      setError('كلمتا المرور غير متطابقتين.');
      form.querySelector<HTMLInputElement>('[name=confirmPassword]')?.focus();
      return;
    }
    setBusy(true); setError('');
    try {
      await request('/auth/change-password', { method: 'POST', scope, body: {
        currentPassword: data.get('currentPassword'), newPassword: data.get('newPassword'),
      } });
      form.reset();
      onChanged();
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel stack" aria-labelledby="account-password">
    <h2 id="account-password">تغيير كلمة المرور</h2>
    <p className="muted">بعد الحفظ، هتسجّل دخول من جديد على أجهزتك. تقدر تنشئ رمز استرجاع جديد بعدها.</p>
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <label>كلمة المرور الحالية<input type={show ? 'text' : 'password'} name="currentPassword" autoComplete="current-password" required maxLength={128} /></label>
      <label>كلمة المرور الجديدة<input type={show ? 'text' : 'password'} name="newPassword" autoComplete="new-password" required minLength={12} maxLength={128} aria-describedby="new-password-hint" /></label>
      <p className="field-help" id="new-password-hint">استخدم من 12 إلى 128 حرفًا.</p>
      <label>تأكيد كلمة المرور الجديدة<input type={show ? 'text' : 'password'} name="confirmPassword" autoComplete="new-password" required minLength={12} maxLength={128} /></label>
      <label className="check-label"><input type="checkbox" checked={show} onChange={event => setShow(event.target.checked)} />إظهار كلمات المرور</label>
      <ErrorBox message={error} />
      <button className="btn primary" disabled={busy}>{busy ? 'جارٍ الحفظ…' : 'حفظ كلمة المرور'}</button>
    </form>
  </section>;
}

function RecoveryPanel({ scope }: { scope: SessionScope }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    setBusy(true); setError(''); setCode('');
    try {
      const result = await request<{ recoveryCode: string }>('/auth/recovery-code', {
        method: 'POST', scope, body: { currentPassword: new FormData(form).get('currentPassword') },
      });
      if (!scope.signal.aborted) { form.reset(); setCode(result.recoveryCode); }
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel stack" aria-labelledby="account-recovery">
    <h2 id="account-recovery">رمز استرجاع الحساب</h2>
    <p className="muted">استخدمه لو نسيت كلمة المرور. إنشاء رمز جديد يستبدل أي رمز قديم.</p>
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <label>كلمة المرور الحالية<input type="password" name="currentPassword" autoComplete="current-password" required maxLength={128} /></label>
      <ErrorBox message={error} />
      <button className="btn" disabled={busy}>{busy ? 'جارٍ الإنشاء…' : 'إنشاء رمز استرجاع'}</button>
    </form>
    {code && <RecoveryCode key={code} value={code} />}
  </section>;
}

type CancellationState = { request: AccessCancellation | null };
const cancellationStatus = { pending: 'طلب الإلغاء قيد المراجعة.', approved: 'وافقت الإدارة على طلب الإلغاء.', declined: 'أغلقت الإدارة طلب الإلغاء دون تنفيذه.' };

function CancellationPanel({ scope, active }: { scope: SessionScope; active: boolean }) {
  const cancellation = useResource<CancellationState>('/me/access-cancellation', 0, false, scope);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const status = cancellation.data?.request?.status;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || busy) return;
    setBusy(true); setError('');
    try {
      await request('/me/access-cancellation', { method: 'POST', scope });
      if (!scope.signal.aborted) { setConfirmed(false); setSubmitted(true); cancellation.reload(); }
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel stack" aria-labelledby="access-cancellation">
    <div className="account-heading"><h2 id="access-cancellation">إلغاء الوصول المدفوع</h2>
      <button type="button" className="btn compact" disabled={cancellation.loading} onClick={cancellation.reload}>تحديث الحالة</button></div>
    <p className="muted">شراء المسار دفعة واحدة. لو وافقت الإدارة على طلب الإلغاء، ينتهي وصولك لكل المحتوى المدفوع ويظل حسابك وتقدّمك محفوظين.</p>
    <ErrorBox message={cancellation.error || error} retry={cancellation.error ? cancellation.reload : undefined} />
    {cancellation.loading && <Loading text="جارٍ قراءة حالة الطلب…" />}
    {status && <p className="notice" role="status">{cancellationStatus[status]}</p>}
    {!status && submitted && <p className="notice" role="status">تم إرسال الطلب.</p>}
    {active && status !== 'pending' && cancellation.data && !cancellation.loading && <form className="stack" onSubmit={submit} aria-busy={busy}>
      <label className="check-label"><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />أؤكد طلب إنهاء كل وصولي المدفوع.</label>
      <button className="btn" disabled={!confirmed || busy}>{busy ? 'جارٍ إرسال الطلب…' : 'إرسال طلب الإلغاء'}</button>
    </form>}
  </section>;
}

const purchaseStatus: Record<Purchase['status'], string> = {
  pending: 'في انتظار رابط الدفع', 'link-ready': 'رابط الدفع جاهز', confirmed: 'تم تأكيد السداد', closed: 'الطلب مغلق',
};

function Purchases({ scope, goals }: { scope: SessionScope; goals: Goal[] }) {
  const purchases = useResource<Purchase[]>('/me/purchases', 0, false, scope);
  return <section className="panel stack" aria-labelledby="account-purchases">
    <div className="account-heading"><h2 id="account-purchases">طلبات الشراء</h2>
      <button className="btn compact" type="button" disabled={purchases.loading} onClick={purchases.reload}>تحديث الطلبات</button></div>
    <ErrorBox message={purchases.error} retry={purchases.reload} />
    {purchases.loading && <Loading text="جارٍ قراءة طلباتك…" />}
    {purchases.data?.length === 0 && <p className="muted">تقدر تطلب رابط دفع من صفحة أسعار المسارات.</p>}
    {!!purchases.data?.length && <ul className="revision-list account-orders">{purchases.data.map(purchase =>
      <li key={purchase.id}>
        <div><h3>{goals.find(goal => goal.id === purchase.goalId)?.title ?? purchase.goalId}</h3>
          <p>{purchaseStatus[purchase.status]} · <bdi>{formatOffer(purchase)}</bdi></p></div>
        {purchase.status === 'link-ready' && purchase.checkoutUrl?.startsWith('https://paymob.link/') &&
          <a className="btn" href={purchase.checkoutUrl} target="_blank" rel="noopener noreferrer">ادفع عبر Paymob</a>}
      </li>)}</ul>}
    <a className="btn text" href="#offers">أسعار المسارات</a>
  </section>;
}

export function AccountSettings({ user, scope, onPasswordChanged, commercial, active, goals }: {
  user: User; scope: SessionScope; onPasswordChanged: () => void; commercial: boolean; active: boolean; goals: Goal[];
}) {
  return <>
    <Heading title="حسابي">مسجل باسم <bdi>{user.userName}</bdi>.</Heading>
    <div className="account-grid">
      <PasswordPanel scope={scope} onChanged={onPasswordChanged} />
      <RecoveryPanel scope={scope} />
      {commercial && user.role === 'Learner' && <>
        <CancellationPanel scope={scope} active={active} />
        <Purchases scope={scope} goals={goals} />
      </>}
    </div>
  </>;
}
