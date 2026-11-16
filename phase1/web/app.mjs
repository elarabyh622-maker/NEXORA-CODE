import { buildPlan, validateGraph } from '/lib/graph.mjs';
import { STORAGE_KEY, sanitizeState, recordAnswer, lessonProgress, completedSkills, persistState } from './state.mjs';

const root = document.getElementById('app');
document.querySelector('.skip-link').addEventListener('click', event => {
  event.preventDefault(); document.getElementById('main')?.focus();
});
const ns = 'http://www.w3.org/2000/svg';
let sample, graph, state, storageAvailable = true;
const paths = {
  route: 'M4 18h4V6h8v12h4M5 18a1 1 0 1 0 0 .1M19 18a1 1 0 1 0 0 .1',
  home: 'm3 11 9-8 9 8M5 10v10h5v-6h4v6h5V10',
  book: 'M12 6c-3-2-6-2-10-1v14c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1v14',
  chart: 'M4 3v17h17M8 16v-5M13 16V7M18 16v-9',
  code: 'm8 6-6 6 6 6m8-12 6 6-6 6m-3-14-2 16',
  arrow: 'M20 12H4m6-6-6 6 6 6',
  check: 'm5 12 4 4L19 6',
  clock: 'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  leaf: 'M5 20c1-7 4-9 12-14M4 17C0 6 12 2 22 3c0 9-3 17-14 15',
  globe: 'M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0M2 12h20M12 2c-6 6-6 14 0 20 6-6 6-14 0-20',
  spark: 'm12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6',
  person: 'M8 7a4 4 0 1 0 8 0 4 4 0 0 0-8 0M4 21v-3a8 8 0 0 1 16 0v3',
  download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  info: 'M12 11v6m0-10v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'
};
function icon(name) {
  const svg = document.createElementNS(ns, 'svg');
  for (const [key, value] of Object.entries({ viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':'1.7', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true' })) svg.setAttribute(key, value);
  const p = document.createElementNS(ns, 'path'); p.setAttribute('d', paths[name] ?? paths.book); svg.append(p); return svg;
}
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'class') node.className = value;
    else if (['value','checked','selected','disabled','hidden'].includes(key)) node[key] = value;
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
function btn(text, href, type = 'primary', symbol = 'arrow') {
  return el('a', { class:`btn ${type}`, href }, text, icon(symbol));
}
const live = el('div', { class:'sr-only', role:'status', 'aria-live':'polite', 'aria-atomic':'true' });
document.body.append(live);
function announce(message) { live.textContent = ''; requestAnimationFrame(() => { live.textContent = message; }); }
function save() {
  try { storageAvailable = persistState(localStorage, state); }
  catch { storageAvailable = false; }
  const warning = document.getElementById('storage-warning');
  if (warning) warning.hidden = storageAvailable;
  const status = document.getElementById('storage-status');
  if (status) status.textContent = storageAvailable ? 'التقدم محفوظ على هذا الجهاز · دون حساب' : 'الحفظ غير متاح الآن · صدّر تقدمك قبل الإغلاق';
  return storageAvailable;
}
function currentLesson() { return sample.lessons.find(lesson => lesson.id === state.lastLessonId) ?? sample.lessons[0]; }
function preferredLanguage() { return state.language; }
function plan() { return buildPlan(graph, { goalId:state.goalId, achievedSkillIds:completedSkills(sample, state) }); }
function totalSolved() { return sample.lessons.reduce((sum, lesson) => sum + lessonProgress(lesson, state).solved, 0); }
function isDone() { return sample.lessons.every(lesson => lessonProgress(lesson, state).complete); }
function linkLesson(lessonId) { return `#lesson/${lessonId}`; }
function chosenGoal() { return graph.goals.find(goal => goal.id === state.goalId) ?? graph.goals[0]; }

function shell(view, route) {
  const navigation = [ ['start','نقطة البداية','home'], ['plan','خطتي التعليمية','route'], ['progress','تقدمي في العينة','chart'], ['glossary','قاموس المصطلحات','book'] ];
  const sidebar = el('aside', { class:'sidebar' },
    el('a', { class:'brand', href:'#start', 'aria-label':'مسار — نقطة البداية' },
      el('span', { class:'brand-mark' }, icon('route')),
      el('span', {}, el('strong', {}, 'مسار'), el('small', {}, 'التعلّم يبدأ بفهم الطريق'))),
    el('nav', { class:'nav', 'aria-label':'التنقل الرئيسي' }, navigation.map(([id, title, symbol]) =>
      el('a', { href:`#${id}`, class:route === id || (route === 'lesson' && id === 'plan') ? 'active' : '', 'aria-current':route === id ? 'page' : null }, icon(symbol), title))),
    el('div', { class:'sidebar-note' }, icon('leaf'), el('strong', {}, 'خطوة صغيرة، فهم حقيقي'), el('p', {}, 'لا تحتاج أي خبرة سابقة. اقرأ، جرّب التفكير، وتقدّم على مهل.')),
    el('div', { class:'sidebar-foot' }, 'عينة استكشافية · 3 دروس'));
  const bar = el('header', { class:'topbar' },
    el('div', { class:'topbar-title' }, icon('book'), el('span', {}, 'رحلتك الأولى في البرمجة')),
    el('div', { class:'topbar-actions' }, el('span', { class:'pill sample' }, 'عينة تعليمية'), el('span', { class:'small muted' }, 'أهلًا بك'), el('span', { class:'avatar' }, icon('person'))));
  const main = el('main', { id:'main', class:'main', tabindex:'-1' }, view,
    el('footer', { class:'footer' }, el('span', {}, 'مسار · تعلّم بالعربية، خطوة بخطوة'), el('span', {id:'storage-status'}, storageAvailable ? 'التقدم محفوظ على هذا الجهاز · دون حساب' : 'الحفظ غير متاح الآن · صدّر تقدمك قبل الإغلاق')));
  return el('div', { class:'shell' }, sidebar, el('div', { class:'workspace' }, bar,
    el('p', { id:'storage-warning', class:'storage-warning', role:'status', hidden:storageAvailable }, 'الحفظ على هذا الجهاز غير متاح الآن. يمكنك متابعة العينة وتصدير تقدمك قبل إغلاق الصفحة.'),
    main));
}

function renderStart() {
  const code = preferredLanguage() === 'javascript' ? 'let name = "سارة";\nconsole.log(name);' : 'name = "سارة"\nprint(name)';
  const hero = el('section', { class:'hero' },
    el('div', { class:'hero-copy' }, el('p', { class:'eyebrow' }, 'من الصفر، وباللغة العربية'),
      el('h1', {}, 'رحلتك تبدأ بخطوة واضحة.'),
      el('p', {}, 'اختر ما تريد تعلّمه، وسنوضح لك ما تحتاجه قبله. ابدأ بثلاثة دروس بسيطة، وتدرّب قبل أن تنتقل إلى الخطوة التالية.'),
      btn(totalSolved() ? 'واصل من حيث توقفت' : 'ابدأ خطوتك الأولى', totalSolved() ? linkLesson(currentLesson().id) : '#plan', 'primary'),
      el('div', { class:'hero-meta' }, el('span', {}, icon('check'), 'لا خبرة مطلوبة'), el('span', {}, icon('book'), 'شرح وتمارين بالعربية'), el('span', {}, icon('clock'), 'تعلّم على مهل'))),
    el('div', { class:'hero-art', 'aria-label':'مثال: احفظ اسمًا ثم اعرضه' },
      el('div', { class:'code-window' },
        el('div', { class:'code-toolbar' }, el('span', {}, preferredLanguage() === 'javascript' ? 'JavaScript' : 'Python'), el('span', { class:'window-dots' }, el('i'), el('i'), el('i'))),
        el('pre', { dir:'ltr' }, el('code', {}, code)),
        el('div', { class:'code-output' }, el('span', {}, 'الناتج المتوقع'), 'سارة'))));
  const titles = { explore:'لست متأكدًا بعد', python:'أريد تعلّم Python', web:'أريد بناء مواقع', react:'أريد تعلّم React', ai:'أريد تعلّم الذكاء الاصطناعي' };
  const descriptions = { explore:'ابدأ بالمفاهيم المشتركة، ثم اكتشف ما تحب بناءه.', python:'تعرّف إلى الأساسيات بأمثلة Python، قبل مسار الأتمتة.', web:'ابدأ بالمفاهيم المشتركة بأمثلة JavaScript، قبل بناء الواجهات.', react:'تعرّف إلى ما يسبق React. منهجه الكامل ضمن التوسع.', ai:'تعرّف إلى البداية المشتركة. منهج التخصص ضمن التوسع.' };
  function goalCard(goal) {
    const future = goal.status === 'planned';
    return el('button', { type:'button', class:`goal${future ? ' future' : ''}`, 'data-goal':goal.id, 'aria-pressed':goal.id === state.goalId,
      onClick:() => { state.goalId = goal.id; if (goal.id === 'web' || goal.id === 'react') state.language = 'javascript'; else if (goal.id === 'python') state.language = 'python'; save(); render(false); document.querySelector(`[data-goal="${goal.id}"]`)?.focus({preventScroll:true}); announce(`اخترت: ${titles[goal.id] ?? goal.title}`); } },
      el('span', { class:'goal-top' }, el('span', { class:'goal-icon' }, icon(goal.id === 'web' ? 'globe' : goal.id === 'explore' ? 'route' : goal.id === 'ai' ? 'spark' : 'code')), el('span', { class:'pill' }, future ? 'خريطة مستقبلية' : 'ابدأ بعينة الأساسيات')),
      el('h3', {}, titles[goal.id] ?? goal.title), el('p', {}, descriptions[goal.id] ?? goal.description));
  }
  const available = graph.goals.filter(goal => goal.status !== 'planned');
  const future = graph.goals.filter(goal => goal.status === 'planned');
  return el('div', {}, hero,
    el('section', { 'aria-labelledby':'choose-title' },
      el('div', { class:'section-title' }, el('div', {}, el('h2', { id:'choose-title' }, 'ما الذي تريد أن تبدأ به؟'), el('p', {}, 'اختيارك قابل للتغيير. لن تحتاج إلى تعلّم كل اللغات.'))),
      el('div', { class:'goals' }, available.map(goalCard)),
      el('div', { class:'future-goals' }, future.map(goalCard)),
      el('div', { class:'onboarding-options' }, languageField(), btn('اعرض خطتي', '#plan', 'primary')),
      el('p', { class:'aside-tip' }, 'في هذه العينة ستتعلّم ما البرنامج، وكيف نرتب خطوات الحل، وما المتغير. اختيار التخصص يوضح اتجاهك؛ منهجه الكامل يأتي لاحقًا.')));
}

function languageField() {
  return el('div', { class:'language-field' }, el('label', { for:'example-language' }, 'لغة أمثلة الكود:'),
    el('select', { id:'example-language', 'aria-label':'لغة أمثلة الكود', onChange:event => {
      state.language = event.target.value;
      save(); render(false); document.getElementById('example-language')?.focus({preventScroll:true});
    } }, el('option', { value:'python', selected:preferredLanguage() === 'python' }, 'Python'), el('option', { value:'javascript', selected:preferredLanguage() === 'javascript' }, 'JavaScript')));
}

function heading(title, description, action) {
  return el('div', { class:'page-heading' }, el('div', {}, el('h1', {}, title), el('p', {}, description)), action ?? null);
}
function renderPlan() {
  const result = plan();
  const next = result.steps[0]?.lessonId ?? sample.lessons[0].id;
  const planned = chosenGoal().status === 'planned';
  const steps = sample.lessons.map((lesson, index) => {
    const progress = lessonProgress(lesson, state);
    const plannedStep = result.steps.find(step => step.lessonId === lesson.id);
    return el('article', { class:`plan-step${progress.complete ? ' complete' : ''}` },
      el('div', { class:'step-number' }, progress.complete ? icon('check') : String(index + 1)),
      el('div', {}, el('div', { class:'step-head' }, el('h3', {}, lesson.title), el('p', {}, `${lesson.minutes} دقيقة تقريبًا`)),
        el('p', { class:'summary' }, lesson.summary),
        el('div', { class:'mini-progress' }, el('progress', { max:progress.total, value:progress.solved, 'aria-label':`تمارين ${lesson.title}: ${progress.solved} من ${progress.total}` }), el('span', {}, `${progress.solved} / ${progress.total} تمارين`)),
        btn(progress.complete ? 'راجع الدرس' : 'افتح الدرس', linkLesson(lesson.id), progress.complete ? 'compact' : 'primary compact'),
        el('details', {}, el('summary', {}, 'لماذا أحتاج هذه الخطوة؟'), el('p', {}, lesson.why), plannedStep?.reason ? el('p', {}, plannedStep.reason) : null)));
  });
  const uncovered = (result.uncoveredSkillIds ?? []).map(id => graph.skills.find(skill => skill.id === id)?.title ?? id);
  return el('div', {}, heading('طريقك يبدأ من هنا', 'ثلاث خطوات مترابطة. يمكنك استكشاف أي درس، والخطة توضح الترتيب المقترح.', btn('غيّر هدفي', '#start', '', 'route')),
    el('section', { class:'plan-intro' }, el('div', {}, el('strong', {}, chosenGoal().title), el('p', {}, planned ? 'يمكنك دراسة الأساسيات الآن. المحتوى المتخصص لهذا الهدف لم يُنشر بعد.' : 'هذه عينة الأساسيات المشتركة، وليست مسار تخصص كاملًا.')), btn(isDone() ? 'شاهد تقدمك' : 'ابدأ الخطوة التالية', isDone() ? '#progress' : linkLesson(next), 'primary')),
    planned || uncovered.length ? el('div', { class:'notice' }, 'خطة جزئية: ', uncovered.length ? `مهارات مثل ${uncovered.slice(0, 4).join('، ')} لا تتوفر لها دروس في هذه العينة.` : 'منهج هذا التخصص ضمن التوسع. لا يمثل إكمال العينة إنهاء التخصص.') : null,
    el('div', { class:'split' }, el('section', { class:'plan-list', 'aria-label':'ترتيب الدروس' }, el('h2', {class:'sr-only'}, 'دروس العينة'), steps),
      el('aside', { class:'panel side-summary' }, el('h3', {}, 'ماذا ستحقق في العينة؟'), el('ul', {}, el('li', {}, 'تشرح معنى البرنامج والمدخلات والمخرجات.'), el('li', {}, 'ترتب خطوات حل مشكلة بسيطة.'), el('li', {}, 'تقرأ قيمة متغير وتحدد الناتج.')),
        el('p', {}, 'تقدمك هنا سجل تدريب محلي. تعلّم لغة كاملة يحتاج دروسًا ومشروعات وتقييمات أخرى.'), btn('قاموسك الصغير', '#glossary', '', 'book'))));
}

function exampleView(example) {
  return el('figure', { class:'example' }, el('figcaption', { class:'example-head' }, el('strong', {}, example.title), el('bdi', { dir:'ltr', class:'small muted' }, example.language === 'text' ? 'مثال توضيحي' : example.language === 'python' ? 'Python' : 'JavaScript')),
    el('pre', { dir:example.language === 'text' ? 'auto' : 'ltr' }, el('code', {}, example.code)), el('p', { class:'explanation' }, example.explanation));
}
function exerciseView(lesson, exercise, index) {
  const record = state.answers[exercise.id];
  const hintLevel = state.hintLevels[exercise.id] ?? 0;
  const draft = state.drafts[exercise.id] ?? record?.value ?? '';
  const id = `answer-${exercise.id}`;
  const inputs = exercise.type === 'choice'
    ? el('fieldset', {}, el('legend', { class:'sr-only' }, exercise.prompt), el('div', { class:'choice-options' }, exercise.options.map(option =>
      el('label', { class:'choice' }, el('input', { type:'radio', name:id, value:option.id, checked:draft === option.id,
        onChange:event => { state.drafts[exercise.id] = event.target.value; save(); } }), el('span', {}, option.text)))))
    : el('div', {}, el('label', { class:'field-label', for:id }, 'اكتب إجابتك'),
      el('input', { class:'text-answer', id, name:id, type:'text', value:draft, maxlength:'2000', autocomplete:'off', dir:'auto',
        onInput:event => { state.drafts[exercise.id] = event.target.value; save(); } }));
  const feedback = record ? el('div', { class:`feedback ${record.correct ? 'success' : 'error'}` },
    el('strong', {}, record.correct ? 'إجابة صحيحة.' : 'جرّب مرة أخرى.'),
    el('p', {}, record.correct ? exercise.explanation : 'ارجع إلى المثال وابحث عن الفكرة المطلوبة. يمكنك طلب تلميح.'),
    record.correct && record.assisted ? el('p', { class:'small' }, 'تدريب بمساعدة؛ ستحتاج مهمة جديدة مستقلة للتحقق من الفهم لاحقًا.') : null) : null;
  const form = el('form', { class:'exercise', 'data-exercise':exercise.id, onSubmit:event => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = data.get(id) ?? '';
    if (!String(value).trim()) { announce('اختر إجابة أو اكتبها أولًا.'); event.currentTarget.querySelector('input')?.focus(); return; }
    state = recordAnswer(state, lesson, exercise, value); save(); render(false);
    document.querySelector(`[data-check="${exercise.id}"]`)?.focus({preventScroll:true});
    announce(state.answers[exercise.id].correct ? (storageAvailable ? 'إجابة صحيحة. تم حفظ تقدم التدريب على هذا الجهاز.' : 'إجابة صحيحة. الحفظ على الجهاز غير متاح؛ يمكنك تصدير تقدمك.') : 'الإجابة تحتاج مراجعة. جرّب مرة أخرى أو اطلب تلميحًا.');
  } },
    el('p', { class:'exercise-tag' }, `تمرين ${index + 1}`, exercise.independent ? el('span', { class:'pill' }, 'طبّق في موقف جديد') : null),
    el('h3', {}, exercise.prompt),
    exercise.code ? el('div', { class:'example' }, el('pre', { dir:exercise.language === 'text' ? 'auto' : 'ltr' }, el('code', {}, exercise.code))) : null,
    inputs, el('div', { class:'exercise-actions' }, el('button', { type:'submit', class:'btn primary compact', 'data-check':exercise.id }, 'تحقق من إجابتي', icon('check')),
      hintLevel < exercise.hints.length ? el('button', { type:'button', class:'btn text compact', 'data-hint':exercise.id, onClick:() => {
        state.hintLevels[exercise.id] = hintLevel + 1;
        if (state.answers[exercise.id]) state.answers[exercise.id].assisted = true;
        save(); render(false); document.querySelector(`[data-hint="${exercise.id}"]`)?.focus({preventScroll:true}); announce(exercise.hints[hintLevel]);
      } }, hintLevel ? 'تلميح آخر' : 'أحتاج تلميحًا') : el('span', { class:'small muted' }, 'ظهرت كل التلميحات')),
    hintLevel ? el('div', { class:'hint' }, exercise.hints.slice(0, hintLevel).map((hint, i) => el('p', {}, `${i + 1}. ${hint}`))) : null,
    feedback);
  return form;
}

function renderLesson(lessonId) {
  const lesson = sample.lessons.find(item => item.id === lessonId);
  if (!lesson) return el('div', {}, heading('هذا الدرس غير موجود', 'اختر درسًا من الخطة للمتابعة.'), btn('ارجع إلى خطتي', '#plan'));
  state.lastLessonId = lesson.id; save();
  const index = sample.lessons.indexOf(lesson);
  const unmet = sample.lessons.slice(0, index).filter(item => !lessonProgress(item, state).complete);
  const progress = lessonProgress(lesson, state);
  const examples = lesson.examples.filter(example => example.language === 'text' || example.language === preferredLanguage());
  const nextLesson = sample.lessons[index + 1];
  return el('div', {},
    el('nav', { class:'breadcrumbs', 'aria-label':'مسار الصفحة' }, el('a', { href:'#start' }, 'البداية'), el('span', {}, '/'), el('a', { href:'#plan' }, 'خطتي'), el('span', {}, '/'), el('span', { 'aria-current':'page' }, lesson.title)),
    heading(lesson.title, lesson.summary, el('span', { class:'pill' }, icon('clock'), `${lesson.minutes} دقيقة تقريبًا`)),
    unmet.length ? el('p', { class:'notice' }, `تستفيد أكثر إذا بدأت بـ «${unmet[0].title}». يمكنك الاستكشاف الآن، والخطة تبقي الخطوات السابقة واضحة.`) : null,
    el('div', { class:'lesson-layout' },
      el('article', { class:'panel lesson-body' },
        el('div', { class:'objectives' }, el('h2', {}, 'بعد هذا الدرس ستستطيع:'), el('ul', {}, lesson.objectives.map(objective => el('li', {}, objective)))),
        lesson.examples.some(example=>example.language!=='text') ? el('div', {class:'lesson-language'}, languageField()) : null,
        lesson.sections.filter(section=>!section.language || section.language===preferredLanguage()).map(section => el('section', { class:'lesson-section' }, el('h2', {}, section.heading), el('p', {}, section.body))),
        examples.map(exampleView),
        el('div', { class:'aside-tip' }, lesson.takeaway),
        el('section', { class:'exercise-list', 'aria-label':'تمارين الدرس' }, el('h2', {}, 'حان دورك'), el('p', { class:'muted small' }, 'هذه تمارين فهم وتتبع. اقرأ المثال ثم تحقق من إجابتك.'), lesson.exercises.map((exercise, i) => exerciseView(lesson, exercise, i))),
        el('div', { class:'lesson-finish' }, el('div', {}, el('strong', {}, progress.complete ? 'أنهيت تمارين هذا الدرس.' : `${progress.solved} من ${progress.total} تمارين مكتملة`), el('p', {}, progress.complete ? 'خذ لحظة واشرح الفكرة بكلماتك قبل المتابعة.' : 'يمكنك الاستكشاف والمتابعة، والعودة لإكمال التدريب.')),
          btn(nextLesson ? 'الدرس التالي' : 'شاهد تقدمي', nextLesson ? linkLesson(nextLesson.id) : '#progress', progress.complete ? 'primary' : ''))),
      el('aside', { class:'panel lesson-nav' }, el('h3', {}, 'خطواتك الثلاث'), el('nav', { 'aria-label':'دروس العينة' }, sample.lessons.map((item, i) => el('a', { href:linkLesson(item.id), class:item.id === lesson.id ? 'current' : '', 'aria-current':item.id === lesson.id ? 'page' : null }, el('span', { class:'number' }, lessonProgress(item, state).complete ? icon('check') : i + 1), item.title))), el('p', { class:'small muted' }, 'كل خطوة تمهّد لما بعدها. تقدّم على مهل.'))));
}

function downloadProgress() {
  const data = { product:'Masar', scope:'local-phase1-practice', exportedAt:new Date().toISOString(), state };
  const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob); const a = el('a', { href:url, download:'masar-sample-progress.json' });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  announce('تم تجهيز ملف تقدم العينة.');
}
function renderProgress() {
  const solved = totalSolved();
  const total = sample.lessons.flatMap(lesson => lesson.exercises).length;
  const completed = sample.lessons.filter(lesson => lessonProgress(lesson, state).complete).length;
  const skills = new Set(completedSkills(sample, state));
  const rows = graph.skills.filter(skill => sample.lessons.some(lesson => lesson.skillIds.includes(skill.id))).map(skill =>
    el('div', { class:'skill-row' }, el('div', {}, el('h3', {}, skill.title), el('p', {}, skill.description)), el('span', { class:`pill${skills.has(skill.id) ? ' sample' : ''}` }, skills.has(skill.id) ? 'تدرّبت عليها في العينة' : 'تحتاج إلى تدريب')));
  return el('div', {}, heading('كل خطوة لها أثر', 'هذا سجل تدريب العينة على جهازك؛ يساعدك على معرفة ما راجعته وما يحتاج متابعة.', el('button', { class:'btn', type:'button', onClick:downloadProgress }, 'صدّر تقدمي', icon('download'))),
    el('div', { class:'stats' }, el('div', { class:'stat' }, el('strong', {}, `${completed} / ${sample.lessons.length}`), el('p', {}, 'دروس أتممت تمارينها')),
      el('div', { class:'stat' }, el('strong', {}, `${solved} / ${total}`), el('p', {}, 'إجابات صحيحة في العينة')),
      el('div', { class:'stat' }, el('strong', {}, `${skills.size}`), el('p', {}, 'مفاهيم تدرّبت عليها'))),
    el('div', { class:'split' }, el('div', { class:'stack' }, el('section', { class:'panel' }, el('h2', {}, 'ما الذي تدرّبت عليه؟'), rows),
      el('section', { class:'panel' }, el('h2', {}, 'كيف كانت خطوتك الأولى؟'), el('p', { class:'muted small' }, 'ملاحظة اختيارية تحفظ على هذا الجهاز فقط. لا تكتب اسمك أو بيانات شخصية.'),
        el('label', { class:'field-label', for:'sample-feedback' }, 'ما الجزء الذي كان واضحًا؟ وما الذي يحتاج شرحًا أبسط؟'),
        el('textarea', { id:'sample-feedback', class:'feedback-area', maxlength:2000, value:state.feedback, onInput:event => { state.feedback = event.target.value; save(); } }),
        el('p', { class:'small muted' }, 'تُضمّن الملاحظة عند تصدير تقدمك.'))),
      el('aside', { class:'panel side-summary' }, el('h3', {}, isDone() ? 'أتممت العينة. ما بعد ذلك؟' : 'طريقك ما زال مفتوحًا'), el('p', {}, isDone() ? 'جرّب شرح المفاهيم لشخص آخر. ثم اختر اتجاهك؛ المسارات المتخصصة ستضيف مشروعات وتقييمات أوسع.' : 'ارجع إلى أقرب درس وأكمل التدريب. الخطأ جزء من التعلّم.'), btn(isDone() ? 'استكشف هدفي التالي' : 'واصل التدريب', isDone() ? '#start' : linkLesson(currentLesson().id)))));
}
function renderGlossary() {
  return el('div', {}, heading('مصطلحاتك الأولى', 'المعنى بالعربية، والاسم التقني يساعدك على قراءة الكود والتوثيق لاحقًا.'),
    el('div', { class:'glossary-list' }, sample.glossary.map(term => el('article', { class:'glossary-term' }, el('h2', {}, term.term), el('bdi', {dir:'ltr'}, term.technical), el('p', {}, term.definition)))));
}
function render(resetScroll = false) {
  const [route, id] = location.hash.slice(1).split('/');
  const name = ['start','plan','lesson','progress','glossary'].includes(route) ? route : 'start';
  const view = name === 'plan' ? renderPlan() : name === 'lesson' ? renderLesson(id) : name === 'progress' ? renderProgress() : name === 'glossary' ? renderGlossary() : renderStart();
  root.replaceChildren(shell(view, name));
  document.title = `${name === 'lesson' ? sample.lessons.find(lesson => lesson.id === id)?.title ?? 'الدرس' : {start:'خطوتك الأولى', plan:'خطتي التعليمية', progress:'تقدمي في العينة', glossary:'قاموس المصطلحات'}[name]} | مسار`;
  if (resetScroll) { window.scrollTo(0, 0); document.getElementById('main')?.focus({preventScroll:true}); }
}

async function load() {
  try {
    const responses = await Promise.all([fetch('/content/sample.json'), fetch('/content/graph.json')]);
    if (responses.some(response => !response.ok)) throw new Error('ملفات الدروس غير متاحة');
    [sample, graph] = await Promise.all(responses.map(response => response.json()));
    const validation = validateGraph(graph);
    if (!validation.valid) throw new Error('خريطة العينة تحتاج مراجعة');
    let raw, serialized;
    try { serialized = localStorage.getItem(STORAGE_KEY); }
    catch { storageAvailable = false; }
    try { raw = JSON.parse(serialized ?? 'null'); } catch { raw = null; }
    state = sanitizeState(raw, sample, graph);
    render();
    window.addEventListener('hashchange', () => render(true));
    window.addEventListener('storage', event => {
      if (event.key !== STORAGE_KEY) return;
      try { state = sanitizeState(JSON.parse(event.newValue ?? 'null'), sample, graph); render(false); announce('تغير تقدم العينة في تبويب آخر. تم تحديث العرض.'); } catch { /* Keep the current valid local session. */ }
    });
  } catch (error) {
    root.replaceChildren(el('main', { class:'error-page', id:'main' }, el('h1', {}, 'تعذر تجهيز العينة الآن'), el('p', {}, 'تأكد من تشغيل الخادم المحلي واكتمال ملفات المحتوى، ثم حاول مرة أخرى.'), el('p', { class:'muted small' }, error.message), el('button', { class:'btn primary', type:'button', onClick:() => location.reload() }, 'حاول مرة أخرى')));
  }
}
load();
