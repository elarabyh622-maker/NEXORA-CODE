import { useState, type FormEvent } from 'react';
import { formatOffer } from './Access';
import { RecoveryCode } from './AccountSettings';
import { errorText, request, segment, type SessionScope } from './api';
import { useResource } from './hooks';
import type { AccessCancellation, Goal, Purchase } from './types';
import { ErrorBox, Heading, Loading } from './ui';

type CancellationRow = AccessCancellation & { userName: string; displayName: string };
type PurchaseRow = Purchase & { userName: string };

function AssistedRecovery({ scope }: { scope: SessionScope }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [issued, setIssued] = useState<{ recoveryCode: string; expiresAt: string } | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError(''); setIssued(null);
    try {
      const result = await request<{ recoveryCode: string; expiresAt: string }>('/admin/accounts/recovery-code', { method: 'POST', scope,
        body: { userName: data.get('userName'), currentPassword: data.get('currentPassword') },
      });
      if (!scope.signal.aborted) { form.reset(); setIssued(result); }
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel stack" aria-labelledby="assisted-recovery">
    <h2 id="assisted-recovery">مساعدة متعلّم في استرجاع حسابه</h2>
    <p className="muted">تحقّق من ملكية الحساب أولًا، ثم شارك الرمز مع المتعلّم عبر قناة التواصل التي تحقّقت منها. الرمز صالح لمدة 30 دقيقة.</p>
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <label>اسم مستخدم المتعلّم<input name="userName" required minLength={3} maxLength={40} dir="auto" autoComplete="off" spellCheck={false} /></label>
      <label>كلمة مرور حسابك الإداري<input type="password" name="currentPassword" autoComplete="current-password" maxLength={128} required /></label>
      <label className="check-label"><input type="checkbox" required />تحقّقت من ملكية الحساب.</label>
      <ErrorBox message={error} />
      <div className="actions"><button className="btn" disabled={busy}>{busy ? 'جارٍ الإنشاء…' : 'إنشاء رمز مؤقت'}</button></div>
    </form>
    {issued && <RecoveryCode key={issued.recoveryCode} value={issued.recoveryCode} />}
  </section>;
}

function CancellationAction({ item, scope, onSaved }: { item: CancellationRow; scope: SessionScope; onSaved: (message: string) => void }) {
  const [decision, setDecision] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!decision || busy) return;
    setBusy(true); setError('');
    try {
      await request(`/admin/access/cancellations/${segment(item.id)}/resolve`, { method: 'POST', scope, body: { approve: decision === 'approve' } });
      if (!scope.signal.aborted) onSaved(decision === 'approve' ? 'تم إنهاء الوصول المدفوع للحساب.' : 'تم رفض طلب الإلغاء.');
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <li className="stack">
    <h3>{item.displayName} · <bdi>{item.userName}</bdi></h3>
    <form className="stack" key={item.id} onSubmit={submit} aria-busy={busy}>
      <label>قرار طلب الإلغاء<select required value={decision} disabled={busy} onChange={event => { setDecision(event.target.value); setError(''); }}>
        <option value="">اختر الإجراء</option><option value="approve">الموافقة وإنهاء كل الوصول المدفوع</option><option value="decline">رفض الطلب</option>
      </select></label>
      {decision && <label key={decision} className="check-label"><input type="checkbox" required />أؤكد تنفيذ القرار لهذا الحساب.</label>}
      <ErrorBox message={error} />
      <div className="actions"><button className="btn" disabled={!decision || busy}>{busy ? 'جارٍ الحفظ…' : 'حفظ قرار الإلغاء'}</button></div>
    </form>
  </li>;
}

function CancellationQueue({ scope }: { scope: SessionScope }) {
  const queue = useResource<CancellationRow[]>('/admin/access/cancellations', 0, false, scope);
  const [notice, setNotice] = useState('');
  return <section className="panel stack" aria-labelledby="cancellation-queue">
    <div className="account-heading"><h2 id="cancellation-queue">طلبات إلغاء الوصول</h2>
      <button type="button" className="btn compact" disabled={queue.loading} onClick={queue.reload}>تحديث الطلبات</button></div>
    <ErrorBox message={queue.error} retry={queue.reload} />
    {queue.loading && <Loading />}
    {notice && <p className="feedback success" role="status">{notice}</p>}
    {queue.data?.length === 0 && <p className="muted">لا توجد طلبات قيد المراجعة.</p>}
    {!!queue.data?.length && <ul className="account-admin-queue">{queue.data.map(item => <CancellationAction key={item.id} item={item}
      scope={scope} onSaved={message => { setNotice(message); queue.reload(); }} />)}</ul>}
  </section>;
}

function PurchaseAction({ item, scope, title, onSaved }: { item: PurchaseRow; scope: SessionScope; title: string; onSaved: (message: string) => void }) {
  const hasLink = item.status === 'link-ready';
  const [action, setAction] = useState<'link' | 'confirm' | 'close'>(hasLink ? 'confirm' : 'link');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError('');
    try {
      await request(`/admin/purchases/${segment(item.id)}/${action}`, { method: action === 'link' ? 'PUT' : 'POST', scope,
        ...(action === 'link' ? { body: { checkoutUrl: data.get('checkoutUrl') } }
          : action === 'confirm' ? { body: { paymentReference: data.get('paymentReference') } }
          : hasLink ? { body: { confirmedUnpaidAndDisabled: true } } : {}),
      });
      if (!scope.signal.aborted) onSaved(action === 'link' ? 'تم إتاحة الرابط للمتعلّم.' : action === 'close' ? 'تم إغلاق الطلب.' : 'تم تأكيد السداد وتفعيل المسار.');
    } catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <li className="stack">
    <h3>{title}</h3>
    <p>المتعلّم <bdi>{item.userName}</bdi> · <bdi>{formatOffer(item)}</bdi></p>
    <p className="field-help">مرجع الطلب <bdi>{item.id}</bdi></p>
    <label>الإجراء<select value={action} disabled={busy} onChange={event => { setAction(event.target.value as typeof action); setError(''); }}>
      {hasLink ? <option value="confirm">تأكيد السداد وتفعيل المسار</option> : <option value="link">إرفاق رابط Paymob</option>}
      <option value="close">{hasLink ? 'إغلاق طلب برابط منتهي أو ملغى' : 'إغلاق الطلب قبل إرسال الرابط'}</option>
    </select></label>
    <form key={action} className="stack" onSubmit={submit} aria-busy={busy}>
      {action === 'link' && <>
        <label>رابط Paymob القصير<input name="checkoutUrl" type="url" dir="ltr" maxLength={200} placeholder="https://paymob.link/…" required /></label>
        <label className="check-label"><input type="checkbox" required />أنشأت هذا الرابط لهذا الطلب وراجعت المبلغ والعملة.</label>
      </>}
      {action === 'close' && <label className="check-label"><input type="checkbox" required />{hasLink
        ? 'تحقّقت من أن الطلب غير مدفوع وأن رابط Paymob أُلغي أو انتهت صلاحيته.'
        : 'أؤكد إغلاق الطلب قبل إرسال رابط الدفع.'}</label>}
      {action === 'confirm' && <>
        <p className="field-help">راجع العملية في لوحة Paymob وطابقها مع الطلب والمبلغ والعملة.</p>
        <label>رقم عملية Paymob<input name="paymentReference" inputMode="numeric" dir="ltr" pattern="[1-9][0-9]{0,19}" maxLength={20} required /></label>
        <label className="check-label"><input type="checkbox" required />تحقّقت من نجاح السداد في لوحة Paymob.</label>
      </>}
      <ErrorBox message={error} />
      <div className="actions"><button className="btn" disabled={busy}>{busy ? 'جارٍ الحفظ…' : action === 'link' ? 'إتاحة رابط الدفع' : action === 'close' ? 'إغلاق الطلب' : 'تأكيد السداد وتفعيل المسار'}</button></div>
    </form>
  </li>;
}

function PurchaseQueue({ scope, goals }: { scope: SessionScope; goals: Goal[] }) {
  const queue = useResource<PurchaseRow[]>('/admin/purchases', 0, false, scope);
  const [notice, setNotice] = useState('');
  return <section className="panel stack" aria-labelledby="purchase-queue">
    <div className="account-heading"><h2 id="purchase-queue">طلبات الشراء</h2>
      <button type="button" className="btn compact" disabled={queue.loading} onClick={queue.reload}>تحديث الطلبات</button></div>
    <ErrorBox message={queue.error} retry={queue.reload} />
    {queue.loading && <Loading />}
    {notice && <p className="feedback success" role="status">{notice}</p>}
    {queue.data?.length === 0 && <p className="muted">لا توجد طلبات شراء مفتوحة.</p>}
    {!!queue.data?.length && <ul className="account-admin-queue">{queue.data.map(item => <PurchaseAction key={`${item.id}/${item.status}`} item={item}
      title={goals.find(goal => goal.id === item.goalId)?.title ?? item.goalId} scope={scope}
      onSaved={message => { setNotice(message); queue.reload(); }} />)}</ul>}
  </section>;
}

export function AccountOperations({ scope, goals }: { scope: SessionScope; goals: Goal[] }) {
  return <>
    <Heading title="طلبات الحساب والدفع" />
    <div className="actions"><a className="btn text" href="#users">العودة إلى إعدادات المستخدمين</a></div>
    <div className="account-grid">
      <PurchaseQueue scope={scope} goals={goals} />
      <CancellationQueue scope={scope} />
      <AssistedRecovery scope={scope} />
    </div>
  </>;
}
