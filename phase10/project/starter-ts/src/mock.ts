import { ApiError } from './api.ts';
import { parseInput } from './model.ts';
import type { Catalogue, Product, User } from './model.ts';

// الحسابات والأصناف للتجربة المحلية. يبدأ كل تحديث للصفحة بنسخة جديدة.
export function createMockApi(): Catalogue {
  let products: Product[] = [
    { id: 1, name: 'دفتر رسم', category: 'قرطاسية', price_minor: 1250, stock: 7 },
    { id: 2, name: 'حقيبة قماش', category: 'حقائب', price_minor: 8500, stock: 2 },
  ];
  let nextId = 3;
  const sessions = new Map<string, User>();

  function currentUser(token: string) {
    const user = sessions.get(token);
    if (!user) throw new ApiError(401, 'يلزم تسجيل الدخول.');
    return user;
  }
  function requireAdmin(token: string) {
    if (currentUser(token).role !== 'admin') throw new ApiError(403, 'يلزم حساب مسؤول.');
  }
  function requireProduct(id: number) {
    if (!products.some(product => product.id === id)) throw new ApiError(404, 'المنتج غير موجود.');
  }

  return {
    async list({ q, category }, signal) {
      signal?.throwIfAborted();
      return products.filter(product => product.name.toLowerCase().includes(q.trim().toLowerCase()) &&
        (!category.trim() || product.category === category.trim())).map(product => ({ ...product }));
    },
    async login(username, password) {
      if ((username !== 'admin' && username !== 'reader') || password !== 'training') {
        throw new ApiError(401, 'بيانات التدريب غير صحيحة.');
      }
      const token = crypto.randomUUID();
      sessions.set(token, { username, role: username });
      return token;
    },
    async me(token) { return { ...currentUser(token) }; },
    async logout(token) { currentUser(token); sessions.delete(token); },
    async save(token, input, id) {
      requireAdmin(token);
      if (id !== undefined) requireProduct(id);
      const fields = parseInput(input);
      const product = { ...fields, id: id ?? nextId++ };
      products = id === undefined ? [...products, product] :
        products.map(item => item.id === id ? product : item);
      return { ...product };
    },
    async remove(token, id) {
      requireAdmin(token);
      requireProduct(id);
      products = products.filter(item => item.id !== id);
    },
  };
}
