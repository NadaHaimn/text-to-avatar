"""
gemini_service.py
------------------
مسؤول عن حاجة واحدة محددة: تبسيط/تطبيع النص العربي عشان
يبقى أقرب لبنية جملة لغة الإشارة، قبل ما يروح لمرحلة الـ
gloss matching (rapidfuzz).

=== قرار مهم: ليه Gemini مش بيعمل الـ matching النهائي؟ ===
لأن الـ vocabulary بتاعتك (KArSL-502) محدودة وثابتة. لو سبنا LLM
يختار الـ gloss نفسه، ممكن "يخترع" كلمة مش موجودة في الداتا ست
(hallucination)، أو يديكي نفس المعنى لكن بصيغة مختلفة عن اللي
موجود في الـ Excel بتاعك. الـ rapidfuzz matching (في gloss_service.py)
هو اللي بيضمن إن كل حاجة راجعة فعلاً موجودة في الـ vocabulary.

دور Gemini هنا هو بس: تبسيط لغوي (حذف حروف جر زيادة، توحيد الأزمنة،
تقصير الجمل) — ده بيسهّل مهمة الـ matching اللي بعده، مش بيستبدلها.

=== ملحوظة SDK ===
بنستخدم مكتبة google-genai (الـ SDK الموحّد الرسمي الجديد من Google).
المكتبة القديمة google-generativeai بقت deprecated رسميًا من نوفمبر
2025 ومبقاش فيها تحديثات، فمتستخدموهاش في أي كود جديد.

=== Optimizations ===
1. generation_config بيحدد temperature=0.1 (شبه deterministic) —
   إحنا مش عايزين إبداع هنا، عايزين نفس النتيجة تقريبًا كل مرة.
2. max_output_tokens محدود = استجابة أسرع (مفيش داعي لأكتر من
   طول النص الأصلي تقريبًا).
3. الـ client بيتبني مرة واحدة (singleton) زي الـ Whisper بالظبط.
"""
from google import genai
from google.genai import types
import time
from functools import lru_cache
from app.config import get_settings

SIMPLIFICATION_PROMPT = """أنت مساعد متخصص في تبسيط النصوص العربية لتناسب لغة الإشارة.
حوّل النص التالي إلى صيغة مبسطة بالمعايير الآتية:
- جمل قصيرة جدًا، فعل + فاعل + مفعول به فقط
- احذف حروف الجر والزوائد غير الضرورية للمعنى
- استخدم صيغة المضارع أو الماضي البسيط، لا صيغ معقدة
- حافظ على الترتيب المنطقي للأحداث
- لا تضف أي شرح أو مقدمة، أعد فقط النص المبسط

النص الأصلي:
{text}

النص المبسط:"""


@lru_cache
def _get_client() -> genai.Client:
    """singleton — الـ client بيتهيأ مرة واحدة بس"""
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def simplify_text(text: str) -> tuple[str, float]:
    """
    بيبسط النص العربي عبر Gemini.

    Returns:
        (النص المبسط, الوقت المستغرق بالثانية)
    """
    client = _get_client()
    settings = get_settings()
    prompt = SIMPLIFICATION_PROMPT.format(text=text)

    start = time.time()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,        # شبه deterministic، مش عايزين تنويع إبداعي
            max_output_tokens=512,  # كافي جدًا لجملة مبسطة
        ),
    )
    elapsed = time.time() - start

    simplified = response.text.strip()
    return simplified, elapsed
