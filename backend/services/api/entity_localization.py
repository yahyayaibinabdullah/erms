from __future__ import annotations

from typing import Any

from fastapi import Request
from psycopg import Connection


def preferred_language(connection: Connection, request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    return preferred_language_for_user(connection, principal.user_id if principal else None)


def preferred_language_for_user(connection: Connection, user_id: int | None) -> str:
    if user_id is not None:
        row = connection.execute(
            """SELECT language.language_tag
                 FROM user_preferences preference
                 JOIN supported_languages language USING(language_tag)
                WHERE preference.user_id=%s AND language.is_enabled""",
            (user_id,),
        ).fetchone()
        if row is not None:
            return row["language_tag"]
    row = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE is_enabled ORDER BY is_default DESC,id LIMIT 1"
    ).fetchone()
    return row["language_tag"] if row else "en"


def localized_projection(
    row: dict[str, Any], language_tag: str, primary_field: str,
) -> dict[str, Any]:
    translations = row.get("translations") or {}
    candidates = [language_tag]
    if "-" in language_tag:
        candidates.append(language_tag.split("-", 1)[0])
    selected_language = next((tag for tag in candidates if translations.get(tag)), None)
    translated = translations.get(selected_language, {}) if selected_language else {}
    return {
        "language_tag": selected_language or language_tag,
        primary_field: translated.get(primary_field) or row.get(primary_field),
        "description": translated.get("description") or row.get("description"),
        "used_canonical_fallback": not bool(selected_language),
    }


def localize_rows(
    rows: list[dict[str, Any]], language_tag: str, primary_field: str,
) -> list[dict[str, Any]]:
    for row in rows:
        row["localized"] = localized_projection(row, language_tag, primary_field)
    return rows


def localize_search_result(
    result: dict[str, Any], language_tag: str, primary_field: str,
) -> dict[str, Any]:
    """Attach the same preferred-language projection used by list endpoints.

    Search endpoints are increasingly used for paginated administration
    listings. Keeping localization at this API boundary prevents those faster
    endpoints from silently reverting entity labels to canonical English.
    """
    result["items"] = localize_rows(
        list(result.get("items") or []), language_tag, primary_field,
    )
    return result


def sort_localized_rows(rows: list[dict[str, Any]], primary_field: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (
        str((row.get("localized") or {}).get(primary_field) or row.get(primary_field) or "").casefold(),
        str(row.get("code") or "").casefold(),
        row.get("id", 0),
    ))


def localized_labels(c, key):
    return {
        row["language_tag"]: row["text"]
        for row in c.execute(
            """SELECT l.language_tag,COALESCE(t.published_text,b.published_text,d.default_text) AS text
        FROM supported_languages l CROSS JOIN ui_message_definitions d
        LEFT JOIN ui_message_translations t ON t.message_key=d.message_key
          AND t.language_tag=l.language_tag AND t.published_text IS NOT NULL AND NOT t.needs_review
        LEFT JOIN ui_message_translations b ON b.message_key=d.message_key
          AND b.language_tag=split_part(l.language_tag,'-',1) AND b.published_text IS NOT NULL AND NOT b.needs_review
        WHERE l.is_enabled AND d.message_key=%s""",
            (key,),
        )
    }
