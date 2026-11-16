# NEXORA CODE | مشغّل Python وJavaScript

وسيط HTTP بمكتبة Python القياسية، يستمع على `127.0.0.1:8787` في مضيف Linux مستقل. يستدعيه API من خلال عنوان HTTPS خاص، ويشغّل كل طلب في حاوية `runsc` مؤقتة. يدعم Python console وJavaScript بنمط Node.js CommonJS. صور التشغيل جاهزة ومثبّتة بالـ digest ويُضبط اختيارها لدى المشغّل.

## تجهيز المضيف

1. خصص مضيف Linux أو VM مستقلًا بــ cgroup v2، وPython 3.10+ وDocker Engine محلي على `/var/run/docker.sock`. احصر الوصول إلى شبكة المضيف وإلى المقبس. صلاحية مجموعة `docker` تعطي سلطة إدارة المضيف، لذلك خصّص حساب الخدمة `nexora-runner` لهذا المضيف واجعل ملفات الخدمة تحت ملكية `root`. احفظ بيانات التطبيق وقاعدة البيانات على مضيف منفصل. راجع [تثبيت gVisor](https://gvisor.dev/docs/user_guide/install/) و[إعداد Docker مع runsc](https://gvisor.dev/docs/user_guide/quick_start/docker/).
2. سجّل `runsc` كـ runtime بالاسم `runsc` وبخيارات gVisor الافتراضية. يحتاج Docker إلى دعم حدود الذاكرة وswap وحصة CPU وحد العمليات. راجع [موارد Docker](https://docs.docker.com/engine/containers/resource_constraints/) و[حدود تطبيقات gVisor](https://gvisor.dev/docs/user_guide/compatibility/).
3. راجع واختَر إصدارًا محددًا من صورتي Linux الرسميتين `python` و`node` من نوع Debian slim، وتحقق من digest وأصل الصورة ومعمارية المضيف. يتوقع الملف التنفيذي `/usr/local/bin/python` أو `/usr/local/bin/node` داخل الصورة. نفّذ `docker pull` للمرجع الكامل بالـ digest في خطوة التجهيز على المضيف المخصص، قبل تشغيل الخدمة. الطلبات تستخدم `--pull=never`. راجع [صورة Python](https://hub.docker.com/_/python) و[صورة Node.js](https://hub.docker.com/_/node).
4. ثبّت `broker.py` و`sandbox.py` تحت `/opt/nexora-code-runner`، وثبّت الوحدة `nexora-code-runner.service` في `/etc/systemd/system`. أنشئ `/etc/nexora-code-runner/runner.env` بملكية `root` وصلاحية `0600`. ضع فيه المتغيرات التالية، واملأ مراجع الصور من خطوة المراجعة. ولّد رمز Bearer عشوائيًا بطول 32 بايت على الأقل، مشفّرًا Base64url دون padding، وشاركه مع API عبر مخزن الإعدادات الخاص به.

   ```ini
   NEXORA_RUNNER_PYTHON_IMAGE=python@sha256:<reviewed-digest>
   NEXORA_RUNNER_JAVASCRIPT_IMAGE=node@sha256:<reviewed-digest>
   NEXORA_RUNNER_BEARER_TOKEN=<generated-private-token>
   ```

5. شغّل الوحدة على المضيف المخصص. يفحص بدء الخدمة تسجيل `runsc` والمتحكمات والصورتين المحليتين، وينفذ برنامجًا ثابتًا بكل لغة ويفحص UTF-8 وEOF وهوية المستخدم. يفحص Python أيضًا أن الجذر للقراءة فقط وأن `/tmp` محدود وأن الحاوية ترى واجهة loopback فقط. يتوقف البدء عند أي إخفاق قبل فتح المنفذ.

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now nexora-code-runner
   sudo journalctl -u nexora-code-runner -n 30 --no-pager
   ```

6. وجّه `POST /v1/execute` من وكيل TLS خاص إلى `http://127.0.0.1:8787`. اسمح بالاتصال من API على الشبكة الخاصة. استخدم شهادة موثوقة لدى API، وحدًا أقصى قدره `246016` بايت للطلب، وتمرير `Authorization` و`Content-Type` و`Content-Length`، وتخزين الطلب مؤقتًا لدى الوكيل قبل إرساله. اضبط مهلة API لكل طلب على 25 ثانية واضبط الوكيل بحيث يتيحها. استبعد رمز Bearer والمحتوى من سجلات الوكيل.

## عقد التنفيذ

```http
POST /v1/execute
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{"language":"python","code":"print(input())","stdin":"مرحبا\n"}
```

```json
{"status":"completed","stdout":"مرحبا\n","stderr":""}
```

القيم المدعومة للحالة هي `completed` و`code_error` و`timed_out` و`output_limit` و`infrastructure_error`. تعرض أخطاء إنشاء الحاوية أو التحقق من الخروج `infrastructure_error` دون تفاصيل تشغيل المضيف. أخطاء HTTP مثل `401` و`400` و`413` و`415` و`503` تعني أن الطلب رُفض أو أن سعة التنفيذ مشغولة.

| الحد | القيمة |
|---|---|
| حجم الشيفرة والمدخل | 32 KiB و8 KiB من UTF-8 |
| خرج العمليتين | 16 KiB لـ `stdout` و`stderr` مجتمعين، مع فك UTF-8 واستبدال البايتات غير الصالحة |
| وقت التشغيل | 4 ثوانٍ، بالإضافة إلى خطوات Docker المحددة بمهلة |
| تشغيل متزامن | حاويتان، وحتى 8 اتصالات معالجة |
| موارد الحاوية | 192 MiB دون swap إضافي، نصف CPU، حد PID قدره 32، و`/tmp` بحجم 4 MiB |

تعمل الحاوية بمعرّفي المستخدم والمجموعة `65532:65532`، مع إسقاط capabilities، وتفعيل `no-new-privileges`، وجذر للقراءة فقط، وشبكة Docker من نوع `none`. تتلقى الشيفرة والمدخل كإطار بايتات عبر stdin. تُحفظ الملفات المؤقتة داخل `/tmp` بالحاوية. يحد الوسيط الخرج في الذاكرة، ويوقف اتصال Docker عند تجاوز الزمن أو الخرج، ويزيل الحاوية بالقوة بعد مطابقة الاسم والوسم. إذا تعذّر التأكد من الإزالة، تتوقف الخدمة عن استقبال تشغيل جديد. تتحقق خطوة بدء الخدمة و`ExecStopPost` من الحاويات المتبقية التي تحمل الاسم والوسم المخصّصين. إعدادات Docker الافتراضية وصور التشغيل جزء من حدود الثقة على المضيف.

## التحقق

شغّل اختبارات الوسيط المحلية من جذر المستودع. تستخدم هذه الاختبارات برامج ثابتة للتحقق من الجمع بين `stdout` و`stderr` والمهلة، وتستبدل Docker للتحقق من مسار الفشل والتنظيف. ترفض خدمة التشغيل Windows وWSL.

```sh
python -B -m unittest discover -s phase3/runner -v
```

بعد تشغيل الخدمة على المضيف المخصص، شغّل `smoke.py` برمز Bearer في بيئة عملية التحقق، ثم افحص قائمة الحاويات على المضيف. تستعمل المجموعة إدخالًا عربيًا، وقراءة stdin حتى EOF، وخطأ حسابيًا، وحد الخرج، وانتهاء المهلة. مرّر `--url` بعنوان HTTPS الخاص لإعادة الفحص من مضيف API.

```sh
python3 -B smoke.py
docker container ls -a --filter 'label=org.nexora.code.phase3.runner=1'
```

تحتاج البيئة الفعلية إلى نتيجة `PASS` لكل حالة، وقائمة فارغة للحاويات الخاصة بالمشغّل عند اكتمال الاختبار. يشمل القبول على المضيف أيضًا التحقق من أن إعدادات `runsc` هي إعدادات الحزم المراجعة، ومن تطبيق حدود cgroup والهوية والكتابة والشبكة لكلتا الصورتين. نفّذ دورة إيقاف وتشغيل للمشغّل في نافذة اختبار وتحقق من التنظيف قبل إتاحة المسار للمتعلمين. مرجع معاني أعلام الحاوية في [Docker container create](https://docs.docker.com/reference/cli/docker/container/create/).
