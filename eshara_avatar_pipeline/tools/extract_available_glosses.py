"""
extract_available_glosses.py
------------------------------
بيقرأ كل ملفات .sigml من مجلد algerianSignLanguage-avatar/data/sigml
ويستخرج أسماءها (بدون الامتداد) كقائمة JSON، عشان الـ gloss_service
يستخدمها كمصدر الحقيقة الوحيد لأي كلمة "متاحة فعليًا للتشغيل".

=== ليه نحتاج نشغل السكريبت ده تاني؟ ===
لو فريق الـ avatar ضاف كلمات جديدة (ملفات sigml جديدة) في المشروع
الأصلي، لازم نعيد توليد data/available_glosses.json عندنا عشان
الـ API يعرف بالكلمات الجديدة دي.

الاستخدام:
    python tools/extract_available_glosses.py \
        --sigml-dir /path/to/algerianSignLanguage-avatar/data/sigml \
        --output data/available_glosses.json
"""
import argparse
import json
import os


def extract_glosses(sigml_dir: str) -> list[str]:
    if not os.path.isdir(sigml_dir):
        raise FileNotFoundError(f"مجلد الـ sigml مش موجود: {sigml_dir}")

    glosses = []
    for filename in sorted(os.listdir(sigml_dir)):
        if filename.endswith(".sigml"):
            gloss_name = filename[: -len(".sigml")]
            glosses.append(gloss_name)
    return glosses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sigml-dir",
        required=True,
        help="مسار مجلد sigml من مشروع algerianSignLanguage-avatar (عادة data/sigml)",
    )
    parser.add_argument(
        "--output",
        default="data/available_glosses.json",
        help="مسار ملف الإخراج JSON",
    )
    args = parser.parse_args()

    glosses = extract_glosses(args.sigml_dir)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(glosses, f, ensure_ascii=False, indent=2)

    print(f"✅ تم استخراج {len(glosses)} gloss وحفظها في {args.output}")


if __name__ == "__main__":
    main()
