"""
avatar_url_service.py
----------------------
بيبني الرابط النهائي اللي الفلاتر هيفتحوه في WebView/iframe.

الشكل النهائي:
    {avatar_player_base_url}?words=كلمة1,كلمة2,كلمة3

الصفحة (index.html المعدّل — شوفي avatar_patch/) بتقرأ query param
"words" وتشغل الأفاتار تلقائيًا لما تفتح.

=== ليه encodeURIComponent لكل كلمة على حدة؟ ===
عشان لو فيه كلمة فيها مسافة (زي "طبيب أسنان")، لازم تتشفر صح جوه
الـ query string من غير ما تتلخبط مع الـ comma separator اللي بنستخدمه
لفصل الكلمات عن بعض.
"""
from urllib.parse import quote
from app.config import get_settings


def build_avatar_player_url(matched_glosses: list[str], avatar: str = "marc") -> str:
    """
    بتاخد قائمة أسماء gloss (بالترتيب اللي هيتشغلوا بيه) وترجع
    الرابط الكامل الجاهز للفتح مباشرة.
    """
    settings = get_settings()
    encoded_words = ",".join(quote(g) for g in matched_glosses)
    separator = "&" if "?" in settings.avatar_player_base_url else "?"
    return f"{settings.avatar_player_base_url}{separator}words={encoded_words}&avatar={quote(avatar)}"
