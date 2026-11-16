# عقد تنفيذ المرحلة الثانية — NEXORA CODE

الترقيم المعتمد 1–7. المستخدم طلب تنفيذ المرحلة الثانية بنفس طريقة الجلسات الموازية واختيار model/effort. المرحلة الأولى محفوظة كما هي، وبوابة اختبار فهم مبتدئ فيها PENDING؛ تنفيذ الأساس الجديد مصرح به دون اختلاق نتيجة تلك التجربة.

## النطاق والقرارات

تنفيذ أساس فعلي محلي: .NET 10 API كوحدات داخل تطبيق واحد، PostgreSQL حقيقي مع migrations ذات checksum، واجهة React/TypeScript، حسابات وجلسات Cookie وصلاحيات، محتوى بإصدارات وحالات نشر، خطط شخصية مفسرة ومحفوظة، مسودات وتقدم محفوظان بالخادم. لا Sandbox أو تشغيل كود أو AI أو نشر عام أو مدفوعات.

المنتج التجاري مدفوع. فتح العينة المحلية للتطوير والاختبار لا يحدد سياسة المعاينة العامة. قبل الإطلاق التجاري يجب أن يتحقق الخادم من صلاحية الوصول إلى المحتوى المدفوع؛ الحساب وحده لا يمنحها. التسعير وطريقة التحصيل خارج نطاق هذه المرحلة.

يُستخدم Npgsql 10.0.3 المتاح في cache مع SQL parametrized وmigrations صريحة بدل إدخال ORM إضافي لهذه المرحلة؛ يوثّق المنسق ذلك كقرار قابل للمراجعة. لا قاعدة InMemory أو SQLite لإثبات PostgreSQL. لا RLS أو tenant isolation claim؛ المطلوب ملكية موارد المستخدم وصلاحيات API واختبار مستخدمين فعليًا.

تُستخدم بيانات المرحلة الأولى كعينة قابلة للاستيراد إلى إصدار محتوى أولي واحد. لا تمنح إجابة المتصفح أو نسبة مشاهدة إتقانًا. الهدف المحلي هو foundation ولا يساوي جاهزية إطلاق عام. لا تعديل Docker الموجود، ولا حذف/إعادة تهيئة قواعد أو مجلدات، ولا Git. أسرار الاتصال والاعتماد لا تظهر في chat أو logs أو ملفات المصدر.

## الملكية

1. جلسة Domain: `phase2/src/Masar.Domain/` و`phase2/tests/Masar.Domain.Tests/` و`phase2/docs/DOMAIN.md` فقط.
2. جلسة Backend: `phase2/src/Masar.Api/` و`phase2/database/` و`phase2/docs/API.md` فقط. تملك csproj الخاص بها. لا ملفات الجذر أو Domain أو frontend.
3. جلسة Frontend: `phase2/apps/web/` و`phase2/docs/FRONTEND.md` فقط. تملك package.json/lock الخاصين بها. لا backend/domain/root.
4. المنسق: `phase2/scripts/`، إعداد PostgreSQL وتهيئة البيانات والجلسة الأولى، اختبارات تكامل HTTP/DB، هيكل الحل وconfig العام والتقارير وحالة المشروع والدمج والتصحيحات.

كل العمل داخل F:\تعلم برمجه. لا توقف خدمة Docker أو أي container موجود غير مملوك لهذه المرحلة. لا تثبيت نظامي. لا جلسات إضافية من الجلسات الفرعية. عند الحاجة لتوضيح، سجله في مذكرتك وواصل المستقل منه؛ المنسق يراجع الملفات والحالات.

## عقد Domain (ثابت للدمج)

مشروع library net10.0 بلا dependencies خارجية. namespace `Masar.Domain`. يستخدم System.Text.Json.Nodes لمرونة استيراد عينة المرحلة الأولى دون نسخ كل DTO. ملف المحتوى يتكون من `{sample:<sample.json>,graph:<graph.json>}` تحت اسم bundle.

```csharp
public static class CurriculumEngine {
  public static IReadOnlyList<string> Validate(JsonObject bundle);
  public static JsonObject Plan(JsonObject bundle, string goalId,
    IEnumerable<string>? achievedSkillIds = null,
    IEnumerable<string>? preferredSkillIds = null);
}
```

Validate يفحص تطابق releaseId و3دروس العينة عند الاستيراد الأولي، ثم يسمح بإصدارات عامة بأعداد مختلفة (ليس شرط 3 ثابتًا لكل منهج)، وskillIds والمعرّفات الفريدة ومراجع المتطلبات وتعبيرات AND/OR المتداخلة وDAG محافظة والمجموعات الفارغة، وتمارين choice/text وacceptedAnswers ومراجع الخيارات. Plan يدعم graph phase1 ولا يفرض كل بدائل OR؛ يعيد دائمًا goalId,status,steps,missingSkillIds,uncoveredSkillIds,chosenAlternatives مثل عينة phase1، إضافة plannerVersion="2.0.0". step يحوي lessonId,skillIds,reason. المصدر للمنطق المقصود phase1/lib/graph.mjs. رفض خريطة غير صحيحة لا يرمي StackOverflow؛ قيود حجم/عمق واضحة. مفهوم المحتوى "planned" لا يصير منشورًا بتوفر اسمه.

```csharp
public static class ExerciseEvaluator {
  public static JsonObject Evaluate(JsonObject exercise, string answer, int hintsUsed);
}
// correct:boolean, assisted:boolean, explanation:string;
// Arabic digits/trim/NFKC. لا eval، لا قبول جواب فارغ، لا استنتاج إتقان.
```

اختبارات xUnit 2.9.3 وMicrosoft.NET.Test.Sdk 17.14.1 وxunit.runner.visualstudio 2.5.3 متاحة في cache؛ يمكن استخدام pinned packages المتاحة. تركز على السلوك والمراجع والدورات وتغيير الهدف والبدائل والمستوى هنا تجريبي لا تقييم احتراف.

## عقود API للواجهة (كلها JSON، camelCase)

الخادم 127.0.0.1:5180، وdev frontend 127.0.0.1:5173 مع proxy /api إلى 5180. الإنتاج المحلي المبني يقدم static frontend من wwwroot على نفس أصل API. HTTP خاص Development/localhost؛ Production يشترط HTTPS وSecure cookies.

الأخطاء: `{code,message}` بالعربية وحالة HTTP مناسبة، بلا stack traces أو credentials. لا redirect HTML في API 401/403. GET /health يعيد حالة آمنة، GET /api/v1/health يتحقق من DB إذا أمكن.

### هوية

- `GET /api/v1/auth/csrf` → `{token,userId}` ويصدر cookie CSRF. `userId` هو الحساب الحالي أو null للزائر. كل POST/PUT/PATCH/DELETE (بما فيها register/login) تحتاج `X-CSRF-TOKEN` مع cookies. تربط الواجهة الرمز بالهوية المتحققة قبل الكتابة وتجدد الجلسة عند تبدلها.
- `POST /api/v1/auth/register` body `{userName,displayName,password}` → 201 `{user:{id,userName,displayName,role}}` ثم جلسة. role دائمًا Learner. لا كلمات مرور افتراضية أو حساب admin تلقائي من أول زائر. username يدعم حروف العربية، طول 3–40، NFKC وlowercase invariant ومجموعة حروف/أرقام/._-، displayName 2–80، password 12–128.
- `POST /api/v1/auth/login` body `{userName,password}` → `{user:{...}}`. خطأ generic401؛ حدود محاولات وعمر جلسة. PasswordHasher القياسي، لا hash مخصص.
- `GET /api/v1/auth/me` → `{user:{...}}` أو401.
- `POST /api/v1/auth/logout` →204 ويبطل الجلسة المخزنة لا cookie فقط.
- Bootstrap دور Admin بعملية محلية صريحة على username موجود، من SQL/CLI في scripts المنسق، دون كشف credentials. GET role لا يصدق role body.

### محتوى وإصدارات

- `GET /api/v1/catalog` → `{releases:[{id,releaseId,title,status}],goals:[{id,title,description,status,skillIds}],activeReleaseId}`. لا يعرض مسودات لعامة المتعلمين.
- `GET /api/v1/content/{releaseId}` → `{id,releaseId,title,status,sample,graph}` منشور فقط. يحذف acceptedAnswers من الاستجابة العامة وتمارين المستخدم، مع إبقاء شرح الدرس وأمثلة المؤلف؛ يرجع explanations بعد تقييم الخادم. لا تعتمد الواجهة على acceptedAnswers.
- `GET /api/v1/content/{releaseId}/lessons/{lessonId}` → درس منشور بلا acceptedAnswers، أو404.
- `GET /api/v1/admin/releases` لصلاحيات Author/Reviewer/Admin → `{releases:[...],activeReleaseId}`.
- `POST /api/v1/admin/releases` body `{bundle}` →201 `{id,releaseId,status:"draft"}` بعد Validate.
- `POST /api/v1/admin/releases/{id}/transition` body `{status,expectedVersion}`. الحالات draft → technical_review → learning_review → published → retired؛ roles Author للإنشاء وتقديم technical_review، Reviewer/Admin لعبور المراجعات والنشر. لا overwrite للمحتوى المنشور، ولا تعديل bundle بعد إنشائه في المرحلة2؛ النسخ الجديدة هي الطريق. expectedVersion optimistic concurrency و409 عند mismatch. لا تغيير default activeReleaseId بصمت لخطط سابقة. يسجل audit.
- `POST /api/v1/admin/releases/{id}/activate` body `{expectedVersion}` لـ Reviewer/Admin. يتطلب إصدارًا منشورًا ويحفظ اختيار البداية وسجل التدقيق. تقاعد البداية يزيل التعيين، ولا يغيّر أي خطة محفوظة. تعرض الواجهة اختيارًا صريحًا إذا بقيت إصدارات منشورة.

### خطط

- `POST /api/v1/plan-previews` body `{releaseId,goalId}` → Domain Plan مع releaseId. متاح للزائر؛ authenticated uses evidence-based practiced skills من سجل الخادم لهذا الإصدار، لا يقبل achievedSkillIds من العميل.
- `POST /api/v1/learning-plans` body `{releaseId,goalId,expectedCurrentRevision?}` →201 `{id,revision,releaseId,goalId,status,plan}`. خطة لكل user، تغيّر goal/release ينشئ revision ولا يمحو القديم. expectedCurrentRevision مطلوب عند وجود خطة، 409 يمنع overwrite قديم. لا يحسب نشر إصدار جديد ترحيلًا تلقائيًا.
- `GET /api/v1/me/plan` → `{id,revision,releaseId,goalId,status,plan}` أو404.
- `GET /api/v1/me/plan/history` → `{revisions:[{id,revision,releaseId,goalId,createdAt}]}`.
- `GET /api/v1/learning-plans/{id}` → خطة المالك فقط؛404 عند ID مستخدم آخر.

### تقدم ومسودات

- `POST /api/v1/practice/attempts` body `{releaseId,lessonId,exerciseId,answer,hintsUsed,idempotencyKey}` → `{id,correct,assisted,explanation,alreadyRecorded}`. التقييم خادم فقط. payload لا يقبل correct/role/achieved كمصدر حقيقة. المفتاح unique(user,idempotencyKey)؛ نفس الطلب يعود نفسه، تغير payload بالمفتاح نفسه409. الأدلة المرحلة2 هي practiced فقط، لا demonstrated. حفظ محاولات منفصل عن الدروس المكتملة.
- `GET /api/v1/me/progress?releaseId=...` → `{releaseId,completedLessonIds,practicedSkillIds,correctExerciseIds,attemptsCount,solved,total,lessons:[{lessonId,solved,total,complete}],skills:[{skillId,status}]}`. التجميع من نتائج موثوقة؛ unknown/practiced فقط هنا. يحتسب كل exercise مرة في solved وإن تكرر النجاح.
- `GET /api/v1/me/drafts/{releaseId}/{exerciseId}` → `{answer,version}` أو404.
- `PUT /api/v1/me/drafts/{releaseId}/{exerciseId}` body `{answer,expectedVersion}`. expectedVersion0 للإنشاء؛409 عند تعارض، والاستجابة `{answer,version}`. لا مسودة مشتركة بين الحسابات.

## التخزين والتهيئة

Npgsql connection من `ConnectionStrings__Masar` env؛ `ConnectionStrings__Migration` للصيانة فقط. قاعدتا `masar_phase2` و`masar_phase2_tests` منفصلتان في كل محرك. Docker على `127.0.0.1:55435` بقي دون تغيير عند الاستئناف؛ تم التحقق النهائي على PostgreSQL 18.6 المحمول المنفصل على `127.0.0.1:55436`. يختار `-Engine` المحرك صراحة. بيانات الاعتماد الجديدة مشفرة بـ DPAPI داخل `.local` ولا تذهب إلى ملفات المصدر.

API يدعم flags يملكها Backend:

- `dotnet Masar.Api.dll --migrate` يستخدم Migration connection وينفذ SQL migrations مرقمة ذات checksum وجلسة advisory lock؛ خروج0 بعد النجاح، لا webserver.
- `--import-bundle <absolute-path>` يستورد bundle بإصداره كـ draft أو لا يغير existing identical؛ flag `--publish-initial` مصرح به محليًا لعينة أولى فقط إذا لا يوجد منشور، بعد Validate وتسجيل audit. لا يستخدمه startup كل مرة.
- `--promote-admin <userName>` يستخدم Migration connection لمنح role=Admin لحساب محلي موجود وتسجيلaudit؛ ليس route عامًا.

لا migrations أو imports ضمن startup العادي. migration SQL embeddedresource في API csproj من ../../database/migrations/*.sql. يتم اختبار إعادة التشغيل وحفظ البيانات وتعارض الإصدارات وإعادة استخدام المهارات محليًا فعليًا.

## قبول وتسليم

كل جلسة تبني وتفحص ملفاتها وتوثق مصادرها ونتائجها وحدودها. المنسق يجري تكاملًا حقيقيًا على PostgreSQL (مستخدمان،401/403/CSRF/ملكيةموارد/idempotency/concurrency/versionpinning) وbuild frontend وفحص متصفح أساسي، ويحفظ الدليل. لا ادعاء readiness عام أو RLS أو تغطية أمنية كاملة. المرحلة3 لا تبدأ ضمن هذا التنفيذ.
