import { useRef, useState, type FormEvent } from 'react';
import { errorText, request, type SessionScope } from './api';
import { BRAND_ASSETS, PRODUCT_DESCRIPTOR, PRODUCT_NAME } from './brand';
import type { User } from './types';
import { ErrorBox } from './ui';
import './auth.css';

export function Auth({ user, scope, onIdentity, commercial = false }: { user: User | null; scope: SessionScope; onIdentity: (userId: string) => Promise<boolean>; commercial?: boolean }) {
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
      <img src={BRAND_ASSETS.wordmark} width="1445" height="530" alt={`${PRODUCT_NAME} — Learn to Think. Code to Create.`} lang="en" dir="ltr" />
      <p>{PRODUCT_DESCRIPTOR}</p>
    </div>
    <div className="auth-form-panel">
      {user ? <>
        <h1 id="auth-heading">أهلًا، <bdi>{user.displayName}</bdi></h1>
        <p className="muted">أنت مسجل باسم <bdi>{user.userName}</bdi>.</p>
        <ErrorBox message={error} />
        <a className="btn primary auth-submit" href="#plan">الانتقال إلى خطتي</a>
      </> : <>
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
        <a className="btn text auth-guest" href="#start">{commercial ? 'تفاصيل الوصول إلى المنصة' : 'تصفّح عينة الدروس'}</a>
      </>}
    </div>
  </section>;
}
