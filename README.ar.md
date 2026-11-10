# RE4 Tweaks PS2 Installer (Android)

[English](README.md) | **العربية**

<div dir="rtl">

**الإصدار 1.0.1**

[![Stars](https://img.shields.io/github/stars/YEMENI-modder/RE4Ps2TweaksInstaller?style=for-the-badge&logo=github)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/stargazers)
[![Downloads](https://img.shields.io/github/downloads/YEMENI-modder/RE4Ps2TweaksInstaller/total?style=for-the-badge&logo=android&label=Downloads)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/releases/tag/V1.1)
[![Build](https://img.shields.io/github/actions/workflow/status/YEMENI-modder/RE4Ps2TweaksInstaller/build.yml?style=for-the-badge&label=Build)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/actions)

تطبيق أندرويد يثبّت تويك **RE4 Menu Tweaks PS2** على ملف اللعبة الخاص بك Resident Evil 4 (PS2) بصيغة **ISO أو CHD**، كل شيء على جوالك مباشرة. بدون كمبيوتر، بدون Winlator، بدون ملف `.bat`: اختر الملف، اختر لغة القائمة، واضغط *Apply patch*.

يقرأ التطبيق الملف ويستخرج الملف التنفيذي للإقلاع، ثم يطبّق التويك بنفس منطق التحقق والباتش الموجود في المثبّت الأصلي، ثم يكتب النتيجة داخل الملف.

> هذا التطبيق مجرد غلاف للتثبيت. التويك نفسه هو عمل مطوريه الأصليين، راجع قسم [الحقوق](#الحقوق).

## المميزات

- **يدعم ISO وCHD.** اختر أيًّا منهما، ويتعرف التطبيق على النوع تلقائيًا. راجع [دعم CHD](#دعم-chd).
- **تعديل الـ ISO في مكانه.** يبقى `Re4.iso` باسمه `Re4.iso`. لا يوجد ملف ثانٍ بحجم 4 GB، ويُكتب فقط الملف التنفيذي الجديد (بضعة ميجابايت).
- **نسخة احتياطية تلقائية (مفعّلة افتراضيًا).** قبل الباتش تُنسخ نسختك الأصلية بدون تعديل إلى `Re4_Og.iso` بجانبها. يمكنك إيقافها في الخطوة 3. ملف `_Og` الموجود لا يُستبدل أبدًا، لذلك تكرار الباتش لا يمكن أن يتلف نسختك النظيفة.
- **كتابة آمنة.** يُحسب الباتش ويُتحقق منه بالكامل قبل لمس الـ ISO، وإذا فشلت الكتابة يرجع الـ ISO تمامًا كما كان.
- **كشف المنطقة تلقائيًا** (SLES / SLUS / SLPM) من الملف التنفيذي في جذر الصورة.
- **ثلاث لغات للقائمة:** البرتغالية (الأصلية)، الإنجليزية، العربية.
- **تحويل اللغة.** الـ ISO الذي عليه التويك بلغة معينة يُحوَّل إلى اللغة التي تختارها، في أي اتجاه.
- **واجهة التطبيق بالعربية والإنجليزية** (مع دعم RTL)، وتتبدل من الشريط العلوي.

## طريقة الاستخدام

1. ثبّت ملف APK (راجع [Releases](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/releases) أو [ابنِه بنفسك](#البناء-من-المصدر)).
2. افتح التطبيق، اسمح بالوصول للملفات عند الطلب، واضغط **Select ISO** (ملف `.iso` أو `.chd`).
3. اختر لغة القائمة: البرتغالية أو الإنجليزية أو العربية.
4. اترك خيار **تفعيل نسخة احتياطية** مفعّلًا (موصى به) واضغط **Apply patch**.

عند الانتهاء، يحتوي `Re4.iso` على التويك، و`Re4_Og.iso` هو نسختك الأصلية (وينطبق نفس الشيء على `Re4.chd` / `Re4_Og.chd`).

إذا لم يتمكن التطبيق من الحصول على صلاحية الكتابة على مكان الـ ISO الحقيقي (مثلًا لم تُمنح صلاحية الوصول للملفات)، فإنه لا يلمس الـ ISO ويحفظ نسخة معدّلة في `Download/<name>_Patched.iso` (أو `.chd`) بدلًا من ذلك.

تحتاج ملف ISO خاص بك من مصدر قانوني. لا يحتوي هذا المستودع على أي ملفات من اللعبة.

## دعم CHD

ملفات CHD تعمل مثل ملفات ISO تمامًا: اختر ملف `.chd`، اختر اللغة، واضغط *Apply patch*. بدون أي تحويل.

- المدعوم فقط **CHD من نوع DVD** (الذي ينتجه `chdman createdvd`، وهو المستخدم لألعاب PS2). إذا تعذّرت قراءة الملف يخبرك التطبيق بالسبب، وتحويله إلى ISO يعمل دائمًا كحل بديل.
- تُحفظ النتيجة في نفس الملف، مع نفس خيار النسخة الاحتياطية الموجود مع ISO. الباتش على CHD أبطأ من ISO ويحتاج مساحة فارغة تصل إلى **3 أضعاف حجم الـ CHD تقريبًا** أثناء العمل (الأصلي + النسخة الاحتياطية + ملف مؤقت)، ويُحذف المؤقت عند الانتهاء.
- دعم CHD جديد. أبقِ خيار **تفعيل نسخة احتياطية** مفعّلًا، وأبلغ عن أي مشكلة تواجهها.

## نسخ القائمة

| النسخة | الوصف |
|---|---|
| **الأصلية** | القائمة البرتغالية الأصلية تمامًا كما نشرها مطورو التويك. |
| **الإنجليزية** | ترجمة إنجليزية كاملة لنصوص القائمة (التبويبات، الخيارات، الألوان، الأسلحة، الأزياء...). تغيّرت النصوص فقط، بدون أي تغيير في الكود أو الـ offsets أو الـ hooks. التفاصيل، ومنها الملفات التي تُركت بدون ترجمة عمدًا، في [`TRANSLATION_NOTE.txt`](app/src/main/python/dados_en_root/dados/TRANSLATION_NOTE.txt). |
| **العربية** | نصوص قائمة عربية، يرسمها مُصيِّر عربي صغير موضوع في مساحة غير مستخدمة من منطقة كود Files Used (القائمة تستخدم خط بكسلات خاص بها، فخطوط اللعبة لا تُمس). النص يُشكَّل مسبقًا ويُخزَّن بالترتيب البصري. وعندما لا تتسع العبارة العربية في مكانها ذي الحجم الثابت تُستخدم الإنجليزية. |

## كيف يعمل

- **Kotlin**: الواجهة، اختيار الملفات، العمل في الخلفية.
- **Python** عبر [Chaquopy](https://chaquo.com/chaquopy/): منطق الباتش، مأخوذ من المثبّت الأصلي بدون تعديل.
- **[pycdlib](https://github.com/clalancette/pycdlib)**: قراءة نظام ملفات ISO9660.
- **`chd_handler.py`**: قراءة وإعادة كتابة صور CHD.

الباتش يكبّر الملف التنفيذي غالبًا (إضافة Files Used تضيف segment). وبدل إعادة بناء نظام الملفات، وهذا ينقل كل الملفات من أماكنها، يُكتب الملف التنفيذي الجديد بعد آخر سكتور في الصورة ويُحدَّث فقط سجله في المجلد (وحجم الـ volume). كل ملف آخر يبقى في سكتوره. وإذا لم يتغير الحجم تُكتب البايتات ببساطة فوق مكانها الحالي. ثم يُتحقق من النتيجة بقراءتها من جديد.

كل نسخة قائمة تأتي كنسخة كاملة مستقلة من منطق المثبّت (`installer_core.py` و`FilesUsed.py` و`RemoveWeaponSwap.py` و`dados/`) بدل نسخة مشتركة تُبدَّل بياناتها، وهكذا يبقى كود الباتش الأصلي مطابقًا بايت ببايت لأداة الكمبيوتر الأصلية في كل نسخة.

ملاحظات التنفيذ موجودة في الكود نفسه:
`app/src/main/python/iso_handler.py` و`app/src/main/python/chd_handler.py` و
`app/src/main/java/com/yemeni/re4tweaksinstaller/MainActivity.kt`.

## البناء من المصدر

### المتطلبات

| الأداة | الإصدار |
|---|---|
| JDK | 17 |
| Android SDK | Platform 34 (`compileSdk 34`)، minSdk 24 |
| Python | موجود في `PATH` (الـ CI يستخدم 3.11)، يشغّله Chaquopy أثناء البناء لجلب `pycdlib` |
| الإنترنت | أول بناء يحمّل Gradle وAndroid Gradle Plugin وChaquopy (`chaquo.com/maven`) |

الـ Gradle wrapper (8.4) مضمّن، فلا تحتاج تثبيت Gradle.

### Android Studio

1. **File > Open** واختر مجلد المشروع.
2. انتظر انتهاء مزامنة Gradle (يعرض Android Studio تثبيت SDK Platform الناقصة).
3. اختر إعداد `app` واضغط **Run**، أو استخدم **Build > Build APK(s)**.

### سطر الأوامر

```bash
# Linux / macOS
./gradlew assembleDebug

# Windows
gradlew.bat assembleDebug
```

يُكتب ملف APK في `app/build/outputs/apk/debug/app-debug.apk`.

إذا لم يجد Gradle الـ Android SDK، أنشئ ملف `local.properties` في جذر المشروع:

```properties
sdk.dir=/path/to/Android/sdk
```

### GitHub Actions

الملف `.github/workflows/build.yml` يبني APK من نوع debug عند كل push على `main` وعند التشغيل اليدوي (تبويب **Actions**، ثم *Run workflow*)، ثم ينشره كملف zip في release باسم `build-test`.

### ملاحظات

- نسخ debug موقّعة بـ debug keystore الخاص بـ Gradle. هذا مناسب للتثبيت على جهازك، أما الإصدار العام فيحتاج إعداد توقيع خاص به (غير موجود في هذا المستودع).
- المعماريتان `arm64-v8a` و`armeabi-v7a` مضمّنتان.

## هيكل المشروع

```
app/src/main/java/.../MainActivity.kt    الواجهة والتنسيق
app/src/main/python/iso_handler.py       قراءة ISO/CHD، النسخ الاحتياطي، الكتابة
app/src/main/python/chd_handler.py       قارئ / كاتب CHD v5
app/src/main/python/installer_core.py    منطق الباتش الأصلي (القائمة البرتغالية)
app/src/main/python/dados/               ملفات البيانات الأصلية
app/src/main/python/dados_en_root/       النسخة الإنجليزية (نسخة كاملة)
app/src/main/python/dados_ar_root/       النسخة العربية (نسخة كاملة)
tools/                                   سكربتات توليد بيانات الإنجليزية / العربية
```

## إعادة بناء الترجمات

ملفات البيانات الإنجليزية والعربية تُولَّد بسكربتات المجلد `tools/`، فيمكن مراجعة الترجمات وتصحيحها من المصدر. شغّلها من جذر المستودع:

```bash
python3 tools/build_english_dados.py
python3 tools/build_arabic_dados.py [--preview out.png]
```

سكربت العربية يحتاج `pillow` و`arabic-reshaper` و`python-bidi`، إضافة إلى `unicorn` و`capstone` للاختبار الذاتي. وتحدّث السكربتات أيضًا قيم SHA-256 في ملفات JSON الخاصة بالبروفايلات، لأن المثبّت يرفض البيانات التي لا يطابق هاشها.

## الحقوق

تويك **Menu Tweaks PS2** (Enemy HP وMemory Viewer وFree Camera وCheats وغيرها) **ليس** من عمل صاحب هذا المستودع. هذا المشروع مجرد غلاف تثبيت حول عمل فريق المودينج الأصلي. القنوات التالية على يوتيوب معروفة في مجتمع RE4 PS2 بنشر التويك وتغطيته، وتُذكر هنا تقديرًا لجهودهم:

- https://youtube.com/@dn_e_voce
- https://youtube.com/@hardrainmodder
- https://youtube.com/@eusoujeffgamers
- https://youtube.com/@o_ceifeiro_x
- https://youtube.com/@walymodder
- https://youtube.com/@herikre4ps2

رابط تحميل التويك الأصلي / فيديو العرض: https://youtu.be/Sn5NMTdCEzw

### شكر خاص

- **q8tp1**: على اكتشاف مشكلة في التطبيق.
- **scorpion**: على نشر التطبيق وتجربته واقتراح دعم CHD.
- **Ahmed | Weto**: على تجربة النسخة التجريبية واكتشاف المشاكل.

الحقوق نفسها معروضة داخل التطبيق.

### الشفافية بخصوص الذكاء الاصطناعي

صُمّم كود هذا المشروع وكُتب بالكامل بواسطة **Claude** (مساعد الذكاء الاصطناعي من Anthropic)، ويشمل ذلك تطبيق أندرويد، ومنطق التعامل مع الـ ISO والنسخ الاحتياطي، والمُصيِّر العربي وأدوات الترجمة، وبناء GitHub Actions، وملفات README هذه. أما **YEMENI** فوجّه العمل بتعليمات ومراجعات تقنية، واتخذ قرارات التصميم، وبنى التطبيق واختبره على أجهزة حقيقية.

- صاحب المشروع والتوجيه والاختبار: **YEMENI** ([github.com/YEMENI-modder](https://github.com/YEMENI-modder))
- ترجمة قوائم الإنجليزية والعربية: **YEMENI**

إذا كنت أحد مطوري التويك الأصليين (أو تعرف هويتهم المؤكدة) وتريد تصحيح ذكر الحقوق أو إضافة رخصة أو إزالة هذا المشروع، فافتح [Issue](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/issues) في هذا المستودع.

## الرخصة

لم تُحدَّد رخصة لهذا المستودع بعد. حقوق ملفات التويك الأصلية (`app/src/main/python/dados/` و`dados_en_root/` و`dados_ar_root/` وملفات `.py` المرافقة لها) تعود لمؤلفيها الأصليين، ولم تأتِ معها معلومات رخصة. هذا الأمر بانتظار توضيح من المصدر الحقيقي.

</div>
