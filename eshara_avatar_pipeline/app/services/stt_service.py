"""
stt_service.py
---------------
تحويل الصوت لنص عربي باستخدام faster-whisper (مش Whisper الأصلي).

=== ليه faster-whisper بالذات؟ ===
- نفس دقة OpenAI Whisper بالظبط (نفس الأوزان) لكن بمحرك CTranslate2
  اللي بيخليه أسرع بحوالي 4x على نفس الهاردوير، وبياخد ذاكرة أقل.
- مجاني 100% وشغال أوفلاين (من غير API key ولا حدود usage).
- بيدعم int8 quantization على الـ CPU، وده مهم جدًا لو مفيش GPU.

=== Optimizations ===
1. الموديل بيتحمل مرة واحدة بس (singleton) وقت ما السيرفر يشتغل،
   مش في كل request — تحميل الموديل نفسه بياخد وقت، فلو عملناه
   كل مرة هنبوظ السرعة تمامًا.
2. beam_size=5 توازن كويس بين السرعة والدقة. لو عايزة أسرع من كده
   ممكن تنزليها لـ 1 (greedy) على حساب دقة بسيطة.
3. vad_filter=True: بيشيل فترات الصمت من الصوت قبل ما يبعتها للموديل،
   فبيقلل وقت المعالجة خصوصًا في فيديوهات فيها سكوت كتير.
4. language="ar" محدد يدويًا: من غيرها الموديل بيعمل خطوة إضافية
   لاكتشاف اللغة، وده وقت زيادة إحنا مش محتاجينه لأننا عارفين
   إن الصوت عربي أصلًا.
"""
from faster_whisper import WhisperModel
import time
from functools import lru_cache
from app.config import get_settings


@lru_cache
def get_whisper_model() -> WhisperModel:
    """
    singleton pattern: الموديل بيتحمل مرة واحدة بس في ذاكرة السيرفر
    ويتشارك بين كل الـ requests. lru_cache بتضمن ده تلقائيًا.
    """
    settings = get_settings()
    return WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def transcribe_audio(audio_path: str) -> tuple[str, float]:
    """
    بياخد مسار ملف صوت ويرجع النص العربي المستخرج منه.

    Returns:
        (النص الكامل, الوقت المستغرق بالثانية)
    """
    model = get_whisper_model()

    start = time.time()
    segments, info = model.transcribe(
        audio_path,
        language="ar",          # تحديد يدوي = توفير خطوة اكتشاف اللغة
        beam_size=5,
        vad_filter=True,        # يشيل الصمت = معالجة أسرع
        vad_parameters={"min_silence_duration_ms": 500},
    )

    # segments بيرجع كـ generator، فلازم نلف عليه عشان يتنفذ فعليًا
    full_text = " ".join(segment.text.strip() for segment in segments)
    elapsed = time.time() - start

    return full_text.strip(), elapsed
