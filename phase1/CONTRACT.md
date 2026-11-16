# عقد التعاون — المرحلة الأولى

هذه المرحلة هي «اختبار الفكرة والعينة»، وتسميتها للمستخدم المرحلة 1؛ وهي الصف المرقم 0 في مسودة PRODUCT_PLAN القديمة. يوحّد المنسق الترقيم إلى 1–7.

## نطاق المرحلة

عينة عربية تفاعلية محلية من 3 دروس، وتمارين قابلة للتحقق، وخريطة مهارات تشرح الترتيب، وتعريف المتعلم والهدف، وخطة اختبار مع مبتدئ. لا حسابات أو Backend أو اعتماد مهني أو تشغيل حر لكود المستخدم ضمن هذه المرحلة. لا نشر أو استخدام خدمات مدفوعة أو مفاتيح API.

الواجهة المحلية تستخدم HTML/CSS وJavaScript modules دون اعتماديات بناء لتسهيل مراجعة العينة؛ هذا نموذج تجربة أولي، ولا يغير اختيار React/TypeScript وASP.NET Core للمنتج اللاحق. أمثلة Python وJavaScript نصوص للقراءة والتتبع؛ إجابات التمارين تُصحح بقواعد محدودة دون eval أو Function أو تنفيذ كود متعلم.

## توزيع الملكية

- الجلسة الأساسية: `phase1/web/`، `phase1/package.json`، `phase1/scripts/serve.mjs`، دمج واختبار وتسليم وتحديث حالة المشروع.
- جلسة المحتوى: `phase1/content/sample.json`، `phase1/docs/CONTENT_REVIEW.md` فقط.
- جلسة الخريطة: `phase1/content/graph.json`، `phase1/lib/graph.mjs`، `phase1/tests/graph.test.mjs`، `phase1/docs/GRAPH_NOTES.md` فقط.
- جلسة قبول العينة: `phase1/docs/LEARNER_PROFILE.md`، `phase1/docs/PILOT_PROTOCOL.md`، `phase1/docs/ACCEPTANCE_MATRIX.md`، `phase1/docs/PHASE2_BACKLOG.md` فقط. لا تُعلن نتائج تجربة بشرية لم تحدث.

كل الملفات داخل F:\تعلم برمجه. لا تعديل ملفات جلسة أخرى، ولا Git أو تثبيت أو حذف ملفات قائمة. لا حاجة لإرسال رسائل إلى أشخاص أو chats أخرى؛ يعتمد المنسق على ملفاتكم وحالة جلساتكم. إذا لزم سؤال اكتبه في ملف الملاحظات وواصل المستقل منه.

## عقد محتوى sample.json

UTF-8 وJSON صحيح، الجذر:

```json
{
  "schemaVersion": 1,
  "releaseId": "phase1-ar-v1",
  "title": "خطوتك الأولى في البرمجة",
  "intro": "شرح عربي قصير",
  "lessons": [],
  "glossary": []
}
```

توجد 3 دروس بالمعرّفات الثابتة بالترتيب:

1. `what-is-a-program` مرتبط بـ `concept.program` و`concept.input-output`.
2. `step-by-step` مرتبط بـ `concept.sequence`.
3. `first-variable` مرتبط بـ `concept.variable`.

كل درس: `id,title,summary,why,objectives` (مصفوفة نصوص)، `minutes` (تقدير تجريبي مثل "8–12")، `skillIds`، `sections` (3 أو أكثر: `{heading,body}`؛ body نص عادي، بلا HTML أو Markdown؛ أضيف عند الدمج حقل `language` اختياري بقيمة python أو javascript لترشيح شرح الصياغة بحسب التفضيل)، `examples` (واحد أو أكثر: `{title,language,code,explanation}`؛ language هو `text` أو `python` أو `javascript`)، `exercises` (3 لكل درس)، `takeaway` (نص).

كل تمرين: `id,prompt,type,options,acceptedAnswers,explanation,hints,independent`، و`code` اختياري نص، و`language` اختياري. `type` إما `choice` أو `text`. كل option هو `{id,text}`. `acceptedAnswers` قائمة ids للاختيار أو قائمة نصوص/أرقام للإجابة القصيرة. التصحيح يطبع العربية والمسافات الخارجية والأرقام العربية فقط دون تنفيذ كود؛ إجابة فارغة لا تُقبل. كل تمرين يوضح مفهومًا دُرس بالفعل. يوجد تمرين independent=true واحد على الأقل لكل درس، والتلميح الأخير لا يكشف جوابه مباشرة. المثال المحلول والتدريب ثم مهمة جديدة مستقلة. Glossary: عناصر `{term,technical,definition}`.

مثال Python وJavaScript يشرحان نفس فكرة المتغير للمبتدئ دون اشتراط لغة للجميع. الاختيار في العينة يحدد تفضيل أمثلة فقط؛ لا يدّعي نشر مسار مهني كامل. لا markup تنفيذي، كل النصوص تعرض بـ textContent.

## عقد graph.json وgraph.mjs

الجذر `schemaVersion,releaseId,skills,lessons,goals`. skill: `{id,title,description,required,recommended}`. required إما null أو تعبير `{skill:"id"}` أو `{allOf:[...]}` أو `{anyOf:[...]}`؛ recommended قائمة معرفات.

lessons: `{id,title,skillIds,why}` متطابقة مع معرّفات sample. goals: `{id,title,description,status,skillIds}`. الأهداف: `explore` و`python` و`web` متاحة كعينة (`status:"sample"`) وتحتاج مهارات العينة كلها، و`react` و`ai` بحالة `planned` لا يدّعي إكمالها. المهارات الإضافية المخططة يمكن وجودها في graph للتوضيح، دون درس أو اعتماد. أمثلة planned لا تُقحم متطلب Python في React.

Exports:

```js
export function validateGraph(graph) {} // returns {valid:boolean,errors:string[]}
export function buildPlan(graph, {goalId, achievedSkillIds = [], preferredSkillIds = []} = {}) {}
// returns {goalId,status,steps,missingSkillIds,uncoveredSkillIds,chosenAlternatives}
// steps: [{lessonId,skillIds,reason}]، status: sample|partial|planned|unavailable
export function getReadyLessons(graph, achievedSkillIds = []) {} // returns lesson id strings
```

لا تدّعي الخوارزمية أنها احتساب إتقان إنتاجي؛ achievedSkillIds مدخل تجريبي أو سجل تدريب محلي. نختبر AND/OR والتداخل، والروابط الناقصة والدورات والمجموعات الفارغة، وعدم فرض جميع البدائل، وgoal غير متاح. يُستخدم Node test runner بلا مكتبات خارجية. خطة الهدف planned تعرض فجواته بوضوح حتى لو أمكن دراسة جزء العينة.

## معيار صدق الحالة

المحتوى: draft ثم peer-reviewed تقنيًا؛ فحص بشري مع مبتدئ pending حتى يحدث فعلًا. نتائج الآلة لا تعني نجاح التجربة البشرية. حالات التطبيق تشير إلى «تقدم العينة على هذا الجهاز»، ولا تستعمل لغة شهادة أو احتراف مثبت. كل جلسة تسجل ما أنجزته وفحوصها وحدود التحقق داخل ملفاتها قبل إنهاء المهمة.
