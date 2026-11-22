# Domain — المرحلة الثانية

## توقيعات الدمج

ثُبّتت التوقيعات كما في CONTRACT.md؛ namespace `Masar.Domain` وtarget `net10.0`، بلا dependencies خارجية للمكتبة:

```csharp
public static IReadOnlyList<string> CurriculumEngine.Validate(JsonObject bundle);
public static JsonObject CurriculumEngine.Plan(JsonObject bundle, string goalId,
    IEnumerable<string>? achievedSkillIds = null,
    IEnumerable<string>? preferredSkillIds = null);
public static JsonObject ExerciseEvaluator.Evaluate(JsonObject exercise, string answer, int hintsUsed);
```

`bundle` يضم `sample` و`graph`؛ تمرّر API التمرين من المحتوى المخزن الموثوق إلى Evaluate، ولا تمرر exercise أو acceptedAnswers من العميل. المخرجات `correct`, `assisted`, `explanation` فقط، دون استنتاج إتقان. Plan يعيد حقول العقد و`plannerVersion="2.0.0"`، ولا يغيّر input أو مجموعات المهارات.

اكتمل إصلاح `P2-02` ضمن نطاق Domain بتاريخ 2026-11-11. نجحت الاختبارات الـ110، بما فيها 51 حالة للتحقق من محتوى العرض.

## الملفات والمصادر

- `src/Masar.Domain/`: مكتبة .NET 10، SDK المستخدم فعليًا `10.0.403`؛ `TreatWarningsAsErrors=true`.
- `tests/Masar.Domain.Tests/`: xUnit `2.9.3`، Microsoft.NET.Test.Sdk `17.14.1`، xunit.runner.visualstudio `2.5.3`، مثبتة صراحةً في csproj.
- مرجع السلوك: `../phase1/lib/graph.mjs`، وبيانات `../phase1/content/sample.json` و`graph.json`. تمت قراءتها دون تعديلها.
- `tests/Masar.Domain.Tests/Fixtures/phase1-plans.json`: 25 حالة مرجعية مولدة فعليًا بواسطة JavaScript الأصلي، تشمل الأهداف الخمسة وخمس حالات للأدلة السابقة لكل هدف. يقارن الاختبار المخرج كاملًا بما فيه النص العربي للأسباب؛ الاستثناء الوحيد هو الحقل الإضافي المتفق عليه `plannerVersion`.
- مولّد المرجع `tests/Masar.Domain.Tests/generate-phase1-parity.mjs` لا يحتاج npm packages أو شبكة؛ Node المستخدم `v24.20.0`. Node ليس dependency للمكتبة أو لتشغيل الاختبارات بعد وجود fixture.

## التحقق والتخطيط

`Validate` يعيد قائمة فارغة للمحتوى الصحيح. الأخطاء تحمل مسارات للحقول، دون طرح exception بسبب الأشكال غير الصحيحة المعتادة أو النصوص ذات Unicode تالف. تتولى API تقديم رسالة عربية مناسبة؛ نصوص التحقق التفصيلية للمؤلف باللغة الإنجليزية.

يشترط schemaVersion=1 وتطابق releaseId، وتطابق مجموعتي معرفات الدروس ومهارات كل درس في sample وgraph. معرّف الإصدار الأولي `phase1-ar-v1` يتطلب ثلاثة دروس بالضبط؛ الإصدارات الأخرى تسمح بأعداد مختلفة، واختُبر درس واحد وأربعة دروس. معرفات المهارات والدروس والأهداف فريدة داخل كل جدول، ومعرفات التمارين فريدة في الإصدار كله؛ وهذا يناسب draft/progress المبنيين على releaseId وexerciseId.

### عقد حقول العرض (P2-02)

يتحقق `CurriculumEngine.Validate` من حقول العرض في كل إصدار. تستند متطلبات النص واللغات إلى فاحص العينة وحقول العرض التي تستهلكها الواجهة. القوائم أدناه مطلوبة وتحتوي على عنصر واحد على الأقل. حقول النص تقبل سلاسل فيها نص فعلي، ويحدد الخطأ مسار الحقل أو فهرس العنصر. [فاحص المرحلة الأولى](../../phase1/scripts/check.mjs) · [أنواع الواجهة](../apps/web/src/types.ts)

| الموضع | الحقول المطلوبة |
| --- | --- |
| `sample` | نصا `title` و`intro` وقائمتا `lessons` و`glossary` |
| كل درس في `sample.lessons` | نصوص `title` و`summary` و`why` و`minutes` و`takeaway`، وقوائم `objectives` و`sections` و`examples` بالإضافة إلى حقول المهارات والتمارين الموثقة هنا |
| `objectives[]` | نص لكل هدف |
| `sections[]` | كائن فيه `heading` و`body`. يقبل `language` عند وجوده `python` أو `javascript` أو `csharp` أو `cpp` أو `java` أو `go`. غياب الحقل يعني قسمًا مشتركًا بين اللغات |
| `examples[]` | كائن فيه `title` و`code` و`explanation` و`language`. يقبل `language` القيم `text` و`python` و`javascript` و`csharp` و`cpp` و`java` و`go` |
| `glossary[]` | كائن فيه `term` و`technical` و`definition` |

تُرفض القوائم المفقودة أو الفارغة، والقيم `null`، وعناصر الأنواع الخاطئة. يشمل ذلك `sections: null`، والهدف المخزن ككائن، و`language: null` في قسم. يستدعي مسار إنشاء الإصدار `Content.Validate` قبل التخزين ويحوّل أخطاء Domain إلى `400 invalid_content` بحسب قراءة الكود. جرى اختبار الرفض مباشرةً في Domain. [Content.cs](../src/Masar.Api/Content.cs#L26)

### المتطلبات والخطة

تتحقق تعبيرات `required` من مفتاح واحد فقط: `skill` أو `allOf` أو `anyOf`، مع السماح بالتداخل ورفض المجموعات الفارغة والمراجع المفقودة. `required=null` هو غياب المتطلبات؛ غياب الحقل نفسه خطأ. `recommended` قائمة اختيارية الأثر على الترتيب، لكن وجودها وصحة مراجعها مطلوبان. تُفحص DAG بطريقة Kahn التكرارية، مع احتساب جميع حواف OR تحفظيًا؛ لا تُقبل دورة لمجرد وجود فرع آخر يمكن اجتيازه.

`Plan` يحافظ على اختيار المرحلة الأولى الحتمي: يفضل فرع OR القابل للتحقق، ثم الأقل في المهارات غير المغطاة، ثم الأقل في عدد الدروس، ثم المهارات المفضلة، ثم ترتيب الفرع في المصدر. لا يفرض كل بدائل OR. يسجل `chosenAlternatives` اسم المهارة ومسار التعبير وفهرس الفرع والمهارات المختارة، ويشرح `step.reason` الغرض والمتطلبات والمهارات الجديدة. يمكن للدرس تقديم متطلبات داخلية قبل المهارات التابعة في الدرس نفسه، حتى لو اختلف ترتيب skillIds.

`missingSkillIds` هي مهارات الخطة غير الموجودة ضمن الأدلة الواردة عند بدء التخطيط؛ `uncoveredSkillIds` هي الجزء الذي لا يغطيه محتوى الخطة. `planned` تظل كذلك حتى مع وجود دروس أو أدلة لجميع المهارات؛ لا تتحول إلى حالة نشر. تبقى `sample` و`partial` و`unavailable` كما في المرجع. الهدف المجهول أو bundle غير صالح يعيدان مخرجًا كامل الحقول بحالة `unavailable` ومصفوفات فارغة.

المدخلات والـ JsonNodes لا تتغير. الأدلة المعاد استخدامها تُنسخ وتُرشّح إلى معرفات معروفة. مهارات الخطوات تمثل ما ستقدمه الخطة افتراضيًا، وليست أدلة تعلم محفوظة. على API تمرير مهارات مستخرجة من سجل الخادم؛ الدالة العامة لا تستطيع إثبات مصدر IEnumerable. لا تنقل الدالة أدلة بين إصدارات تلقائيًا.

## التقييم

تمارين `choice` تتطلب 2–32 خيارًا، بنصوص ومعرفات سليمة وفريدة بعد التطبيع، وacceptedAnswers تشير إلى معرفات خيارات موجودة. تمارين `text` تتطلب options فارغة. كلاهما يتطلب إجابات مقبولة غير فارغة، دون تكرار بعد التطبيع، وprompt وexplanation وhints صحيحة. `independent` إذا وجد يجب أن يكون boolean، لكنه لا يرفع قوة الدليل.

`Evaluate` يتحقق من محتوى التمرين قبل المقارنة. يطبّق NFKC وtrim على الإجابة المتوقعة والواردة، ويحوّل مجموعتي الأرقام العربية `٠..٩` والفارسية `۰..۹` إلى `0..9`. لا يزيل التشكيل أو علامات الترقيم، ولا يغير حالة الحروف أو المسافات الداخلية. في choice يقارن معرف الخيار، لا النص المعروض.

الإجابة الفارغة أو الأطول من 4096 أو Unicode التالف أو hintsUsed السالب لا تُقبل. `assisted` يساوي `hintsUsed > 0`؛ لا يُستنتج إتقان أو `demonstrated` من النجاح حتى دون تلميح. الحقل الإضافي `correct` داخل exercise لا يؤثر على النتيجة المحسوبة. لا eval أو تشغيل للشيفرة أو تحليلها كبرنامج. التفسير يعود من المحتوى الموثوق، وفي المدخل غير الصالح يعود تفسير عام آمن. نزاهة hintsUsed الفعلية تحتاج سياسة API/واجهة؛ Domain لا يدعي اكتشاف تلميح أخفاه المستخدم.

## الحدود الصريحة

| الحد | القيمة |
| --- | ---: |
| عمق JsonNode قبل أي معالجة متداخلة | 64 |
| عدد عقد JSON، شاملة null | 50,000 |
| مجموع محارف النصوص وأسماء الخصائص | 2,000,000 |
| عدد المهارات أو الدروس لكل جدول | 512 |
| عدد الأهداف | 128 |
| عدد مراجع المهارات أو أبناء مجموعة تعبير | 512 |
| عمق تعبير required ابتداءً من الصفر | 24 |
| طول أطول مسار اعتماد بين المهارات | 64 حافة |
| التمارين لكل درس / لكل bundle | 128 / 4096 |
| طول المعرف / العنوان | 128 / 500 |
| طول prompt أو hint أو إجابة واحدة | 4000 / 4000 / 4096 |
| طول explanation / عدد hints | 8000 / 16 |
| عدد acceptedAnswers | 32 |
| عمليات التخطيط المحتسبة / عمق استدعاءات التخطيط | 100,000 / 256 |
| عناصر كل IEnumerable للمهارات الواردة | 512 عنصرًا قبل التصفية |

الفحص البنيوي تكراري قبل الاجتياز المتداخل. تُرفض النصوص وأسماء الخصائص ذات Unicode تالف أيضًا. يُحد تعداد IEnumerable حتى لو كان غير منتهٍ. إذا استنفد تخطيط شديد التعقيد ميزانية العمل أو عمق الاستدعاء يعيد `unavailable` كامل الحقول؛ لا يصدر خطة ناقصة مضللة. الحدود مستقلة عن ميزانيات HTTP وحجم request التي تتولاها API.

المخطط greedy محلي مثل المرحلة الأولى، وليس محسنًا عالميًا. عند وجود أكثر من درس لنفس المهارة يختار الأول حسب ترتيب المصدر. التحقق بنيوي ومرجعي، وليس مراجعة علمية لجودة المنهج أو حاجزًا لتعقيم HTML؛ عرض النص الآمن ومراجعة النشر مسؤوليتان منفصلتان.

## أوامر التحقق الفعلية

من `F:\تعلم برمجه` في PowerShell:

```powershell
$env:DOTNET_CLI_HOME = Join-Path $PWD 'phase2/.local/dotnet'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'

dotnet build phase2/src/Masar.Domain/Masar.Domain.csproj --configfile phase2/NuGet.Config --nologo
dotnet restore phase2/tests/Masar.Domain.Tests/Masar.Domain.Tests.csproj --configfile phase2/NuGet.Config --source 'C:\Users\BONDOK\.nuget\packages' -p:NuGetAudit=false --nologo
node phase2/tests/Masar.Domain.Tests/generate-phase1-parity.mjs
node phase1/scripts/check.mjs
dotnet test phase2/tests/Masar.Domain.Tests/Masar.Domain.Tests.csproj --no-restore --nologo --logger 'trx;LogFileName=domain-p2-02.trx'
```

شُغلت فئة `ContentDisplayValidationTests` قبل الإصلاح باستخدام `--filter 'FullyQualifiedName~ContentDisplayValidationTests'`. فشلت 47 من 51 حالة بسبب قبول المدخلات المعيبة. بعد الإصلاح نجحت المجموعة الكاملة بنتيجة `Passed: 110, Failed: 0, Skipped: 0`، وظلت الخطط الـ25 مطابقة لمرجع المرحلة الأولى. اجتاز `phase1-ar-v1` أيضًا فاحص المرحلة الأولى الأصلي (3 دروس و9 تمارين و11 مصطلحًا). دليل التشغيل [domain-p2-02.trx](../tests/Masar.Domain.Tests/TestResults/domain-p2-02.trx).

ملاحظات إعادة التنفيذ: محاولة تمرير `--configfile` مباشرة إلى `dotnet test` فشلت بـMSB1001؛ استُبدلت بمرحلة restore مستقلة ثم `--no-restore`. restore الافتراضي وجد الحزم لكنه فشل بـNU1900 عند استعلام بيانات ثغرات NuGet عبر شبكة غير متاحة. نجح restore من cache المحلي للقراءة مع `NuGetAudit=false` في الأمر فقط؛ لم يُعطل التدقيق في csproj أو config، ولم يُجر فحص ثغرات online. الحزم المهيأة للتشغيل تحت `.local/nuget` وفق NuGet.Config المنسق.

تشمل الاختبارات العينة، الأهداف المخططة وتغير الهدف، إعادة استخدام المهارات وعدم mutation، nested AND/OR ومسارات الاختيارات وحسم التعادل والكلفة والتفضيل، تقديم المهارات داخل درس واحد، partial/unavailable، تكرار المعرفات ومطابقة المراجع، دورات OR المحافظة، المجموعات الفارغة، حدود JSON/المحتوى/التعبير/DAG والتعداد غير المنتهي، وتمارين malformed وتطبيع الإجابات وعدم قبول correct المرسل.

لم تتغير ملفات Phase1 أو Api أو frontend أو database أو scripts أو ملفات الجذر. لم تُنشأ جلسات أو مستودعات Git أو مفاتيح. لا تشمل هذه النتيجة تشغيل API أو PostgreSQL أو فحص الواجهة أو إثبات جاهزية إطلاق؛ تبقى اختبارات تكاملها ضمن نطاق المنسق.
