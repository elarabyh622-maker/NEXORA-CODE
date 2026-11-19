export interface ProductInput {
  name: string;
  category: string;
  price_minor: number;
  stock: number;
}

export interface Product extends ProductInput {
  id: number;
}

export interface Filters {
  q: string;
  category: string;
}

export interface User {
  username: string;
  role: 'admin' | 'reader';
}

export interface Catalogue {
  list(filters: Filters, signal?: AbortSignal): Promise<Product[]>;
  login(username: string, password: string): Promise<string>;
  me(token: string): Promise<User>;
  logout(token: string): Promise<void>;
  save(token: string, input: ProductInput, id?: number): Promise<Product>;
  remove(token: string, id: number): Promise<void>;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validText(value: unknown, limit: number): value is string {
  return typeof value === 'string' && value.trim().length > 0 &&
    [...value].length <= limit && !value.includes('\0');
}

function validInt(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max;
}

export function parseInput(value: unknown): ProductInput {
  if (!isRecord(value) || !validText(value.name, 100) || !validText(value.category, 60) ||
      !validInt(value.price_minor, 0, 100_000_000) || !validInt(value.stock, 0, 1_000_000)) {
    throw new Error('راجع اسم المنتج والتصنيف والسعر والمخزون.');
  }
  return { name: value.name.trim(), category: value.category.trim(),
    price_minor: value.price_minor, stock: value.stock };
}

export function parseProduct(value: unknown): Product {
  if (!isRecord(value) || !validInt(value.id, 1, Number.MAX_SAFE_INTEGER)) {
    throw new Error('معرّف المنتج غير صالح.');
  }
  return { id: value.id, ...parseInput(value) };
}

export function parseProducts(value: unknown): Product[] {
  if (!Array.isArray(value)) throw new Error('توقّعنا قائمة منتجات من الخادم.');
  const products = value.map(parseProduct);
  if (new Set(products.map(product => product.id)).size !== products.length) {
    throw new Error('تحتوي القائمة على معرّفات مكررة.');
  }
  return products;
}

export function parseUser(value: unknown): User {
  if (!isRecord(value) || !validText(value.username, 64) ||
      (value.role !== 'admin' && value.role !== 'reader')) {
    throw new Error('تعذّر قراءة بيانات الحساب.');
  }
  return { username: value.username, role: value.role };
}

const currency = new Intl.NumberFormat('ar-EG', { style: 'currency', currency: 'EGP' });
export function formatPrice(priceMinor: number) {
  return currency.format(priceMinor / 100);
}

export function readIntegerField(value: unknown): number {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('اكتب قيمة عددية قبل الحفظ.');
  }
  const number = Number(value);
  if (!Number.isSafeInteger(number)) throw new Error('اكتب عددًا صحيحًا.');
  return number;
}
