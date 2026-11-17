import { useState, type FormEvent } from 'react';
import { formatOffer } from './Access';
import { errorText, request, segment, type SessionScope } from './api';
import { useResource } from './hooks';
import type { CommercialAccount, CommercialOffer, CommercialTarget, CommercialTargets } from './types';
import { ErrorBox, Heading, Loading } from './ui';
import './commercial.css';

type Action = 'grant' | 'revoke';
type GrantType = 'goal' | 'lesson' | 'legacy';

function targetTitle(targets: CommercialTarget[], id: string) {
  return targets.find(target => target.id === id)?.title ?? id;
}

function AccountAccess({ account, scope, targets, onChanged }: {
  account: CommercialAccount; scope: SessionScope; targets: CommercialTargets; onChanged: (account: CommercialAccount) => void;
}) {
  const [type, setType] = useState<GrantType>('goal');
  const [action, setAction] = useState<Action>('grant');
  const [targetId, setTargetId] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const isGrant = action === 'grant';
  const available = type === 'lesson' ? targets.lessons : targets.goals;
  const selectedIds = type === 'lesson' ? account.lessonIds : account.goalIds;
  const choices = isGrant ? available : selectedIds.map(id => ({ id, title: targetTitle(available, id) }));

  function resetTarget() {
    setTargetId(''); setConfirmed(false); setError(''); setNotice('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !confirmed) return;
    if (type === 'legacy' ? !account.fullAccess || isGrant : !choices.some(choice => choice.id === targetId)) return;
    const target = type === 'legacy' ? 'الوصول الكامل' : targetTitle(available, targetId);
    const body = { userName: account.userName,
      ...(type === 'goal' ? { goalId: targetId } : type === 'lesson' ? { lessonId: targetId } : {}) };
    setBusy(true); setError(''); setNotice('');
    try {
      await request(`/admin/access/${action}`, { method: 'POST', scope, body });
      if (scope.signal.aborted) return;
      setNotice(`${isGrant ? 'تم تفعيل' : 'تم إلغاء'} ${target} لحساب ${account.userName}.`);
      setConfirmed(false);
      if (!isGrant) setTargetId('');
      if (type === 'legacy') setType('goal');
      const nextIds = isGrant ? [...new Set([...selectedIds, targetId])] : selectedIds.filter(id => id !== targetId);
      onChanged({ ...account,
        ...(type === 'goal' ? { goalIds: nextIds } : type === 'lesson' ? { lessonIds: nextIds } : { fullAccess: false }),
      });
    } catch (cause) {
      if (!scope.signal.aborted) setError(errorText(cause));
    } finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="commercial-current">
      <h3>{account.displayName} · <bdi>{account.userName}</bdi></h3>
      <ul className="commercial-grants" aria-label="الوصول المفعّل للحساب">
        {account.fullAccess && <li className="pill sample">وصول كامل</li>}
        {account.goalIds.map(id => <li className="pill sample" key={`goal/${id}`}>مسار · {targetTitle(targets.goals, id)}</li>)}
        {account.lessonIds.map(id => <li className="pill sample" key={`lesson/${id}`}>درس · {targetTitle(targets.lessons, id)}</li>)}
      </ul>
      {!account.fullAccess && !account.goalIds.length && !account.lessonIds.length && <p className="muted">مفيش محتوى مفعّل للحساب.</p>}
    </div>
    <form className="stack" onSubmit={submit} aria-busy={busy}>
      <div className="commercial-fields">
        <label>نوع الوصول<select value={type} disabled={busy} onChange={event => {
          const next = event.target.value as GrantType;
          setType(next);
          if (next === 'legacy') setAction('revoke');
          resetTarget();
        }}><option value="goal">مسار كامل</option><option value="lesson">درس محدد</option>
          {account.fullAccess && <option value="legacy">وصول كامل سابق</option>}
        </select></label>
        <label>الإجراء<select value={action} disabled={busy || type === 'legacy'} onChange={event => {
          setAction(event.target.value as Action); resetTarget();
        }}><option value="grant">تفعيل الوصول</option><option value="revoke">إلغاء الوصول</option></select></label>
      </div>
      {type !== 'legacy' && <label>{type === 'goal' ? 'المسار' : 'الدرس'}
        <select required value={targetId} disabled={busy || !choices.length} onChange={event => {
          setTargetId(event.target.value); setConfirmed(false); setError(''); setNotice('');
        }}><option value="" disabled>{choices.length ? 'اختر المحتوى' : 'لا توجد خيارات متاحة'}</option>
          {choices.map(item => <option key={item.id} value={item.id}>{item.title}{isGrant && selectedIds.includes(item.id) ? ' · مفعّل' : ''}</option>)}
        </select>
      </label>}
      <label className="check-label"><input type="checkbox" required checked={confirmed} disabled={busy || (type !== 'legacy' && !targetId)} onChange={event => setConfirmed(event.target.checked)} />
        {isGrant ? 'تحققت من سداد ثمن المحتوى المحدد لهذا الحساب.' : 'أؤكد إلغاء الوصول المحدد لهذا الحساب.'}
      </label>
      <ErrorBox message={error} />
      {notice && <p className="feedback success" role="status">{notice}</p>}
      <button className="btn primary" disabled={busy || !confirmed || (type !== 'legacy' && !targetId)}>{busy ? 'جارٍ الحفظ…' : isGrant ? 'تأكيد تفعيل الوصول' : 'تأكيد إلغاء الوصول'}</button>
    </form>
  </div>;
}

function OfferForm({ goal, offer, scope, onSaved }: {
  goal: CommercialTarget; offer?: CommercialOffer; scope: SessionScope; onSaved: (offer: CommercialOffer | null) => void;
}) {
  const [price, setPrice] = useState(offer ? String(offer.price) : '');
  const [currency, setCurrency] = useState(offer?.currency ?? '');
  const [published, setPublished] = useState(offer);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  async function save(clear = false) {
    if (busy) return;
    const amount = Number(price);
    if (!clear && (!price.trim() || !Number.isFinite(amount) || amount < 0 || amount > 99999999.99 || !/^[A-Z]{3}$/.test(currency))) {
      setNotice(''); setError('أدخل سعرًا صالحًا ورمز عملة من ثلاثة أحرف.');
      return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      await request(`/admin/access/offers/${segment(goal.id)}`, { method: 'PUT', scope,
        body: clear ? { price: null, currency: null } : { price: amount, currency } });
      if (scope.signal.aborted) return;
      const saved = clear ? null : { goalId: goal.id, price: amount, currency };
      setPublished(saved ?? undefined);
      if (clear) { setPrice(''); setCurrency(''); }
      setNotice(clear ? 'تمت إزالة السعر.' : 'تم حفظ السعر.');
      onSaved(saved);
    } catch (cause) {
      if (!scope.signal.aborted) setError(errorText(cause));
    } finally { setBusy(false); }
  }
  return <form className="stack" aria-busy={busy} onSubmit={event => { event.preventDefault(); void save(); }}>
    <p className="field-help">السعر المعروض · {published ? <bdi>{formatOffer(published)}</bdi> : 'غير محدد بعد'}</p>
    <div className="commercial-fields">
      <label>السعر<input type="number" required min="0" max="99999999.99" step="0.01" inputMode="decimal" dir="ltr" value={price} disabled={busy} onChange={event => setPrice(event.target.value)} /></label>
      <label>رمز العملة<input required minLength={3} maxLength={3} pattern="[A-Z]{3}" placeholder="EGP" dir="ltr" autoComplete="off" value={currency} disabled={busy} onChange={event => setCurrency(event.target.value.toUpperCase())} /></label>
    </div>
    <ErrorBox message={error} />
    {notice && <p className="feedback success" role="status">{notice}</p>}
    <div className="actions"><button className="btn primary" disabled={busy}>{busy ? 'جارٍ الحفظ…' : 'حفظ سعر المسار'}</button>
      {published && <button type="button" className="btn" disabled={busy} onClick={() => void save(true)}>إزالة السعر</button>}
    </div>
  </form>;
}

export function CommercialSettings({ scope, onOffersChanged }: { scope: SessionScope; onOffersChanged: () => void }) {
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [selectedUser, setSelectedUser] = useState('');
  const [selectedGoal, setSelectedGoal] = useState('');
  const [updatedAccounts, setUpdatedAccounts] = useState<Record<string, CommercialAccount>>({});
  const [updatedOffers, setUpdatedOffers] = useState<Record<string, CommercialOffer | null>>({});
  const targets = useResource<CommercialTargets>('/admin/access/targets', 0, false, scope);
  const offers = useResource<CommercialOffer[]>('/admin/access/offers', 0, false, scope);
  const accounts = useResource<CommercialAccount[]>(`/admin/access/accounts?query=${encodeURIComponent(query)}`, 0, false, scope);
  const account = Object.hasOwn(updatedAccounts, selectedUser) ? updatedAccounts[selectedUser] : accounts.data?.find(item => item.userName === selectedUser);
  const goal = targets.data?.goals.find(item => item.id === selectedGoal);
  const offer = Object.hasOwn(updatedOffers, selectedGoal) ? updatedOffers[selectedGoal] ?? undefined : offers.data?.find(item => item.goalId === selectedGoal);

  function searchAccounts(event: FormEvent) {
    event.preventDefault();
    const term = search.trim();
    if (term.length === 1) return;
    setSelectedUser('');
    setUpdatedAccounts({});
    if (term === query) accounts.reload();
    else setQuery(term);
  }

  return <><Heading title="إعدادات المستخدمين" eyebrow="إدارة الاشتراكات">حدّد ما يقدر كل متعلّم يفتحه بعد مراجعة السداد. أسعار المسارات تظهر للمتعلّمين بعد حفظها.</Heading>
    <ErrorBox message={targets.error} retry={targets.reload} />
    {targets.loading && <Loading text="جارٍ قراءة المسارات والدروس…" />}
    <div className="commercial-settings">
      <section className="panel stack" aria-labelledby="commercial-users">
        <h2 id="commercial-users">صلاحيات المتعلمين</h2>
        <form className="commercial-search" onSubmit={searchAccounts}>
          <label>البحث عن متعلّم<input type="search" maxLength={80} value={search} onChange={event => setSearch(event.target.value)} placeholder="الاسم أو اسم المستخدم" /></label>
          <button className="btn" disabled={accounts.loading || search.trim().length === 1}>بحث</button>
        </form>
        <ErrorBox message={accounts.error} retry={accounts.reload} />
        {accounts.loading && <Loading text="جارٍ قراءة الحسابات…" />}
        {accounts.data?.length === 0 && <p className="muted">لا توجد حسابات مطابقة.</p>}
        {!!accounts.data?.length && <label>حساب المتعلّم<select value={selectedUser} onChange={event => setSelectedUser(event.target.value)}>
          <option value="">اختر الحساب</option>{accounts.data.map(item => <option key={item.userName} value={item.userName}>{item.displayName} · {item.userName}</option>)}
        </select></label>}
        {account && targets.data && <AccountAccess key={account.userName} account={account} scope={scope} targets={targets.data}
          onChanged={updated => setUpdatedAccounts(previous => ({ ...previous, [updated.userName]: updated }))} />}
      </section>
      <section className="panel stack" aria-labelledby="commercial-prices">
        <h2 id="commercial-prices">أسعار المسارات</h2>
        <ErrorBox message={offers.error} retry={offers.reload} />
        {offers.loading && <Loading text="جارٍ قراءة الأسعار…" />}
        {!!targets.data?.goals.length && <label>المسار<select value={selectedGoal} onChange={event => setSelectedGoal(event.target.value)}>
          <option value="">اختر المسار</option>{targets.data.goals.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select></label>}
        {goal && offers.data && <OfferForm key={goal.id} goal={goal} offer={offer} scope={scope} onSaved={saved => {
          setUpdatedOffers(previous => ({ ...previous, [goal.id]: saved }));
          onOffersChanged();
        }} />}
      </section>
    </div>
  </>;
}
