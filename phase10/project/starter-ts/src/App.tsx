import { useState } from 'react';
import { ApiError } from './api.ts';
import { formatPrice, parseInput, readIntegerField } from './model.ts';
import { useProducts } from './useProducts.ts';
import type { SubmitEvent } from 'react';
import type { Catalogue, Product, User } from './model.ts';
import type { ListState } from './useProducts.ts';

interface Session { token: string; user: User }
interface ListProps {
  state: ListState;
  admin: boolean;
  onEdit: (product: Product) => void;
  onDelete: (product: Product) => void;
  busy: boolean;
}

export function ProductList({ state, admin, onEdit, onDelete, busy }: ListProps) {
  if (state.status === 'loading') return <p role="status">جارٍ تحميل المنتجات…</p>;
  if (state.status === 'error') return <p role="alert">{state.message}</p>;
  if (state.products.length === 0) return <p role="status">لا توجد منتجات تطابق البحث.</p>;
  return <ul className="products">{state.products.map(product =>
    <li key={product.id}>
      <div className="product-heading"><h3>{product.name}</h3><strong>{formatPrice(product.price_minor)}</strong></div>
      <p>{product.category} · المخزون {product.stock}</p>
      {admin && <div className="actions">
        <button disabled={busy} onClick={() => onEdit(product)}>تعديل {product.name}</button>
        <button disabled={busy} onClick={() => onDelete(product)}>حذف {product.name}</button>
      </div>}
    </li>
  )}</ul>;
}

export default function App({ api, demo = true }: { api: Catalogue; demo?: boolean }) {
  const [filters, setFilters] = useState({ q: '', category: '' });
  const [draftFilters, setDraftFilters] = useState({ q: '', category: '' });
  const [revision, setRevision] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [editing, setEditing] = useState<Product | null>(null);
  const [removing, setRemoving] = useState<Product | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const state = useProducts(api, filters, revision);
  const admin = session?.user.role === 'admin';

  function endSession() {
    setSession(null);
    setEditing(null);
    setRemoving(null);
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) endSession();
      setError(reason instanceof Error ? reason.message : 'تعذّر إكمال العملية.');
    } finally {
      setBusy(false);
    }
  }
  function search(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setFilters({ q: String(values.get('q')).trim(), category: String(values.get('category')).trim() });
    setRevision(value => value + 1);
  }
  function login(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const passwordField = form.querySelector<HTMLInputElement>('input[name="password"]');
    if (passwordField) passwordField.value = '';
    void perform(async () => {
      const token = await api.login(String(values.get('username')), String(values.get('password')));
      try {
        const user = await api.me(token);
        form.reset();
        setSession({ token, user });
      } catch (reason) {
        await api.logout(token).catch(() => {});
        throw reason;
      }
    });
  }
  function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    void perform(async () => {
      const input = parseInput({
        name: values.get('name'), category: values.get('category'),
        price_minor: readIntegerField(values.get('price_minor')), stock: readIntegerField(values.get('stock')),
      });
      await api.save(session.token, input, editing?.id);
      form.reset();
      setEditing(null);
      setFilters({ q: '', category: '' });
      setDraftFilters({ q: '', category: '' });
      setRevision(value => value + 1);
      setNotice('تم حفظ المنتج.');
    });
  }
  function remove() {
    if (!session || !removing) return;
    void perform(async () => {
      await api.remove(session.token, removing.id);
      if (editing?.id === removing.id) setEditing(null);
      setRemoving(null);
      setRevision(value => value + 1);
      setNotice('تم حذف المنتج.');
    });
  }

  return <>
    <header><div className="wrapper"><span dir="ltr">NEXORA CODE</span><p>مشروع الكتالوج</p></div></header>
    <main className="wrapper">
      <h1>كتالوج المنتجات</h1>
      <section aria-labelledby="account"><h2 id="account">الحساب</h2>
        {session ? <div className="row"><p>{session.user.username} · {admin ? 'مسؤول' : 'قارئ'}</p>
          <button disabled={busy} onClick={() => void perform(async () => {
            await api.logout(session.token);
            endSession();
            setNotice('تم تسجيل الخروج.');
          })}>تسجيل الخروج</button></div> : <>
          {demo && <p>للتدريب المحلي، استخدم <bdi>admin</bdi> أو <bdi>reader</bdi> وكلمة المرور <bdi>training</bdi>.</p>}
          <form onSubmit={login} className="row">
            <label>اسم المستخدم<input name="username" autoComplete="username" maxLength={64} required /></label>
            <label>كلمة المرور<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>
            <button disabled={busy}>تسجيل الدخول</button>
          </form></>}
      </section>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <section aria-labelledby="browse"><h2 id="browse">تصفّح المخزون</h2>
        <form key={JSON.stringify(filters)} onSubmit={search} className="row">
          <label>ابحث بالاسم<input name="q" value={draftFilters.q} onChange={event => { const q = event.currentTarget.value; setDraftFilters(previous => ({...previous, q})); }} maxLength={100} /></label>
          <label>التصنيف الكامل<input name="category" value={draftFilters.category} onChange={event => { const category = event.currentTarget.value; setDraftFilters(previous => ({...previous, category})); }} maxLength={60} /></label>
          <button>بحث</button>
        </form>
        <ProductList state={state} admin={admin} onEdit={product => { setEditing(product); setRemoving(null); }}
          onDelete={product => setRemoving(product)} busy={busy} />
        {removing && <div className="row"><p>هل تريد حذف {removing.name}؟</p>
          <button disabled={busy} onClick={remove}>تأكيد الحذف</button>
          <button disabled={busy} onClick={() => setRemoving(null)}>إلغاء الحذف</button></div>}
      </section>
      {admin && <section aria-labelledby="edit"><h2 id="edit">{editing ? 'تعديل المنتج' : 'إضافة منتج'}</h2>
        <form key={editing?.id ?? 'new'} onSubmit={save} className="editor">
          <label>اسم المنتج<input name="name" defaultValue={editing?.name ?? ''} maxLength={100} required /></label>
          <label>تصنيف المنتج<input name="category" defaultValue={editing?.category ?? ''} maxLength={60} required /></label>
          <label>السعر بالقروش<input name="price_minor" type="number" defaultValue={editing?.price_minor} min="0" max="100000000" step="1" required /></label>
          <label>الكمية المتاحة<input name="stock" type="number" defaultValue={editing?.stock} min="0" max="1000000" step="1" required /></label>
          <div className="actions"><button disabled={busy}>حفظ المنتج</button>
          {editing && <button type="button" disabled={busy} onClick={() => setEditing(null)}>إلغاء التعديل</button>}</div>
        </form>
      </section>}
    </main>
  </>;
}
