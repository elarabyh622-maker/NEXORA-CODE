# الحل المرجعي لمشروع المخزون

يشغّل المشروع محاكاة مخزون محلية ببيانات تجريبية. يستخدم Python 3.10 أو أحدث ومكتبته القياسية.

## التشغيل على Windows

افتح PowerShell في المجلد الذي يحتوي `main.py`.

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe main.py
```

إذا كان `py` غير متاح، استخدم `python --version` و`python -m venv .venv` مع Python 3.10 أو أحدث. يستخدم الأمران الأخيران المفسّر داخل البيئة مباشرة.

## نتائج التحقق

تنجح الاختبارات الثمانية. يستدعي `test_withdraw_full_stock` السحب بكمية مساوية للرصيد ويتحقق من الصفر. يفحص `test_overdraw_preserves_quantity_and_value` الاستثناء والرصيد والقيمة بعد الرفض، ويمرّر `test_invalid_amount_preserves_quantity` حالات الصفر والسالب والقيمة المنطقية والنص والعدد العشري إلى العمليتين. لكل اختبار مخزون جديد ينشئه `setUp`.

يعرض `main.py` الأسطر التالية.

```text
PEN: 0
NOTE: 2
total_minor_units: 720
```

يملك `Inventory` أسطر `StockLine` ويفوّض الاستلام والسحب إليها. كل سطر يملك رصيده، ويشارك بيانات `Product` الثابتة. يستخدم حساب القيمة أعدادًا صحيحة بوحدات صغرى افتراضية. يتحقق `Product.__post_init__` من الرمز والسعر بعد تهيئة الحقول، ويتحقق `StockLine.withdraw` من الكمية والرصيد قبل طرحها.
