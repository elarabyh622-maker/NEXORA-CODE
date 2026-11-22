# مشروع Java 21: إعارة كتب من سطر الأوامر

هذا تدريب محلي ببيانات وأسماء خيالية. تحتاج JDK 21؛ تحقّق باستخدام `javac -version` و`java -version`. لا تحتاج Maven أو Gradle أو Python أو أي مكتبة خارجية. افتح PowerShell داخل مجلد المشروع بعد فك ZIP. احتفظ بنسخة من ملف البيانات قبل التجربة.

## البناء والتشغيل

الأوامر التالية تعمل من جذر المشروع في Windows PowerShell 5.1 أو PowerShell 7:

```powershell
New-Item -ItemType Directory -Force out | Out-Null
javac -encoding UTF-8 -d out src/Library.java src/Lending.java
java -cp out Library data/books.tsv list
java -cp out Library data/books.tsv add B003 "Java Practice"
java -cp out Library data/books.tsv borrow B001 "Mona"
java -cp out Library data/books.tsv return B001
```

نفّذ كل أمر بعد نجاح السابق فقط. `javac` الناجح لا يطبع رسالة؛ افحص `$LASTEXITCODE` وتوقّف إذا لم يكن صفرًا. أوامر التعديل الناجحة تطبع `OK: add` أو `OK: borrow` أو `OK: return`. الفشل يطبع `ERROR:` على stderr ويعيد رمز خروج 1.

يعرض `list` ترويسة `id` ثم `title` ثم `borrower` مفصولة بعلامة Tab، والصفوف بترتيب إدخالها. الحقل الأخير الفارغ يعني أن الكتاب متاح. مثال بيانات البداية:

```text
id<TAB>title<TAB>borrower
B001<TAB>Java Basics<TAB>
B002<TAB>Clean Code<TAB>Sara
```

`<TAB>` توضيح فقط؛ الملف الحقيقي `data/books.tsv` يحتوي علامات Tab. ترميز الملف UTF-8 دون BOM، والترويسة إلزامية. عند غياب الملف يعرض `list` الترويسة دون إنشاء ملف؛ ينشئ أول `add` ناجح الملف إذا كان المجلد موجودًا.

## المهمة الوحيدة

أكمل الدالة `Lending.borrow` داخل `src/Lending.java` فقط. في نسخة البداية ترمي الدالة `UnsupportedOperationException("Borrow is incomplete")`؛ لذلك تفشل الإعارة بأمان ويبقى الملف دون تغيير حتى تكملها.

العقد: تستقبل `List<Library.Book>` ومعرّفًا واسم مستعير، وتعيد قائمة جديدة تحتوي الكتاب نفسه بعد تحديث حقل `borrower`، وتحافظ على الترتيب وباقي الكتب والقائمة الأصلية. استخدم `Library.index(books, id)` للبحث والتحقق من المعرّف، و`Library.field(borrower, "borrower")` للتحقق من الاسم. ارفض الكتاب المعار بالفعل برسالة `Book is already borrowed` باستخدام `IllegalArgumentException`. أنشئ `ArrayList` جديدة وعدّل عنصرها ثم أعدها. لا تقرأ أو تكتب الملفات داخل هذه الدالة؛ الحفظ مسؤولية `Library`.

المعرّفات من `B001` إلى `B999`. العنوان واسم المستعير من 1 إلى 120 وحدة UTF-16، دون مسافات زائدة في البداية أو النهاية أو محارف تحكم، بما فيها Tab والسطر الجديد. لا تكرر المعرّفات. لا يمكن إعارة كتاب غير موجود أو معار بالفعل، ولا إرجاع كتاب متاح. يرفض البرنامج ملفًا تالفًا كله قبل أي تعديل. يحفظ باستبدال ذري في المجلد نفسه؛ إذا لم يدعم نظام الملفات ذلك يفشل الحفظ دون استبدال الملف الأصلي. لا تشغّل عمليتين للتعديل في الوقت نفسه؛ هذا التمرين لا يقدم قفلًا أو معالجة للتعديل المتزامن.

## الاختبارات

اختبارات Java تشغّل CLI في عمليات جديدة، وتستخدم ملفات مؤقتة، وتتحقق من المخرجات ورموز الخروج وبقاء بايتات البيانات كما هي عند الرفض. لا تعدّل بيانات البداية.

```powershell
javac -encoding UTF-8 -d out src/Library.java src/Lending.java
javac -encoding UTF-8 -cp out -d out tests/LibraryTests.java
java -cp out LibraryTests --starter
```

قبل الحل يجب أن تنجح اختبارات الهيكل برسالة `PASSED: starter scaffolding`، وأن تفشل الاختبارات الكاملة التالية عند الإعارة غير المكتملة:

```powershell
java -cp out LibraryTests
```

بعد إكمال الدالة أعد البناء، ثم شغّل الاختبارات الكاملة دون `--starter`. يجب أن تظهر `PASSED: completed library` ويكون `$LASTEXITCODE` صفرًا. لا تستخدم `--starter` بعد الحل؛ فهو يتوقع رفض الإعارة. تشمل الاختبارات الإضافة والقائمة والإعارة والإرجاع والملف التالف والمدخلات غير الصالحة وعدم تعديل قائمة الإدخال. لا يعتبر نجاح اختبارات الهيكل إكمالًا للمهمة.
