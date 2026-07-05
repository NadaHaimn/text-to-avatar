"""
gloss_service.py
-----------------
مطابقة كل كلمة في النص مع أقرب gloss **موجود فعليًا كملف .sigml**
في مشروع algerianSignLanguage-avatar.

=== ليه المصدر هنا ملف JSON مش Excel؟ ===
لأن مصدر الحقيقة الوحيد هنا هو: "هل فيه ملف sigml بالاسم ده ولا لأ؟"
لو رجّعنا gloss من قاموس منفصل (زي Excel KArSL-502) بدون التأكد إن
فيه ملف sigml مطابق بالظبط، الأفاتار هيفشل يشغلها والـ JS هيتجاهلها
بصمت (زي ما بيحصل في findGlosses الأصلية).

بنستخرج القائمة دي مباشرة من أسماء ملفات web-simulator/sigml/*.sigml
(موجودة في data/available_glosses.json — شوفي تعليمات التحديث تحت).

=== دعم الكلمات المتعددة (multi-word glosses) ===
بعض الإشارات بتتكون من كلمتين (زي "طبيب أسنان"، "بعد غد"). نفس منطق
الـ sliding window المستخدم في index.html الأصلي (بيجرب طول 2 قبل 1)
متبع هنا في match_text عشان يتوافق مع سلوك المشغل بالظبط.

=== Optimizations ===
1. القائمة بتتحمل مرة واحدة وتتطبع (normalize) مسبقًا، singleton.
2. كاش داخلي لكل كلمة اتطابقت قبل كده.
3. بحث بالـ multi-word أولاً (sliding window) زي المشغل الأصلي بالظبط،
   عشان أي كلمة بترجع من هنا "matched" تبقى مضمونة إنها هتتشغل فعليًا.
"""
import json
from pyarabic.araby import strip_tashkeel, normalize_hamza
from rapidfuzz import process, fuzz
from functools import lru_cache
from app.config import get_settings


def normalize_arabic(text: str) -> str:
    """نفس الـ normalization المستخدم في مشروع Eshara الأساسي"""
    text = normalize_hamza(text)
    text = strip_tashkeel(text)
    text = text.strip()
    if text.startswith("ال") and len(text) > 3:
        text = text[2:]
    text = text.replace("ة", "ه").replace("ى", "ي")
    return text


class AvatarGlossMatcher:
    def __init__(self, available_glosses_path: str, threshold: int):
        self.threshold = threshold
        self._match_cache: dict[str, dict] = {}

        with open(available_glosses_path, encoding="utf-8") as f:
            raw_glosses: list[str] = json.load(f)

        # بنحتفظ بالاسم الأصلي (زي ما هو، بمسافاته لو فيها) عشان ده
        # اللي المشغل محتاجه بالظبط كاسم ملف — والنسخة المطبعة نستخدمها
        # للمطابقة بس
        self.normalized_to_original: dict[str, str] = {}
        for gloss in raw_glosses:
            normalized = normalize_arabic(gloss.strip())
            self.normalized_to_original[normalized] = gloss.strip()

        self.normalized_choices = list(self.normalized_to_original.keys())

        # ماكس عدد كلمات في أي gloss (لضبط حجم الـ sliding window ديناميكيًا)
        self.max_gloss_words = max(
            (len(g.split()) for g in self.normalized_to_original.values()), default=1
        )

    def _lookup_normalized(self, normalized_phrase: str) -> dict | None:
        """exact match ثم fuzzy match على عبارة مطبعة واحدة"""
        if normalized_phrase in self.normalized_to_original:
            return {
                "gloss": self.normalized_to_original[normalized_phrase],
                "match_score": 100.0,
                "matched": True,
            }
        best = process.extractOne(
            normalized_phrase,
            self.normalized_choices,
            scorer=fuzz.ratio,
            score_cutoff=self.threshold,
        )
        if best is not None:
            matched_key, score, _ = best
            return {
                "gloss": self.normalized_to_original[matched_key],
                "match_score": round(score, 2),
                "matched": True,
            }
        return None

    def match_text(self, text: str) -> list[dict]:
        """
        بتطبق نفس منطق sliding window المستخدم في index.html الأصلي
        (بتجرب أطول عبارة الأول، أقل احتمال تفوّت gloss متعدد الكلمات).
        """
        words = [w for w in text.split() if w.strip()]
        results = []
        i = 0
        while i < len(words):
            matched_this_round = False
            for length in range(min(self.max_gloss_words, len(words) - i), 0, -1):
                phrase = " ".join(words[i:i + length])
                normalized_phrase = normalize_arabic(phrase)

                # Check cache first
                if normalized_phrase in self._match_cache:
                    cached = self._match_cache[normalized_phrase]
                    if cached["matched"]:
                        # Cache HIT — use it and advance
                        results.append({**cached, "word": phrase})
                        i += length
                        matched_this_round = True
                        break
                    else:
                        # Cache MISS — try shorter phrase
                        continue

                # Not in cache — do the lookup
                lookup = self._lookup_normalized(normalized_phrase)
                if lookup is not None:
                    self._match_cache[normalized_phrase] = lookup
                    results.append({**lookup, "word": phrase})
                    i += length
                    matched_this_round = True
                    break
                else:
                    # Store miss in cache to avoid repeated rapidfuzz calls
                    self._match_cache[normalized_phrase] = {
                        "matched": False,
                        "gloss": phrase,
                        "match_score": 0.0,
                    }

            if not matched_this_round:
                # مفيش تطابق حتى لكلمة واحدة — سجليها كـ unmatched واتقدمي
                results.append({
                    "word": words[i],
                    "gloss": words[i],
                    "match_score": 0.0,
                    "matched": False,
                })
                i += 1

        return results


@lru_cache
def get_avatar_gloss_matcher() -> AvatarGlossMatcher:
    settings = get_settings()
    return AvatarGlossMatcher(
        available_glosses_path=settings.available_glosses_path,
        threshold=settings.fuzzy_match_threshold,
    )
