# Masar API — تنفيذ المرحلة الثانية

الحالة: تنفيذ المسارات وأوامر الصيانة اكتمل، ونجح بناء API مع Domain الحقيقي. هذا الملف يخص Backend فقط؛ نتائج PostgreSQL/HTTP النهائية يثبتها المنسق بعد تشغيله بقاعدة PostgreSQL18 مستقلة.

## نقاط دمج ثابتة

- .NET10، Npgsql10.0.3، SQL parametrized؛ لا EF ولا SQLite ولا InMemory.
- جميع الجداول في `public` وفق توضيح المنسق. جدول الترحيلات **`public.masar_schema_migrations`**، يحوي `name,checksum,applied_at`، ويجب ألا يملك `masar_app` أي صلاحيات عليه. migrations embedded باسم `Migrations.001_foundation.sql` مع SHA256 للبايتات وadvisory session lock، ومعاملة لكل migration. مالك الترحيل `masar_bootstrap`، ودور الويب `masar_app` منفصلان؛ سكريبتات المنسق تمنح DML فقط ولا تمنح CREATE/DDL.
- التشغيل العادي يقرأ `ConnectionStrings__Masar` فقط؛ أوامر CLI الصريحة تقرأ `ConnectionStrings__Migration` فقط. لا ترحيل ولا استيراد ولا admin افتراضي عند بدء الويب.
- `MASAR_DATA_ROOT` مطلوب: مسار مطلق دائم؛ المفاتيح في `data-protection-keys`، application name=`Masar.Phase2.Local`، وDPAPI للمستخدم الحالي على Windows. يجب تشغيل الأمر/الخدمة بنفس هوية Windows للوصول إلى المفاتيح.
- يجري startup اختبار protect/unprotect قصيرًا ويُرفض التشغيل إذا كانت حماية المفاتيح غير متاحة؛ لا fallback إلى مفاتيح plaintext أو مؤقتة. قد تمنع بيئة sandbox المقيدة DPAPI؛ عندها يشغّل المنسق الخدمة المحلية بهوية Windows المصرح بها خارج قيد sandbox، دون تعطيل حماية المفاتيح.
- `ASPNETCORE_ENVIRONMENT=Development` وHTTP على loopback فقط، والمنفذ الافتراضي5180. خارج Development يُرفض أي listener HTTP أو طلب غير HTTPS، دون الاعتماد على forwarded headers. Production على منصة غير Windows مرفوض إلى حين تهيئة حماية مفاتيح مناسبة.
- الملفات المبنية إلى `src/Masar.Api/wwwroot`، SPA fallback خارج `/api`؛ مسار API غير معروف يبقى JSON404.

## أوامر CLI

تُمرر أسرار الاتصال من بيئة مؤقتة بواسطة سكريبتات المنسق، ولا توضع في أسطر الأوامر أو ملفات المصدر:

```text
dotnet Masar.Api.dll --migrate
dotnet Masar.Api.dll --import-bundle <absolute-path>
dotnet Masar.Api.dll --import-bundle <absolute-path> --publish-initial
dotnet Masar.Api.dll --promote-admin <existing-userName>
```

الاستيراد مطابق JSONB لا يغيّر إصدارًا موجودًا. اختلاف payload بنفس releaseId يعطي فشلًا. نشر البداية المحلي مقيد بعينة `phase1-ar-v1` ذات3دروس، قبل وجود أي نشر سابق؛ إعادة الأمر للعينة المنشورة نفسها آمنة. بعد ذلك الانتقالات عبر مراجعات API. CLI لا يطبع exception message أو connection string، ويخرج1 عند فشل و0 عند نجاح.

حد ملفات حزم المحتوى في أوامر CLI هو 2 MiB. حد جسم طلب HTTP هو 1 MiB.

## قرارات السلوك والأمن

- الحسابات تستخدم `PasswordHasher<Account>` القياسي. اسم المستخدم NFKC/lowercase invariant؛ حروف وأرقام Unicode و`._-` فقط، دون أخذ role من المتصفح. الدور المعاد `Learner/Author/Reviewer/Admin`.
- Cookie `Masar.Session`:256bit عشوائي، HttpOnly/SameSiteStrict/8h، لا يخزن بالـDB إلا SHA256. الدور والحساب يُقرآن من DB كل طلب، وlogout يضع `revoked_at`؛ تسجيل الدخول يدور الجلسة الحالية.
- يستخدم كل طلب كتابة تحت `/api` رأس `X-CSRF-TOKEN` مع cookie `Masar.Csrf`، بما في ذلك التسجيل والدخول ومعاينة الخطة. يعيد `GET /api/v1/auth/csrf` كائن `{token,userId}`. تكون `userId` قيمة UUID للمستخدم المرتبط بالرمز أو `null` للزائر. قبل الكتابة تتحقق الواجهة من مطابقة هذه القيمة لهوية الحساب المعروض. عند اختلافها تعيد مزامنة الهوية وحالة الحساب، وتلغي العملية التي بدأت في الحالة السابقة. يتحقق الخادم من الرمز مع هوية الجلسة في كل كتابة. يعود الرمز المفقود أو غير الصالح بـ400. تظل ردود 401 و403 بصيغة JSON.
-120طلب/دقيقة/IP عامة،12طلب/دقيقة/IP لعمليات الدخول/التسجيل.5فشل/15دقيقة لكل username normalized تُقفل15دقيقة في DB، برسالة401 عامة وdummy standard-hash للمستخدم غير الموجود. هذه سياسة أساس محلي وليست منظومة حماية شاملة ضد إساءة استخدام موزعة.
- ينشئ Author أو Admin المسودة ويقدمها إلى `technical_review`. يتولى Reviewer أو Admin مراجعة `learning_review` والنشر والتقاعد. كل انتقال يسجل audit ويتطلب `expectedVersion`، ويعود بـ409 عند تعارض النسخة. تُحفظ نسخ المحتوى الجديدة بمعرف `releaseId` جديد.
- لا `acceptedAnswers` في أي استجابة متعلم. يُحذف `explanation` الخاص بالتمرين من محتوى القراءة ويعود بعد التقييم؛ شروح أمثلة الدروس باقية.
- ملكية الخطط والمسودات والتقدم والمحاولات مشتقة من الجلسة. خطة مستخدم آخر404. تغيير الهدف/release ينشئ revision؛ وجود خطة يتطلب expectedCurrentRevision مطابقًا. يحفظ snapshot كامل وخريطة الإصدار المثبتة.
- نفس idempotencyKey للمستخدم مع نفس payload يعيد المحاولة نفسها؛ اختلاف answer/hints/release/lesson/exercise يعطي409. المعاملات تقفل صف المالك لتسلسل المحاولات/revisions. التصحيح من Domain على الخادم فقط، ولا تؤخذ correct/achieved/role الزائدة كمصدر حقيقة.
- اكتمال الدرس: نجاح موثوق مرة واحدة في كل تمرين بالدرس؛ التكرار لا يزيد solved. المهارات المرتبطة بدرس مكتمل تصبح practiced فقط (حتى إذا استُخدمت تلميحات)، ولا تُمنح demonstrated. المخطط يستخدم هذه المهارات فقط للإصدار نفسه؛ لا يهاجر الدليل تلقائيًا بين الإصدارات.
- draft expectedVersion=0 لإنشاء، ثم نسخة مطابقة للتحديث، وإلا409. answer حتى4096حرفًا؛ لا كود يُنفذ.
- `/health` يفحص العملية، `/api/v1/health` اتصال DB ووجود جداول التهيئة، برسالة آمنة503 عند عدم الجاهزية؛ لا يحتاج runtime role قراءة جدول الترحيلات.

## الإصدار الافتراضي والفهرس

- يعيد `GET /api/v1/admin/releases` كائن `{releases,activeReleaseId}`. قيمة `activeReleaseId` هي المعرف النصي للإصدار الافتراضي المنشور أو `null`.
- يستخدم Reviewer أو Admin المسار `POST /api/v1/admin/releases/{id}/activate` بجسم `{expectedVersion}` لتعيين إصدار منشور افتراضيًا. يستخدم `{id}` قيمة UUID. يعيد نجاح الطلب 200 مع `{id,releaseId,status,version,activeReleaseId}` ويزيد نسخة الإصدار. يعود بـ409 عند تعارض النسخة، وبـ400 عند محاولة تفعيل إصدار غير منشور. يسجل `release.activate` الإصدار السابق والمختار في المعاملة نفسها.
- اختيار إصدار البداية إجراء مستقل عن النشر. يحدد أمر `--publish-initial` إصدار العينة الافتراضي أثناء التهيئة الأولى. عند تقاعد الإصدار الافتراضي يحذف الخادم تعيينه ويسجل `release.deactivate`، وتعود `activeReleaseId` بقيمة `null` حتى يختار المراجع إصدارًا منشورًا. يمكن تفعيل البديل قبل تقاعد الإصدار السابق لتستمر نقطة البداية.
- يعيد `GET /api/v1/catalog` الإصدارات المنشورة والأهداف التابعة للإصدار الافتراضي من قراءة واحدة. حقول الهدف هي `id,title,description,status,skillIds`. عند غياب الافتراضي تكون `goals` فارغة وتبقى الإصدارات المنشورة في `releases`.
- يخضع `GET /api/v1/content/{releaseId}?view=overview` لصلاحيات مسار المحتوى الكامل ويستخدم `Cache-Control: no-store`. يعيد بيانات الفهرس والخريطة، ويقتصر كل درس في `sample.lessons` على `id,title,summary,minutes,exampleLanguages`. تُقرأ نصوص الدرس وتمارينه عبر `GET /api/v1/content/{releaseId}/lessons/{lessonId}`.
- تُشغّل أمثلة Go محليًا. في الوضع التجاري يُتاح تنزيل `/projects/go-tasks-api-starter-v1.zip` لأصحاب صلاحية الوصول الكامل أو صلاحية مسار `go` أو درس `go-project-01`.
- تُقرأ الخطط المحفوظة ومراجعاتها والتقدم من إصدارها الأصلي بعد التفعيل أو التقاعد. تتطلب قراءة المحتوى العامة والكتابات الجديدة إصدارًا منشورًا.

## المصادر الرسمية

- [ASP.NET Core antiforgery](https://learn.microsoft.com/en-us/aspnet/core/security/anti-request-forgery?view=aspnetcore-10.0)
- [ASP.NET Core authentication/session validation](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/cookie?view=aspnetcore-10.0)
- [Npgsql data sources, transactions, parameters](https://www.npgsql.org/doc/basic-usage.html)

## التحقق

بتاريخ 2026-11-11 نجح بناء Release مستقل بعد إصلاح P2-03 وإضافة هوية CSRF بصفر تحذيرات وأخطاء. اختبارات التكامل الخاصة بالتفعيل والتقاعد ومزامنة الحساب بين التبويبات لدى المنسق.

`dotnet build src/Masar.Api/Masar.Api.csproj --nologo --verbosity minimal` ثم build Release نجحا على SDK10.0.403 بتاريخ2026-11-10، بصفر أخطاء وصفر تحذيرات، وبمرجع Domain الفعلي دون stubs. قبل إضافة startup key-ring probe جرى HTTP smoke على listener منفصل5192 واتصال DB متعمد غير متاح: `/health`200، DB health503JSON آمن، anonymous me401JSON، API غير معروف404JSON، login بلاCSRF400JSON. ظهر أن sandbox يمنع DPAPI؛ لذلك شُدد startup ليرفض هذه الحالة صراحة. لا يعتبر ذلك إثبات PostgreSQL runtime. أوامر PostgreSQL/HTTP النهائية يجريها المنسق؛ لا يُدّعى نجاحها من فحص البناء.

بعد إضافة key-ring probe، نجح تشغيل الفحص المحلي خارج sandbox بهوية Windows الحالية مع DPAPI: إصدار CSRF200 مع cookie/token، رمز غير صالح400، ورمز صالح اجتاز الفحص ووصل لاتصال DB المتعمد غير المتاح فعاد500JSON عام دون تفاصيل. أُوقف listener5192 بعد الفحص. كذلك رُفض بدء Production مع listener HTTP بخروج غير ناجح وسبب HTTPS واضح.

أفاد المنسق بتاريخ2026-11-10 بنجاح `--migrate` والاستيراد الأولي على PostgreSQL18 الحقيقي لكل من `masar_phase2` و`masar_phase2_tests` باستخدام Release DLL والأدوار المنفصلة. هذا دليل تشغيل DB أساسي من جلسة المنسق؛ اختبارات HTTP/DB المتكاملة والتزامن والصلاحيات تبقى قيد التنفيذ في جلسة المنسق، ولا يستبدلها smoke الخاص بهذه الجلسة.
