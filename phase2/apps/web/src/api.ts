import type { User } from './types';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export type SessionScope = { userId: string | null; signal: AbortSignal };
type Csrf = { token: string; userId: string | null };
type RequestOptions = { method?: string; body?: unknown; signal?: AbortSignal; scope?: SessionScope };
export const SESSION_INVALIDATED = 'masar:session-invalidated';
export const ACCESS_INVALIDATED = 'masar:access-invalidated';
export function applicationPath(path: string) {
  const pathname = typeof window === 'undefined' ? '' : window.location?.pathname ?? '';
  const mount = ['/nexora-pilot', '/nexora-commercial'].find(base => pathname === base || pathname.startsWith(`${base}/`));
  return `${mount ?? ''}${path}`;
}
const API = applicationPath('/api/v1');
const fallback: Record<number, string> = {
  400: 'راجع البيانات المدخلة ثم حاول مجددًا.',
  401: 'يلزم تسجيل الدخول، أو انتهت جلستك. سجّل الدخول ثم أعد المحاولة.',
  403: 'لا تملك صلاحية لهذا الإجراء، أو تحتاج حماية الجلسة إلى تحديث.',
  404: 'لم نجد العنصر المطلوب. حدّث الصفحة أو اختر محتوى آخر.',
  409: 'تغيرت النسخة المحفوظة في مكان آخر. راجع أحدث نسخة قبل إعادة الحفظ.',
  429: 'محاولات كثيرة خلال وقت قصير. انتظر قليلًا ثم حاول مجددًا.',
  500: 'تعذر الوصول إلى الخدمة الآن. حاول مجددًا بعد قليل. لم نؤكد الحفظ.',
  503: 'الخدمة غير متاحة الآن. حاول مجددًا بعد قليل. لم نؤكد الحفظ.',
};

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'تعذر الاتصال الآن. تحقق من اتصالك ثم أعد المحاولة. لم نؤكد حفظ طلبك.';
}

async function retryCatalog(signal?: AbortSignal) {
  signal?.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const done = () => { signal?.removeEventListener('abort', aborted); resolve(); };
    const timer = setTimeout(done, 400);
    const aborted = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', aborted);
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', aborted, { once: true });
    if (signal?.aborted) aborted();
  });
}

async function send<T>(path: string, options: RequestOptions, token?: string, attempt = 0): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers['X-CSRF-TOKEN'] = token;
  const timeout = AbortSignal.timeout(20000);
  let response: Response;
  try {
    response = await fetch(API + path, {
      method: options.method ?? 'GET', headers, credentials: 'same-origin', cache: 'no-store',
      signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout,
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(0, 'network', 'تعذر الوصول إلى الخدمة. أعد المحاولة بعد قليل. لم نؤكد تنفيذ الطلب أو حفظه.');
  }
  options.signal?.throwIfAborted();
  if (!response.ok) {
    const data = await response.json().catch(() => null) as { code?: string; message?: string } | null;
    if (path === '/catalog' && (options.method ?? 'GET') === 'GET' && response.status === 503 &&
        attempt === 0 && (data?.code === 'service_unavailable' || data?.code === 'database_unavailable')) {
      await retryCatalog(options.signal);
      return send<T>(path, options, token, 1);
    }
    if (data?.code === 'access_required' && typeof window !== 'undefined') window.dispatchEvent(new Event(ACCESS_INVALIDATED));
    const message = data?.code === 'access_required'
      ? 'الوصول إلى المحتوى غير مفعّل لهذا الحساب. تواصل مع إدارة المنصة ثم حدّث حالة الوصول.'
      : data?.message && /[\u0600-\u06ff]/.test(data.message)
      ? data.message : fallback[response.status] ?? 'حدث خطأ في الخدمة. أعد المحاولة بعد قليل.';
    throw new ApiError(response.status, data?.code ?? 'request_failed', message);
  }
  if (response.status === 204) return undefined as T;
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new ApiError(503, 'unavailable', 'الخدمة لا تعيد بيانات صالحة الآن. تحقق من تشغيل الخادم ثم أعد المحاولة.');
  }
  return await response.json() as T;
}

function identityChanged() {
  return new ApiError(409, 'session_changed', 'تغير الحساب في المتصفح. تحقّق من اسم الحساب قبل إعادة المحاولة.');
}

async function assertCurrentUser(userId: string | null, signal: AbortSignal) {
  const user = await readUser(signal);
  signal.throwIfAborted();
  if ((user?.id ?? null) !== userId) throw identityChanged();
}

async function readCsrf(signal: AbortSignal): Promise<Csrf> {
  const data = await send<Csrf>('/auth/csrf', { signal });
  if (typeof data?.token !== 'string' || !data.token || (data.userId !== null && typeof data.userId !== 'string')) {
    throw new ApiError(503, 'csrf_unavailable', 'تعذر التحقق من حماية الجلسة وهوية الحساب. حدّث الجلسة ثم أعد المحاولة.');
  }
  return data;
}

async function readUser(signal: AbortSignal): Promise<User | null> {
  try {
    const result = await send<{ user: User }>('/auth/me', { signal });
    if (typeof result?.user?.id !== 'string' || !result.user.id) {
      throw new ApiError(503, 'identity_unavailable', 'تعذر التحقق من هوية الحساب. أعد المحاولة.');
    }
    return result.user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function verifySession(signal: AbortSignal): Promise<User | null> {
  const [user, csrf] = await Promise.all([readUser(signal), readCsrf(signal)]);
  signal.throwIfAborted();
  if ((user?.id ?? null) !== csrf.userId) throw identityChanged();
  return user;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const scope = options.scope;
  const credentialSubmission = path === '/auth/login' || path === '/auth/register' || path === '/auth/reset-password';
  const identityEndpoint = credentialSubmission || path === '/auth/logout' || path === '/auth/change-password';
  const protectedRead = path.startsWith('/me/') || path.startsWith('/learning-plans/') || path.startsWith('/admin/')
    || path.startsWith('/lab/drafts/') || path.startsWith('/lab/runs/') || path.startsWith('/lab/evidence?');
  if (!scope) {
    if (method !== 'GET' || protectedRead) {
      throw new ApiError(401, 'session_unverified', 'حدّث الجلسة للتحقق من الحساب قبل متابعة الطلب.');
    }
    return send<T>(path, options);
  }

  const signal = options.signal ? AbortSignal.any([options.signal, scope.signal]) : scope.signal;
  try {
    signal.throwIfAborted();
    let token: string | undefined;
    if (method !== 'GET') {
      const csrf = await readCsrf(signal);
      if (csrf.userId !== scope.userId) throw identityChanged();
      token = csrf.token;
      signal.throwIfAborted();
    }
    const data = await send<T>(path, { ...options, signal }, token).catch(async error => {
      // A 404 can mean a missing draft or plan. Interpret it only after confirming the account.
      if (method === 'GET' && error instanceof ApiError && (error.status === 403 || error.status === 404)) {
        await assertCurrentUser(scope.userId, signal);
      }
      throw error;
    });
    if (method === 'GET') await assertCurrentUser(scope.userId, signal);
    // Auth endpoints change the cookie. Their caller re-verifies the session before using the new identity.
    if (!identityEndpoint) signal.throwIfAborted();
    return data;
  } catch (error) {
    if (!signal.aborted && error instanceof ApiError &&
        (error.code === 'session_changed' || error.code === 'csrf_invalid' || (error.status === 401 && !credentialSubmission))) {
      window.dispatchEvent(new Event(SESSION_INVALIDATED));
    }
    throw error;
  }
}

export const segment = (value: string) => encodeURIComponent(value);
