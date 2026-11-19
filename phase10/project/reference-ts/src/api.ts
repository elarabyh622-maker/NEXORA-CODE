import { isRecord, parseProduct, parseProducts, parseUser } from './model.ts';
import type { Catalogue } from './model.ts';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function createApi(send: typeof fetch = fetch): Catalogue {
  async function request(path: string, method = 'GET', token = '', body?: unknown, signal?: AbortSignal): Promise<unknown> {
    const headers = new Headers();
    if (token) headers.set('Authorization', 'Bearer ' + token);
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    const response = await send('/api/' + path, { method, headers, signal, body: JSON.stringify(body) });
    if (!response.ok) {
      const problem: unknown = await response.json().catch(() => null);
      const detail = isRecord(problem) && typeof problem.detail === 'string' ? problem.detail : 'تعذّر إكمال الطلب.';
      throw new ApiError(response.status, detail + ' (' + response.status + ')');
    }
    if (response.status === 204) return;
    return response.json();
  }

  return {
    async list(filters, signal) {
      const query = new URLSearchParams({ q: filters.q, category: filters.category });
      return parseProducts(await request('products?' + query, 'GET', '', undefined, signal));
    },
    async login(username, password) {
      const result = await request('login', 'POST', '', { username, password });
      if (!isRecord(result) || typeof result.access_token !== 'string' || !result.access_token ||
          result.token_type !== 'bearer' || (result.role !== 'admin' && result.role !== 'reader')) {
        throw new Error('لم يُرجع الخادم بيانات جلسة صالحة.');
      }
      return result.access_token;
    },
    async me(token) { return parseUser(await request('me', 'GET', token)); },
    async logout(token) { await request('logout', 'POST', token); },
    async save(token, input, id) {
      const path = id === undefined ? 'products' : 'products/' + id;
      return parseProduct(await request(path, id === undefined ? 'POST' : 'PUT', token, input));
    },
    async remove(token, id) { await request('products/' + id, 'DELETE', token); },
  };
}
