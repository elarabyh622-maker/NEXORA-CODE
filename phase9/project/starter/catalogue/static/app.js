"use strict";

const byId = (id) => document.getElementById(id);
const loginForm = byId("login");
const searchForm = byId("search");
const editor = byId("editor");
const money = new Intl.NumberFormat("ar-EG", { style: "currency", currency: "EGP" });
let token = "";
let account = null;
let editingId = null;
let items = [];
let latestSearch = 0;

function closeEditor() {
  editor.hidden = true;
  editor.reset();
  editingId = null;
}

function showSession() {
  byId("session-button").textContent = account ? "خروج · " + account.username : "تسجيل الدخول";
  byId("new-product").hidden = account?.role !== "admin";
  loginForm.hidden = true;
  closeEditor();
  renderProducts();
}

async function api(path, options = {}) {
  const headers = {};
  if (options.body) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = "Bearer " + token;
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("تعذّر الاتصال بالكتالوج. تحقّق من تشغيل الخادم المحلي.");
  }
  if (response.status === 401 && token && headers.Authorization === "Bearer " + token) {
    token = "";
    account = null;
    showSession();
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (Array.isArray(error.detail)) {
      throw new Error("راجع الحقول التالية: " + error.detail.map((d) => d.loc.at(-1)).join("، "));
    }
    throw new Error(error.detail || "تعذّر إتمام الطلب.");
  }
  return response.status === 204 ? null : response.json();
}

function button(label, action) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = label;
  node.className = "secondary";
  node.addEventListener("click", () => perform(node, action));
  return node;
}

function renderProducts() {
  const list = byId("products");
  list.replaceChildren();
  for (const product of items) {
    const row = document.createElement("li");
    row.className = "product";
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = product.name;
    const detail = document.createElement("p");
    detail.textContent = [product.category, money.format(product.price_minor / 100),
      "المخزون: " + product.stock].join(" · ");
    info.append(title, detail);
    row.append(info);
    if (account?.role === "admin") {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("تعديل", () => openEditor(product)), button("حذف", async () => {
        if (!window.confirm("حذف المنتج «" + product.name + "»؟")) return;
        await api("/api/products/" + product.id, { method: "DELETE" });
        if (editingId === product.id) closeEditor();
        await loadProducts("حُذف المنتج.");
      }));
      row.append(actions);
    }
    list.append(row);
  }
}

async function loadProducts(successMessage = "") {
  const request = ++latestSearch;
  // TODO 3: حوّل قيم حقلي البحث إلى query string وأرسلها مع طلب المنتجات.
  byId("status").textContent = "جارٍ تحميل المنتجات…";
  let rows;
  try {
    rows = await api("/api/products");
  } catch (error) {
    if (request === latestSearch) {
      items = [];
      renderProducts();
      byId("status").textContent = error.message;
    }
    return;
  }
  if (request !== latestSearch) return;
  items = rows;
  renderProducts();
  const count = rows.length ? "عدد النتائج: " + rows.length : "لا توجد منتجات مطابقة.";
  byId("status").textContent = successMessage || count;
}

function openEditor(product) {
  closeEditor();
  editingId = product?.id ?? null;
  byId("editor-title").textContent = product ? "تعديل منتج" : "إضافة منتج";
  if (product) {
    for (const key of ["name", "category", "price_minor", "stock"]) {
      editor.elements.namedItem(key).value = product[key];
    }
  }
  editor.hidden = false;
  editor.elements.namedItem("name").focus();
}

async function perform(control, action) {
  control.disabled = true;
  try {
    await action();
  } catch (error) {
    byId("status").textContent = error.message;
  } finally {
    control.disabled = false;
  }
}

function onSubmit(form, action) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    perform(form.querySelector("button"), action);
  });
}

byId("session-button").addEventListener("click", () => {
  if (!account) {
    loginForm.hidden = !loginForm.hidden;
    if (!loginForm.hidden) loginForm.elements.username.focus();
    return;
  }
  perform(byId("session-button"), async () => {
    await api("/api/logout", { method: "POST" });
    token = "";
    account = null;
    showSession();
    byId("status").textContent = "تم تسجيل الخروج.";
  });
});

onSubmit(loginForm, async () => {
  const data = Object.fromEntries(new FormData(loginForm));
  loginForm.elements.password.value = "";
  const result = await api("/api/login", { method: "POST", body: JSON.stringify(data) });
  token = result.access_token;
  try {
    account = await api("/api/me");
  } catch (error) {
    token = "";
    throw error;
  }
  showSession();
  byId("status").textContent = account.role === "admin" ? "يمكنك إدارة المنتجات." : "يمكنك قراءة الكتالوج.";
});

onSubmit(searchForm, loadProducts);
byId("new-product").addEventListener("click", () => openEditor(null));
byId("cancel").addEventListener("click", closeEditor);
onSubmit(editor, async () => {
  const product = Object.fromEntries(new FormData(editor));
  product.price_minor = Number(product.price_minor);
  product.stock = Number(product.stock);
  const path = editingId === null ? "/api/products" : "/api/products/" + editingId;
  await api(path, { method: editingId === null ? "POST" : "PUT", body: JSON.stringify(product) });
  closeEditor();
  await loadProducts("حُفظ المنتج.");
});

loadProducts();
