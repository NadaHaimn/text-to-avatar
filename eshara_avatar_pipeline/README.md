# Eshara Avatar Pipeline — نص/صوت/يوتيوب ← رابط أفاتار جاهز للتشغيل

بايبلاين FastAPI بيكمل شغل `eshara_pipeline` (المشروع الأول)، بس بدل
ما يرجع gloss JSON بس، بيرجع **رابط جاهز** يتفتح في WebView/iframe
والأفاتار (من مشروع [algerianSignLanguage-avatar](https://github.com/linuxscout/algerianSignLanguage-avatar))
بيتحرك تلقائيًا.

```
YouTube/Audio/Text
      │
      ▼ (زي المشروع الأول بالظبط: yt-dlp → faster-whisper → Gemini)
      │
      ▼ مطابقة كل كلمة مع قائمة gloss "المتاحة فعليًا" (ملفات .sigml)
      │
      ▼ بناء رابط: {avatar_url}/index.html?words=كلمة1,كلمة2
      │
      ▼
   الفلاتر يفتحوا الرابط في WebView → الأفاتار يتحرك تلقائيًا
```

---

## 0. فكرة مهمة قبل أي حاجة: إزاي المشروع الأصلي شغال؟

مشروع `algerianSignLanguage-avatar` **مالوش API خالص** — هو صفحة ويب
واحدة (`web-simulator/index.html`) بتشغّل محرك 3D اسمه CWASA جوه
المتصفح مباشرة (WebGL). المستخدم بيكتب كلمات في input، يدوس زرار
"Sign"، والـ JS بيدور على ملفات `.sigml` بنفس اسم الكلمة بالظبط
ويشغّلها واحدة ورا التانية.

**يعني الأفاتار بيتحرك live جوه المتصفح، ومفيش "فيديو" بيتخرّج كملف.**
لأي حد (فلاتر، فريق تاني) عايز "يشغّل الأفاتار"، لازم يفتح صفحة ويب،
مش يستقبل ملف فيديو.

### التعديل الوحيد اللي عملناه على المشروع الأصلي
ضفنا **كود JS صغير** في نسخة من `index.html` (موجودة في `avatar_patch/`)
بيقرأ `?words=...` من رابط الصفحة نفسها ويشغّل الأفاتار تلقائيًا لما
الصفحة تفتح — بدل ما يستنى حد يدوس زرار يدويًا. باقي الملف **زي ما هو
100%**، فالاستخدام اليدوي (القوائم، الـ input) لسه شغال عادي.

---

## 1. التركيب (Setup) — خطوتين متوازيتين

### أ) سيرفر الأفاتار (web-simulator المعدّل)

```bash
# 1. نزّلي المشروع الأصلي
git clone https://github.com/linuxscout/algerianSignLanguage-avatar.git

# 2. استبدلي index.html بالنسخة المعدّلة من avatar_patch/
cp avatar_patch/index.html algerianSignLanguage-avatar/web-simulator/index.html

# 3. شغّلي سيرفر بسيط (زي ما الـ Makefile بتاع المشروع بيقول بالظبط)
cd algerianSignLanguage-avatar/web-simulator
python3 -m http.server 8081
```

دلوقتي `http://localhost:8081/index.html` شغال. جربي:
```
http://localhost:8081/index.html?words=أنا
```
المفروض الأفاتار يتحرك تلقائيًا من غير ما تدوسي أي زرار.

> **ملحوظة نشر (production):** للاستخدام الحقيقي مع الفلاتر، لازم
> ترفعي المجلد ده (بعد استبدال `index.html`) على سيرفر ثابت وصولاً
> عام إليه (VPS، Render Static Site، Netlify، أو حتى GitHub Pages).
> `localhost` مش هيشتغل لحد تاني غير جهازك.

### ب) الـ API (البايبلاين)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# افتحي .env وحطي:
#   - GEMINI_API_KEY (من https://aistudio.google.com/apikey)
#   - AVATAR_PLAYER_BASE_URL على رابط سيرفر الأفاتار (المحلي أو المنشور)
```

### ج) توليد قائمة الـ gloss المتاحة

الملف `data/available_glosses.json` **موجود بالفعل جاهز** (418 كلمة،
مستخرجة من نفس نسخة المشروع اللي فحصناها). لو فريق الأفاتار ضاف
كلمات جديدة لاحقًا، ولّدي القائمة من جديد:

```bash
python tools/extract_available_glosses.py \
  --sigml-dir /path/to/algerianSignLanguage-avatar/data/sigml \
  --output data/available_glosses.json
```

---

## 2. التشغيل

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: **http://localhost:8000/docs**

---

## 3. استخدام الـ API

### مثال: نص عربي مباشر
```bash
curl -X POST http://localhost:8000/translate \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "text",
    "content": "أنا أحب أن أذهب إلى طبيب أسنان",
    "simplify_with_gemini": false
  }'
```

الـ response:
```json
{
  "original_text": "أنا أحب أن أذهب إلى طبيب أسنان",
  "simplified_text": null,
  "gloss_sequence": [
    {"word": "أنا", "gloss": "أنا", "match_score": 100.0, "matched": true},
    {"word": "أحب", "gloss": "أحب", "match_score": 0.0, "matched": false},
    {"word": "طبيب أسنان", "gloss": "طبيب أسنان", "match_score": 100.0, "matched": true}
  ],
   "avatar_player_url": "http://localhost:8081/index.html?words=أنا,طبيب%20أسنان",
  "unmatched_words": ["أحب", "أن", "أذهب", "إلى"],
  "timings": {"gloss_matching_seconds": 0.001, "total_seconds": 0.85, ...},
  "warnings": ["4 كلمة اتشالت من التشغيل لعدم وجود ملف sigml لها"]
}
```

**الفلاتر بس بيفتحوا `avatar_player_url` في WebView.** خلاص، الأفاتار
هيتحرك تلقائيًا.

### باقي الـ endpoints
- `POST /translate-audio` — رفع ملف صوت مباشرة (نفس فكرة المشروع الأول)
- `GET /available-glosses` — قائمة كل الكلمات المضمون تشغيلها (مفيدة لـ autocomplete)
- `GET /health` — فحص حالة السيرفر

---

## 4. بنية المشروع

```
eshara_avatar_pipeline/
├── app/
│   ├── main.py                      # FastAPI + /translate, /translate-audio
│   ├── config.py                    # إعدادات .env
│   ├── models/schemas.py            # Pydantic models
│   └── services/
│       ├── youtube_service.py       # (من المشروع الأول، بدون تغيير)
│       ├── stt_service.py           # (من المشروع الأول، بدون تغيير)
│       ├── gemini_service.py        # (من المشروع الأول، بدون تغيير)
│       ├── gloss_service.py         # ← مختلف: بيتغذى من ملفات sigml الفعلية
│       ├── avatar_url_service.py    # ← جديد: بناء رابط التشغيل
│       └── pipeline.py              # المايسترو (نسخة معدّلة)
├── avatar_patch/
│   └── index.html                   # نسخة معدّلة من web-simulator الأصلي
├── data/
│   └── available_glosses.json       # 418 كلمة مستخرجة من ملفات sigml الحقيقية
├── tools/
│   └── extract_available_glosses.py # لإعادة توليد القائمة لو الكلمات اتغيرت
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

---

## 5. أهم قرار تصميم: ليه `gloss_service.py` مختلف عن المشروع الأول؟

في المشروع الأول، الـ vocabulary مصدرها Excel (KArSL-502) بيرجع
أي gloss قريب لغويًا. **هنا الموضوع مختلف وأخطر شوية**: أي كلمة
بترجع "matched: true" لازم تتضمن إن فيه ملف `.sigml` بنفس الاسم
بالظبط، وإلا الأفاتار هيتجاهلها بصمت (زي ما بيحصل في الكود الأصلي
بالظبط عبر دالة `isValidGloss`).

عشان كده:
1. مصدر القائمة هو **أسماء ملفات sigml نفسها**، مش قاموس منفصل.
2. `FUZZY_MATCH_THRESHOLD` هنا **90** (مش 70 زي المشروع الأول) —
   لأن تطابق خاطئ هنا معناه الأفاتار **يعمل إشارة غلط تمامًا**
   (مثلاً "أن" ممكن تتطابق مع "أذن" بنسبة 80%)، وده أخطر بكتير من
   إننا نتجاهل كلمة مش موجودة.
3. بندعم الـ **multi-word glosses** (زي "طبيب أسنان"، "بعد غد") بنفس
   منطق الـ sliding window المستخدم في الـ JS الأصلي بالظبط، عشان
   أي كلمة نرجعها "matched" تبقى مضمونة إنها هتشتغل في المشغل.

---

## 6. ليه اخترنا "رابط صفحة" بدل "فيديو MP4"؟

اتقارن 3 خيارات مع الفريق، والقرار كان: **رابط صفحة (embed) هو
الأسهل والأسرع** للفلاتر:

| الخيار | التعقيد على الفلاتر | التعقيد على الباك إند |
|---|---|---|
| **رابط صفحة (المُختار)** | `WebView(url)` وخلاص | متوسط |
| قائمة أسماء sigml | لازم يدمجوا محرك CWASA بأنفسهم | بسيط لكن بينقل التعقيد |
| فيديو MP4 | صفري | معقد جدًا — محتاج headless browser recording (Playwright)، بطيء جدًا، محتاج GPU |

لو الفريق قرر لاحقًا إنه محتاج فيديو MP4 فعليًا (مثلاً للمشاركة على
سوشيال ميديا)، ده ممكن يتضاف كـ endpoint منفصل لاحقًا باستخدام
Playwright لتسجيل الشاشة، لكنه أبطأ بكتير (ثواني لكل كلمة) ومحتاج
موارد سيرفر أكبر.

---

## 7. ملاحظات مهمة

1. **التوقيت بين الكلمات ثابت (1650ms)** — ده جزء من الكود الأصلي
   بتاع `algerianSignLanguage-avatar` نفسه (مش حاجة إحنا ضفناها)،
   مش مبني على طول الأنيميشن الفعلي لكل إشارة. لو فيه إشارات أطول
   من التوقيت ده، ممكن تتقطع. ده تحسين ممكن يتعمل مستقبلاً على
   مستوى الـ JS نفسه لو الفريق حابب.
2. **postMessage للتواصل مع الصفحة الأب**: لو الفلاتر حملوا الصفحة
   جوه `iframe`، الـ patch بيبعت رسائل `postMessage` (`started`,
   `word_played`, `completed`) تقدر تستخدمها لعرض progress bar
   أو تعرفي إمتى الأنيميشن خلصت فعليًا بدل ما تعتمدي على توقيت ثابت.
3. **الكلمات اللي في `unmatched_words`**: دي معناها مفيش ملف sigml
   ليها في المشروع الأصلي أصلاً. الحل الوحيد هو توسيع مجلد `data/sigml`
   بملفات جديدة (وده شغل فريق الأفاتار، مش حاجة نقدر نحلها من جانب
   الـ API).
