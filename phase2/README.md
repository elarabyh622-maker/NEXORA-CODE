# NEXORA CODE — المرحلة الثانية: أساس التطبيق

**الحالة في 11 نوفمبر 2026:** المتاح ثلاثة دروس عينة، ومحرر Python وJavaScript في درسين. راجع [دليل المرحلة الثالثة](../phase3/README.md) لترحيل مخطط البيانات وإعداد مشغّل الكود.

الواجهة React وTypeScript، والخادم ASP.NET Core 10، والبيانات PostgreSQL 18.6. تصفح العينة المحلية متاح بلا حساب، بينما تُحفظ الخطط والمراجعات والمسودات والمحاولات في الحساب. يصحح الخادم تمارين الاختيار والإجابة القصيرة بقواعد محددة. المنتج التجاري مدفوع؛ هذه النسخة مخصصة للتطوير والاختبار.

## تشغيل النسخة المجهزة

من Windows PowerShell 5.1 أو PowerShell 7 بحساب Windows الذي أعد القاعدة:

```powershell
& 'F:\تعلم برمجه\phase2\Start-Masar.ps1' -Engine Portable
```

افتح [NEXORA CODE المحلي](http://127.0.0.1:5180). أنشئ حسابك من الواجهة؛ لا يوجد حساب أو كلمة مرور افتراضية. لا يلزم تثبيت حزم للتشغيل على هذا الجهاز. أوقف API بـ `Ctrl+C`، وبعده يمكنك إيقاف القاعدة المحمولة وحدها عبر `scripts/Stop-PortableDatabase.ps1`. تحتفظ السكربتات والمكونات الداخلية بأسماء `Masar` الحالية لتظل طريقة التشغيل متوافقة.

يختار `-Engine Portable` قاعدة مستقلة على `127.0.0.1:55436` داخل `phase2/.local/portable-postgres/data`. حسابات وخطط Docker لا تظهر فيها؛ القاعدة الأصلية على `55435` لم تُنقل أو تُحذف أو تُعد تهيئتها. استخدم `-Engine Docker` فقط بعد استعادة ذلك المحرك إذا أردت بياناته. بيانات التطوير والاختبار منفصلة، وتُحمى بيانات الاعتماد ومفاتيح التطبيق بـ Windows DPAPI. احتفظ بمجلد `.local` عند تنظيف نواتج البناء.

## البناء والتهيئة الأولى

1. استخدم .NET SDK `10.0.403` أو patch متوافق، وNode.js 24، وPowerShell 7. مسار cache في `NuGet.Config` خاص بهذا الجهاز؛ اضبطه عند الانتقال لجهاز آخر مع إبقاء NuGet الرسمي.
2. لـ `Portable` ضع [أرشيف EDB لـ PostgreSQL 18.6 Windows x64](https://www.enterprisedb.com/download-postgresql-binaries) في `.local/portable-postgres/postgresql-18.6-windows-x64.zip`. [الرابط المستخدم من صفحة المزود](https://sbp.enterprisedb.com/getfile.jsp?fileid=1260609). لا مثبّت أو خدمة نظام. تفحص التهيئة مسارات الأرشيف والإصدار وتسجل بصمته محليًا.
3. من `phase2` نفّذ `scripts/Initialize-Masar.ps1 -Engine Portable` مرة أولى. يجهز القاعدتين ويبني التطبيق ويطبق الترحيل ويحمل عينة المرحلة الأولى. التشغيل اليومي لا يرحّل ولا يستورد. لإعادة البناء فقط استخدم `scripts/Build-Masar.ps1`.

عند وجود أحرف عربية في المسار، تنشئ السكربتات junction باسم لاتيني في مجلد Windows المؤقت، وتتأكد أنه يشير إلى مجلد المشروع. تبقى البيانات في مكانها. كلمة بدء `initdb` تمر عبر قناة خاصة بالمستخدم دون حفظها كنص عادي. راجع [initdb](https://www.postgresql.org/docs/18/app-initdb.html) و[pg_ctl](https://www.postgresql.org/docs/18/app-pg-ctl.html).

## إدارة المحتوى

بعد إنشاء حسابك، تستطيع من الجهاز نفسه منحه إدارة المحتوى محليًا:

```powershell
& 'F:\تعلم برمجه\phase2\scripts\Promote-MasarAdmin.ps1' -UserName 'اسم_الحساب' -Engine Portable
```

حدّث الجلسة لتظهر مساحة الإصدارات. الحزمة تمر بمسودة ومراجعتين ونشر. اختيار إصدار البداية مستقل ومسجل؛ لا يغيّر إصدارات الخطط المحفوظة. عند تقاعد البداية يمكن اختيار أي إصدار منشور باقٍ صراحة. نشر العينة داخل النسخة المحلية لا يعني نشرًا عامًا.

## الفحوص

شغّل API الاختبار بـ `./Start-Masar.ps1 -Engine Portable -Database masar_phase2_tests -Port 5181`، ثم `scripts/Test-Integration.ps1 -Engine Portable` و`scripts/Probe-Database.ps1 -Engine Portable` من نافذة ثانية. تستخدم الاختبارات حسابات ومحتوى اصطناعيًا في قاعدة الاختبار. اختبارات Domain في `Masar.slnx`، والواجهة عبر `npm test` من `apps/web`.

[تقرير التحقق](docs/VALIDATION_REPORT.md) · [الجلسات](docs/TEAM_EXECUTION.md) · [عقد التنفيذ](CONTRACT.md) · [الخادم](docs/API.md) · [المراجعة المستقلة](docs/INDEPENDENT_REVIEW.md)
