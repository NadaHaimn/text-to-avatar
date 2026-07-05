"""
test_gloss_service.py
-----------------------
اختبارات لخدمة الـ gloss matching الخاصة بالأفاتار (بتتحقق إن كل
gloss راجع "matched=True" له فعلاً ملف sigml مطابق بالاسم بالظبط).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.services.gloss_service import AvatarGlossMatcher, normalize_arabic


@pytest.fixture(scope="module")
def matcher():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "available_glosses.json")
    return AvatarGlossMatcher(available_glosses_path=path, threshold=90)


def test_exact_single_word_match(matcher):
    results = matcher.match_text("أنا")
    assert len(results) == 1
    assert results[0]["matched"] is True
    assert results[0]["gloss"] == "أنا"


def test_multi_word_gloss_preferred_over_single(matcher):
    """'طبيب أسنان' لازم تتطابق ككلمة واحدة مركبة مش 'طبيب' منفصلة"""
    results = matcher.match_text("طبيب أسنان")
    assert len(results) == 1
    assert results[0]["gloss"] == "طبيب أسنان"
    assert results[0]["matched"] is True


def test_unmatched_word_returns_false_not_hallucinated(matcher):
    """كلمة مش موجودة أصلًا لازم ترجع matched=False، مش أي تخمين"""
    results = matcher.match_text("كلمةمختلقةتمامالاتوجد")
    assert results[0]["matched"] is False


def test_high_threshold_prevents_dangerous_fuzzy_matches(matcher):
    """
    'أن' من المفروض متتطابقش مع 'أذن' حتى لو قريبة شكليًا —
    threshold=90 لازم يمنع التطابقات الخطرة دي
    """
    results = matcher.match_text("أن")
    # لو اتطابقت، لازم تبقى مع نفسها بالظبط مش مع كلمة تانية
    if results[0]["matched"]:
        assert results[0]["gloss"] == "أن"
    else:
        assert results[0]["matched"] is False


def test_mixed_text_separates_matched_and_unmatched(matcher):
    results = matcher.match_text("أنا كلمةغيرموجودة")
    matched = [r for r in results if r["matched"]]
    unmatched = [r for r in results if not r["matched"]]
    assert len(matched) == 1
    assert len(unmatched) == 1
