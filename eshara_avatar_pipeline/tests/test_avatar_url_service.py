"""
test_avatar_url_service.py
----------------------------
اختبارات لبناء الرابط النهائي — أهم جزء: التأكد إن الكلمات اللي
فيها مسافات (multi-word glosses) بتتشفر صح وبتترجع صح.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from urllib.parse import unquote, urlparse, parse_qs


def test_url_roundtrip_preserves_multiword_glosses(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("AVATAR_PLAYER_BASE_URL", "http://localhost:8081/index.html")

    from app.config import get_settings
    get_settings.cache_clear()
    from app.services.avatar_url_service import build_avatar_player_url

    url = build_avatar_player_url(["أنا", "طبيب أسنان"])
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    words = [unquote(w) for w in qs["words"][0].split(",")]

    assert words == ["أنا", "طبيب أسنان"]


def test_empty_gloss_list_still_produces_valid_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("AVATAR_PLAYER_BASE_URL", "http://localhost:8081/index.html")

    from app.config import get_settings
    get_settings.cache_clear()
    from app.services.avatar_url_service import build_avatar_player_url

    url = build_avatar_player_url([])
    assert url.startswith("http://localhost:8081/index.html?words=")
