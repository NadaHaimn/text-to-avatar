# Eshara Avatar API — Flutter Developer Integration Guide

> **للمطوّر:** هذا المستند هو كل اللي تحتاجه لدمج الـ API مع التطبيق.  
> لا تحتاج لفهم المشروع الداخلي — فقط اتبع هذا الدليل.

---

## 1. البنية العامة

```
Flutter App
    │
    ▼  POST /translate   (نص أو يوتيوب)
    │  POST /translate-audio  (ملف صوتي)
    │
    ├── Response: { avatar_player_url: "http://..." }
    │
    ▼  WebViewWidget.loadRequest(avatar_player_url)
    │
    └── الأفاتار 3D يتحرك تلقائيًا داخل WebView
```

---

## 2. إعداد الـ URLs

### Android Emulator
```
API_BASE    = http://10.0.2.2:8000
AVATAR_BASE = http://10.0.2.2:8081/index.html
```
> `10.0.2.2` هو الـ alias الخاص بـ Android Emulator للـ localhost بتاع الجهاز المضيف.

### iOS Simulator
```
API_BASE    = http://127.0.0.1:8000
AVATAR_BASE = http://127.0.0.1:8081/index.html
```

### Real Device (on same Wi-Fi)
```
API_BASE    = http://192.168.x.x:8000   ← IP جهازك على الشبكة
AVATAR_BASE = http://192.168.x.x:8081/index.html
```

### Production (later)
```
API_BASE    = https://api.your-domain.com
AVATAR_BASE = https://avatar.your-domain.com/index.html
```

---

## 3. Endpoints

### `GET /health`
تأكد أن السيرفر شغال قبل أي request.

**Response:**
```json
{
  "status": "ok",
  "avatar_player_base_url": "http://localhost:8081/index.html",
  "available_glosses_count": 418
}
```

---

### `POST /translate` — الأهم

**Request Body (JSON):**
```json
{
  "input_type": "text",
  "content": "أنا أذهب إلى المدرسة",
  "simplify_with_gemini": true,
  "avatar": "marc"
}
```

| Field | Type | Values | Notes |
|-------|------|--------|-------|
| `input_type` | string | `"text"` / `"youtube"` | لـ audio استخدم `/translate-audio` |
| `content` | string | النص العربي أو رابط يوتيوب | |
| `simplify_with_gemini` | boolean | `true` / `false` | `true` ينصح به للنصوص الطويلة |
| `avatar` | string | `"marc"`, `"anna"`, `"francoise"`, `"luna"`, ... | يحدد الشخصية 3D التي ستظهر |

**Response:**
```json
{
  "original_text": "أنا أذهب إلى المدرسة",
  "simplified_text": "أنا ذهب مدرسة",
  "gloss_sequence": [
    {"word": "أنا", "gloss": "أنا", "match_score": 100.0, "matched": true},
    {"word": "ذهب", "gloss": "يذهب", "match_score": 93.0, "matched": true},
    {"word": "مدرسة", "gloss": "مدرسة", "match_score": 100.0, "matched": true}
  ],
  "avatar_player_url": "http://localhost:8081/index.html?words=%D8%A3%D9%86%D8%A7,%D9%8A%D8%B0%D9%87%D8%A8,%D9%85%D8%AF%D8%B1%D8%B3%D8%A9",
  "unmatched_words": [],
  "timings": {
    "gemini_simplification_seconds": 0.85,
    "gloss_matching_seconds": 0.001,
    "total_seconds": 0.86
  },
  "warnings": []
}
```

**👉 الكود الوحيد اللي تحتاجه في Flutter:**
```dart
// 1. استدعاء الـ API
final response = await http.post(
  Uri.parse('$apiBase/translate'),
  headers: {'Content-Type': 'application/json'},
  body: jsonEncode({
    'input_type': 'text',
    'content': arabicText,
    'simplify_with_gemini': true,
    'avatar': 'anna',
  }),
);
final data = jsonDecode(response.body);
final avatarUrl = data['avatar_player_url'] as String;

// 2. فتح الـ URL في WebView
controller.loadRequest(Uri.parse(avatarUrl));
// خلاص! الأفاتار يتحرك تلقائيًا.
```

---

### `POST /translate-audio` — رفع ملف صوتي

**multipart/form-data:**
```
file: <binary audio file>  (wav / mp3 / m4a / ogg)
simplify_with_gemini: true
avatar: marc
```

**Flutter Code:**
```dart
final request = http.MultipartRequest(
  'POST', Uri.parse('$apiBase/translate-audio'),
)
  ..fields['simplify_with_gemini'] = 'true'
  ..fields['avatar'] = 'anna'
  ..files.add(await http.MultipartFile.fromPath('file', audioFilePath));

final streamed = await request.send();
final response = await http.Response.fromStream(streamed);
final data = jsonDecode(response.body);
final avatarUrl = data['avatar_player_url'] as String;
```

---

### `GET /available-glosses` — الكلمات المدعومة

يرجع 418 كلمة مضمون أن الأفاتار يعرفها. مفيد لـ autocomplete.

**Response:**
```json
{
  "count": 418,
  "glosses": ["أب", "أبيض", "أحمر", "أذن", ...]
}
```

---

## 4. إعداد WebView في Flutter

### pubspec.yaml
```yaml
dependencies:
  webview_flutter: ^4.7.0
  http: ^1.2.0
```

### Android — `android/app/src/main/AndroidManifest.xml`
```xml
<!-- داخل <application> -->
<application android:usesCleartextTraffic="true" ...>
```
> ⚠️ مطلوب لـ `http://` (localhost). في الـ production مع HTTPS مش محتاجه.

### iOS — `ios/Runner/Info.plist`
```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsLocalNetworking</key>
  <true/>
</dict>
```

### الكود
```dart
import 'package:webview_flutter/webview_flutter.dart';

class AvatarScreen extends StatefulWidget {
  final String avatarUrl;
  const AvatarScreen({required this.avatarUrl});
  // ...
}

class _AvatarScreenState extends State<AvatarScreen> {
  late final WebViewController _controller;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        'EsharaEvents',
        onMessageReceived: (msg) {
          // الأفاتار بيبعت events هنا
          final data = jsonDecode(msg.message);
          final status = data['status']; // "started" | "word_played" | "completed"
          debugPrint('Avatar event: $status');
        },
      )
      ..loadRequest(Uri.parse(widget.avatarUrl));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: WebViewWidget(controller: _controller),
    );
  }
}
```

---

## 5. Avatar `postMessage` Events

الأفاتار بيبعت events للصفحة الأب عبر `window.parent.postMessage`:

| Event | متى يُرسَل | البيانات |
|-------|------------|----------|
| `started` | عند بدء التشغيل | `{ requested: [...words], missing: [] }` |
| `word_played` | عند تشغيل كل كلمة | `{ word, index, total }` |
| `completed` | عند انتهاء كل الكلمات | `{ missingWords: [] }` |
| `stopped` | لو المستخدم أوقف | — |

> **ملاحظة:** لاستقبال هذه الـ events في Flutter WebView، تحتاج JavaScript Channel أو
> تستخدم `NavigationDelegate.onPageFinished` + `runJavaScript`.

---

## 6. Error Handling

```dart
if (response.statusCode == 200) {
  // ✅ نجح
} else if (response.statusCode == 400) {
  // خطأ في الـ input (مثلاً بعت audio type في /translate)
  final error = jsonDecode(response.body)['detail'];
} else if (response.statusCode == 500) {
  // خطأ في السيرفر — اعرض رسالة خطأ للمستخدم
  final error = jsonDecode(response.body)['detail'];
}
```

---

## 7. قائمة الـ Dependencies (Backend)

> هذا للمرجعية فقط — الـ AI Engineer يتولى تشغيل الـ API.

- **FastAPI** — الـ server
- **faster-whisper** — تحويل الصوت لنص
- **google-genai** — Gemini API لتبسيط النص  
- **rapidfuzz + pyarabic** — مطابقة الـ glosses
- **yt-dlp** — تحميل صوت يوتيوب

---

## 8. Swagger UI

بعد تشغيل السيرفر، افتح:
```
http://localhost:8000/docs
```
ستجد توثيق تفاعلي كامل لكل الـ endpoints مع أمثلة.
