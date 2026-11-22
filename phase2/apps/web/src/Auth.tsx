import { useRef, useState, type FormEvent } from 'react';
import { errorText, request, type SessionScope } from './api';
import { BrandWordmark, PRODUCT_DESCRIPTOR } from './brand';
import type { User } from './types';
import { ErrorBox } from './ui';
import './auth.css';

export function Auth({ scope, onIdentity, commercial = false, recovering = false, onPasswordReset, contactUrl }: {
  scope: SessionScope; onIdentity: (userId: string) => Promise<boolean>; commercial?: boolean;
  recovering?: boolean; onPasswordReset: () => void; contactUrl?: string | null;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [show, setShow] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const result = await request<{ user: User }>(`/auth/${mode}`, { method: 'POST', scope, body: {
        userName: data.get('userName'), password: data.get('password'),
        ...(mode === 'register' ? { displayName: data.get('displayName') } : {}),
      } });
      form.reset();
      if (await onIdentity(result.user.id) && window.location.hash === '#auth') window.location.hash = '#plan';
    } catch (cause) { setError(errorText(cause)); requestAnimationFrame(() => errorRef.current?.focus()); }
    finally { setBusy(false); }
  }
  const registering = mode === 'register';

  return <section className="auth-layout" aria-labelledby="auth-heading">
    <div className="auth-identity">
      <BrandWordmark />
      <p>{PRODUCT_DESCRIPTOR}</p>
    </div>
    <div className="auth-form-panel">
      {recovering ? <PasswordRecovery scope={scope} onPasswordReset={onPasswordReset} contactUrl={contactUrl} /> : <>
        <h1 id="auth-heading">{registering ? 'إنشاء حساب متعلم' : 'تسجيل الدخول'}</h1>
        <p className="muted">{registering ? 'احفظ خطتك وتقدّمك في حسابك.' : 'ادخل إلى حسابك لمتابعة خطتك.'}</p>
        {commercial && <p className="notice">إنشاء الحساب لا يفعّل الوصول المدفوع تلقائيًا. يتم التفعيل بواسطة إدارة المنصة بعد التحقق من الشراء.</p>}
        <div className="auth-mode" role="group" aria-label="نوع الدخول">
          <button
            type="button" className="btn" disabled={busy} aria-pressed={!registering}
            onClick={() => { setMode('login'); setError(''); }}
          >دخول</button>
          <button
            type="button" className="btn" disabled={busy} aria-pressed={registering}
            onClick={() => { setMode('register'); setError(''); }}
          >حساب جديد</button>
        </div>
        <div ref={errorRef} tabIndex={-1}><ErrorBox message={error} /></div>
        <form key={mode} onSubmit={submit} aria-busy={busy} className="stack auth-form">
          <label>
            اسم المستخدم
            <input name="userName" autoComplete="username" dir="auto" required minLength={3} maxLength={40}
              autoCapitalize="none" spellCheck={false} aria-describedby="username-help" />
          </label>
          <p id="username-help" className="field-help">من 3 إلى 40 حرفًا. يمكنك استخدام الحروف العربية أو اللاتينية والأرقام والرموز <bdi dir="ltr">. _ -</bdi></p>
          {registering && <label>
            الاسم الظاهر
            <input name="displayName" autoComplete="nickname" dir="auto" required minLength={2} maxLength={80} />
          </label>}
          <label>
            كلمة المرور
            <input name="password" type={show ? 'text' : 'password'} autoComplete={registering ? 'new-password' : 'current-password'}
              required minLength={registering ? 12 : undefined} maxLength={128} aria-describedby={registering ? 'password-help' : undefined} />
          </label>
          {registering && <p id="password-help" className="field-help">استخدم من 12 إلى 128 حرفًا. يمكنك لصق كلمة مرور من مدير كلمات المرور.</p>}
          <label className="check-label">
            <input type="checkbox" checked={show} onChange={e => setShow(e.target.checked)} />
            إظهار كلمة المرور
          </label>
          <button type="submit" className="btn primary auth-submit" disabled={busy}>
            {busy ? 'جارٍ المتابعة…' : registering ? 'إنشاء الحساب' : 'تسجيل الدخول'}
          </button>
        </form>
        {!registering && <a className="btn text auth-guest" href="#auth/recover">نسيت كلمة المرور؟</a>}
        <a className="btn text auth-guest" href="#start">{commercial ? 'تفاصيل الوصول إلى المنصة' : 'تصفّح عينة الدروس'}</a>
      </>}
    </div>
  </section>;
}

function PasswordRecovery({ scope, onPasswordReset, contactUrl }: {
  scope: SessionScope; onPasswordReset: () => void; contactUrl?: string | null;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [show, setShow] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);

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
      await request('/auth/reset-password', { method: 'POST', scope, body: {
        userName: data.get('userName'), recoveryCode: data.get('recoveryCode'), newPassword: data.get('newPassword'),
      } });
      if (scope.signal.aborted) return;
      form.reset();
      onPasswordReset();
    } catch (cause) {
      if (!scope.signal.aborted) { setError(errorText(cause)); requestAnimationFrame(() => errorRef.current?.focus()); }
    } finally { setBusy(false); }
  }

  return <>
    <h1 id="auth-heading">استرجاع الحساب</h1>
    <p className="muted">استخدم رمز الاسترجاع الذي حفظته أو الرمز المؤقت من إدارة المنصة.</p>
    <div ref={errorRef} tabIndex={-1}><ErrorBox message={error} /></div>
    <form className="stack auth-form" onSubmit={submit} aria-busy={busy}>
      <label>اسم المستخدم<input name="userName" autoComplete="username" dir="auto" required minLength={3} maxLength={40} spellCheck={false} autoCapitalize="none" /></label>
      <label>رمز الاسترجاع<input name="recoveryCode" type="password" dir="ltr" autoComplete="off" spellCheck={false} required maxLength={128} /></label>
      <label>كلمة المرور الجديدة<input name="newPassword" type={show ? 'text' : 'password'} autoComplete="new-password" minLength={12} maxLength={128} required /></label>
      <label>تأكيد كلمة المرور الجديدة<input name="confirmPassword" type={show ? 'text' : 'password'} autoComplete="new-password" minLength={12} maxLength={128} required /></label>
      <label className="check-label"><input type="checkbox" checked={show} onChange={event => setShow(event.target.checked)} />إظهار كلمة المرور الجديدة</label>
      <button className="btn primary auth-submit" disabled={busy}>{busy ? 'جارٍ الحفظ…' : 'حفظ كلمة المرور الجديدة'}</button>
    </form>
    <p className="field-help">لو فقدت الرمز، اطلب رمزًا مؤقتًا من الإدارة بعد إثبات ملكية الحساب.</p>
    {contactUrl?.startsWith('https://') && <a className="btn text" href={contactUrl} target="_blank" rel="noopener noreferrer">تواصل مع إدارة المنصة</a>}
    <a className="btn text auth-guest" href="#auth">العودة إلى تسجيل الدخول</a>
  </>;
}
