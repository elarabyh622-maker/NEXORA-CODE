
export function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validText(value, limit) {
  return typeof value === 'string' && value.trim().length > 0 &&
    [...value].length <= limit && !value.includes('\0');
}

function validInt(value, min, max) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max;
}

export function parseInput(value) {
  if (!isRecord(value) || !validText(value.name, 100) || !validText(value.category, 60) ||
      !validInt(value.price_minor, 0, 100_000_000) || !validInt(value.stock, 0, 1_000_000)) {
    throw new Error('راجع اسم المنتج والتصنيف والسعر والمخزون.');
  }
  return { name: value.name.trim(), category: value.category.trim(),
    price_minor: value.price_minor, stock: value.stock };
}

export function parseProduct(value) {
  if (!isRecord(value) || !validInt(value.id, 1, Number.MAX_SAFE_INTEGER)) {
    throw new Error('معرّف المنتج غير صالح.');
  }
  return { id: value.id, ...parseInput(value) };
}

export function parseProducts(value) {
  if (!Array.isArray(value)) throw new Error('توقّعنا قائمة منتجات من الخادم.');
  const products = value.map(parseProduct);
  if (new Set(products.map(product => product.id)).size !== products.length) {
    throw new Error('تحتوي القائمة على معرّفات مكررة.');
  }
  return products;
}

export function parseUser(value) {
  if (!isRecord(value) || !validText(value.username, 64) ||
      (value.role !== 'admin' && value.role !== 'reader')) {
    throw new Error('تعذّر قراءة بيانات الحساب.');
  }
  return { username: value.username, role: value.role };
}

const currency = new Intl.NumberFormat('ar-EG', { style: 'currency', currency: 'EGP' });
export function formatPrice(priceMinor) {
  return currency.format(priceMinor / 100);
}

export function readIntegerField(value) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('اكتب قيمة عددية قبل الحفظ.');
  }
  const number = Number(value);
  if (!Number.isSafeInteger(number)) throw new Error('اكتب عددًا صحيحًا.');
  return number;
}
