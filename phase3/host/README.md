# مضيف مختبر NEXORA CODE على Windows

يعمل المختبر داخل آلة Ubuntu 24.04 Minimal مستقلة يشغّلها QEMU بتسريع Windows Hypervisor Platform. ملفات الآلة والبرامج وصورة الإقلاع موجودة في `phase3/.local` على قرص المشروع. خصصت الآلة معالجين افتراضيين وذاكرة 2.5 GiB وقرصًا ديناميكيًا حتى 20 GiB.

تثبّت الآلة خدمة Docker الخاصة بها وgVisor وصورتي Python وNode المحددتين بالـ digest. يستخدم كل تشغيل حاوية مؤقتة بلا شبكة. يستمع الوسيط على `127.0.0.1:8787` داخل الضيف، ويوصل نفق SSH مشفّر تطبيق Windows إليه عبر `127.0.0.1:18787`. يحصر QEMU منفذ SSH في `127.0.0.1:2227` ويثبت السكربت هوية الضيف من المفتاح الذي يخرجه على المنفذ التسلسلي وقت التهيئة. يظل رمز المصادقة في ملف محمي داخل الضيف ويُمرَّر إلى عملية التطبيق وقت التشغيل.

لتشغيل التطبيق والمختبر بعد إعادة تشغيل Windows:

```powershell
& 'F:\تعلم برمجه\phase3\host\Start-NexoraLab.ps1'
```

لتشغيل اختبارات التنفيذ الفعلية على قاعدة PostgreSQL المخصصة للاختبار:

```powershell
& 'F:\تعلم برمجه\phase3\host\Start-NexoraLab.ps1' -Test
```

تستخدم الخطوتان ملف التجميع الحالي للـ API وقاعدة PostgreSQL المحمولة. ارجع إلى [دليل المرحلة الثالثة](../README.md) إذا كنت تهيئ نسخة جديدة وتحتاج إلى البناء أو ترحيل المخطط.

تبدأ الآلة عبر `prepare-vm.py`. يدعم `--provision` تحديث المشغّل داخل الضيف ويعيد تشغيل الآلة لتقييد شبكتها بعد تثبيت التبعيات. يسمح وضع التشغيل بقناة SSH المحلية المحددة ويمنع اتصال الضيف بـ Windows وبالإنترنت. يتيح `--shutdown` إيقاف الضيف عبر SSH. راجع [مثبت Ubuntu](provision-linux.sh) و[دليل المشغّل](../runner/README.md) و[خيار الشبكة المقيدة في QEMU](https://www.qemu.org/docs/master/system/invocation.html).

استُخدمت صورة Canonical الرسمية لنسخة Noble Minimal المؤرخة في 5 نوفمبر 2026. يطابق سكربت الإقلاع بصمة SHA-256 من البيان الموقّع. يستخدم QEMU حزم MSYS2 الموقعة المثبتة في مجلد المشروع. [صورة Canonical](https://cloud-images.ubuntu.com/minimal/releases/noble/release/) و[توقيع MSYS2](https://www.msys2.org/docs/installer/#how-can-i-verify-that-the-downloaded-files-were-generated-by-msys2-developers).
