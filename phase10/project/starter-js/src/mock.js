import { ApiError } from './api.js';
import { parseInput } from './model.js';

// الحسابات والأصناف للتجربة المحلية. يبدأ كل تحديث للصفحة بنسخة جديدة.
export function createMockApi() {
  let products = [
    { id: 1, name: 'دفتر رسم', category: 'قرطاسية', price_minor: 1250, stock: 7 },
    { id: 2, name: 'حقيبة قماش', category: 'حقائب', price_minor: 8500, stock: 2 },
  ];
  let nextId = 3;
  const sessions = new Map();

  function currentUser(token) {
    const user = sessions.get(token);
    if (!user) throw new ApiError(401, 'يلزم تسجيل الدخول.');
    return user;
  }
  function requireAdmin(token) {
    if (currentUser(token).role !== 'admin') throw new ApiError(403, 'يلزم حساب مسؤول.');
  }
  function requireProduct(id) {
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
        products; // TODO: أعد مصفوفة جديدة تستبدل المنتج ذي المعرف id.
      return { ...product };
    },
    async remove(token, id) {
      requireAdmin(token);
      requireProduct(id);
      products = products.filter(item => item.id !== id);
    },
  };
}
