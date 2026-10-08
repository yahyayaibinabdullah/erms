#!/usr/bin/env python3
"""Synchronize privilege UI-message definitions and Arabic draft translations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from frontend.webui.authorization_ui import privilege_help_text


ROOT = Path(__file__).resolve().parents[3]
ENGLISH_PATH = ROOT / "frontend/webui/i18n/messages.en.json"
ARABIC_PATH = ROOT / "frontend/webui/i18n/messages.ar.generated.json"

CATEGORY_ARABIC = {
    "administration": "إدارة النظام",
    "aggregation": "الملفات",
    "record": "الوثائق",
    "component": "المكونات الرقمية",
    "exceptional": "العمليات الاستثنائية",
    "hold": "أوامر التحفظ",
    "other": "صلاحيات أخرى",
}

NAME_ARABIC = {
    'relationships.administer': 'إدارة أنواع العلاقات',
    'relationships.link': 'ربط الوثائق والملفات',
    "aggregation.acl.manage": "إدارة قائمة التحكم في وصول الملفات",
    "aggregation.close": "إغلاق ملف",
    "aggregation.create_child": "إنشاء ملف فرعي",
    "aggregation.create_root": "إنشاء ملف رئيسي",
    "aggregation.delete": "حذف ملف",
    "aggregation.location.change": "تغيير موقع ملف",
    "aggregation.modify": "تعديل ملف",
    "aggregation.move": "نقل ملف",
    "aggregation.reclassify": "إعادة تصنيف ملف",
    "aggregation.reopen": "إعادة فتح ملف",
    "aggregation.review_date.change": "تغيير تاريخ مراجعة ملف",
    "aggregation.security_level.change": "تغيير درجة سرية ملف",
    "aggregation.view": "عرض ملف",
    "aggregation.vital_status.change": "تغيير الحالة الحيوية لملف",
    "audit.view": "عرض سجل التدقيق",
    "authorization.administer": "إدارة التفويض",
    "authorization.explain": "تفسير قرارات التفويض",
    "authorization.recovery": "استعادة صلاحيات التفويض",
    "classification_scheme.modify_metadata": "تعديل البيانات الوصفية لنظام التصنيف",
    "classification.modify_metadata": "تعديل البيانات الوصفية للتصنيف",
    "classifications.administer": "إدارة التصنيفات",
    "closure.correct_record_placement": "تصحيح موضع وثيقة داخل ملف مغلق",
    "content.index.execute": "تنفيذ فهرسة المحتوى",
    "holds.administer": "إدارة تعليق قنوني",
    "holds.held_items.manage_all": "إدارة جميع عناصر تعليق قنوني",
    "identity.sessions.administer": "إدارة جلسات تسجيل الدخول",
    "identity.text_indexers.administer": "إدارة مفهرسات النصوص",
    "identity.users.administer": "إدارة المستخدمين",
    "localization.administer": "إدارة اللغات والترجمات",
    "org_unit.modify_metadata": "تعديل البيانات الوصفية للوحدة التنظيمية",
    "organization.administer": "إدارة الهيكل التنظيمي",
    "organization.browse": "استعراض الهيكل التنظيمي",
    "organization.ownership.correct": "تصحيح الملكية التنظيمية",
    "profile.modify_metadata": "تعديل البيانات الوصفية لملف الصلاحيات",
    "record.acl.manage": "إدارة قائمة التحكم في وصول الوثيقة",
    "record.component.add": "إضافة مكون رقمي إلى وثيقة",
    "record.component.download": "تنزيل مكون رقمي لوثيقة",
    "record.component.print": "طباعة مكون رقمي لوثيقة",
    "record.component.reindex": "إعادة فهرسة مكون رقمي لوثيقة",
    "record.component.remove": "إزالة مكون رقمي من وثيقة",
    "record.component.reorder": "إعادة ترتيب مكونات الوثيقة",
    "record.component.replace": "استبدال مكون رقمي لوثيقة",
    "record.component.share": "مشاركة مكون رقمي لوثيقة",
    "record.component.view": "عرض مكون رقمي لوثيقة",
    "record.create": "إنشاء وثيقة",
    "record.delete": "حذف وثيقة",
    "record.modify": "تعديل وثيقة",
    "record.move": "نقل وثيقة",
    "record.review_date.change": "تغيير تاريخ مراجعة وثيقة",
    "record.security_level.change": "تغيير درجة سرية وثيقة",
    "record.view": "عرض وثيقة",
    "record.vital_status.change": "تغيير الحالة الحيوية لوثيقة",
    "role.modify_metadata": "تعديل البيانات الوصفية للدور",
    "search.query.debug": "تشخيص استعلام البحث",
    "search.saved_search.administer": "إدارة عمليات البحث المحفوظة",
    "search.saved_search.delete": "حذف عمليات البحث المحفوظة",
    "search.saved_search.save": "حفظ عمليات البحث",
    "security.resource.downgrade": "خفض درجة سرية المورد",
    "security_level.modify_metadata": "تعديل البيانات الوصفية لدرجة السرية",
    "security_levels.administer": "إدارة درجات السرية",
    "user.modify_metadata": "تعديل البيانات الوصفية للمستخدم",
}

DESCRIPTION_ARABIC = {
    'relationships.administer': 'إدارة قائمتي أنواع العلاقات بين الملفات وبين الوثائق.',
    'relationships.link': 'إنشاء روابط مسماة بين الموارد التي يمكنك عرضها وإزالتها.',
    "aggregation.move": "تتيح نقل ملف إلى الملف الحاوي الآخر المسموح به.",
    "audit.view": "تتيح عرض مسار التتبع للنظام وأحداث الأمن والأعمال المسجّلة فيه.",
    "classifications.administer": "تتيح إنشاء نظم التصنيف والتصنيفات ونشرها وتحديثها وتعطيلها وإدارتها.",
    "holds.administer": "تتيح إنشاء حالات تعليق قنوني وتحديثها وحذفها وإدارة مالكيها والمساهمين فيها.",
    "holds.held_items.manage_all": "تتيح إضافة العناصر إلى أي تعليق قنوني أو إزالتها منه.",
    "organization.ownership.correct": "تتيح تصحيح مالك ملف رئيسي أُسند بالخطأ وتطبيق التصحيح على محتوياته.",
    "record.component.reorder": "تتيح تغيير ترتيب عرض المكوّنات الرقمية المرفقة بوثيقة.",
    "record.component.replace": "تتيح استبدال المكوّن الرقمي مع حفظ العملية في مسار التتبع.",
    "record.create": "تتيح إنشاء وثيقة داخل ملف تسمح قائمة التحكم في الوصول الخاصة به بذلك.",
    "record.move": "تتيح نقل وثيقة إلى ملف آخر مسموح به.",
    "security_levels.administer": "تتيح إنشاء درجات السرية المستخدمة للأدوار والملفات والوثائق وصيانتها.",
}


def definition(key: str, group: str, text: str, meaning: str, role: str) -> dict:
    return {
        "message_key": key,
        "context_group": group,
        "default_text": text,
        "semantic_meaning": meaning,
        "common_locations": ["Role details", "Profile privilege editor"],
        "translator_guidance": (
            "Translate the user-facing privilege catalogue text. Keep privilege codes unchanged."
        ),
        "grammatical_role": role,
        "parameter_schema": {},
        "rendered_example": text,
        "is_html": False,
    }


def arabic_item(key: str, text: str) -> dict:
    return {"message_key": key, "translated_text": text, "quality_flags": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url is required when DATABASE_URL is not set")

    with psycopg.connect(args.database_url, row_factory=dict_row) as connection:
        privileges = connection.execute(
            "SELECT code,name,description,category FROM privileges ORDER BY code COLLATE \"C\""
        ).fetchall()

    missing = sorted({row["code"] for row in privileges} - NAME_ARABIC.keys())
    extra = sorted(NAME_ARABIC.keys() - {row["code"] for row in privileges})
    if missing or extra:
        raise SystemExit(f"Arabic privilege-name mapping mismatch; missing={missing}, extra={extra}")

    english = json.loads(ENGLISH_PATH.read_text(encoding="utf-8"))
    by_key = {item["message_key"]: item for item in english}
    arabic = json.loads(ARABIC_PATH.read_text(encoding="utf-8"))
    arabic_by_key = {item["message_key"]: item for item in arabic["items"]}

    categories = sorted({str(row["category"] or "other") for row in privileges} | {"other"})
    for category in categories:
        key = f"privilege.category.{category}"
        english_text = category.replace("_", " ").title()
        by_key[key] = definition(
            key,
            "privilege.category",
            english_text,
            f"Heading for the {english_text} group in the privilege catalogue.",
            "heading",
        )
        arabic_by_key.setdefault(key, arabic_item(key, CATEGORY_ARABIC[category]))

    for privilege in privileges:
        code = privilege["code"]
        english_name = privilege["name"]
        english_description = privilege_help_text(code, privilege.get("description"))
        arabic_name = NAME_ARABIC[code]
        translation_code = {
            "search.saved_search.administer": "search.saved_search.administrator",
        }.get(code, code)
        name_key = f"privilege.{translation_code}.name"
        description_key = f"privilege.{translation_code}.description"
        group = f"privilege.{translation_code}"
        by_key[name_key] = definition(
            name_key,
            group,
            english_name,
            f"Friendly name of the immutable system privilege {code}.",
            "label",
        )
        by_key[description_key] = definition(
            description_key,
            group,
            english_description,
            f"Accessible explanation of what the immutable system privilege {code} permits.",
            "guidance",
        )
        arabic_by_key.setdefault(name_key, arabic_item(name_key, arabic_name))
        arabic_by_key.setdefault(description_key, arabic_item(
            description_key,
            DESCRIPTION_ARABIC.get(
                code,
                f"تتيح هذه الصلاحية للمستخدم {arabic_name} وفق ضوابط التفويض والسياسات المعتمدة.",
            ),
        ))

    ENGLISH_PATH.write_text(
        json.dumps(sorted(by_key.values(), key=lambda item: item["message_key"]), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    arabic["items"] = sorted(arabic_by_key.values(), key=lambda item: item["message_key"])
    arabic["catalogue_sha256"] = hashlib.sha256(ENGLISH_PATH.read_bytes()).hexdigest()
    arabic["batch_id"] = f"generated-privilege-catalogue-ar-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    arabic["generated_at"] = datetime.now().astimezone().isoformat()
    ARABIC_PATH.write_text(
        json.dumps(arabic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"privileges": len(privileges), "categories": len(categories)}))


if __name__ == "__main__":
    main()
