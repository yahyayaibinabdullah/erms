import json
import os
from pathlib import Path
import re

import psycopg
import pytest

from backend.services.api.localization import ARABIC_TERMINOLOGY, synchronize_generated_arabic_drafts


MESSAGE_KEY = "preferences.validation.language.unsupported"


def test_generated_arabic_artifact_is_complete_contextual_and_placeholder_safe():
    root = Path(__file__).parents[4]
    definitions = json.loads((root / "frontend/webui/i18n/messages.en.json").read_text())
    artifact = json.loads((root / "frontend/webui/i18n/messages.ar.generated.json").read_text())
    candidates = artifact["items"]
    definition_keys = [item["message_key"] for item in definitions]
    assert definition_keys == sorted(definition_keys)
    assert artifact["generator"] == "Wathiq Translation Administration"
    assert artifact["model"] == "database-reviewed-translations"
    assert artifact["prompt_version"] == "manual-admin-export-v1"
    assert [item["message_key"] for item in candidates] == definition_keys
    assert len({item["message_key"] for item in candidates}) == len(definitions)

    placeholder = re.compile(r"\{[a-z][a-z0-9_]*\}")
    for definition, candidate in zip(definitions, candidates, strict=True):
        assert candidate["translated_text"].strip()
        assert set(placeholder.findall(candidate["translated_text"])) == set(
            placeholder.findall(definition["default_text"])
        )
        assert isinstance(candidate["quality_flags"], list)
        if candidate["quality_flags"]:
            assert candidate.get("origin") == "generated"
            assert candidate.get("status") == "draft"
            assert not candidate.get("provenance")
            assert all(isinstance(flag,str) and flag for flag in candidate["quality_flags"])

    by_key = {item["message_key"]: item["translated_text"] for item in candidates}
    assert by_key["common.error.bad_request"] == (
        "تعذر إكمال الطلب. راجع المعلومات وحاول مرة أخرى."
    )
    assert by_key["authorization.error.insufficient_clearance"] == (
        "لا تمنحك أدوارك النشطة درجة السرية الكافية."
    )
    assert by_key["navigation.item.records"] == "الوثائق"
    assert by_key["navigation.item.aggregations"] == "الملفات"
    assert by_key["navigation.item.audit_trail"] == "مسار التتبع"


def test_approved_arabic_terminology_matches_the_specification():
    specification = (Path(__file__).parents[4] / "specs/internationalization-and-user-preferences.md").read_text()
    section = specification.split("### 21.1 Approved Arabic terminology reference", 1)[1]
    table = section.split("These mappings establish", 1)[0]
    expected = {}
    for line in table.splitlines():
        if not line.startswith("| ") or line.startswith("| English term") or line.startswith("| ---"):
            continue
        english, arabic = (part.strip() for part in line.strip("|").split("|", 1))
        expected[english] = arabic
    assert expected
    assert ARABIC_TERMINOLOGY == expected


def test_api_startup_does_not_seed_generated_arabic_drafts():
    source = (Path(__file__).parents[1] / "main.py").read_text()
    assert "synchronize_generated_arabic_drafts" not in source


def test_checked_in_arabic_generation_artifact_seeds_only_untouched_source_copies(client):
    protected_key = MESSAGE_KEY
    corrected_key = "navigation.item.records"
    item = _translation(client)
    manual = client.put(
        f"/api/v1/admin/i18n/messages/{protected_key}/translations/ar",
        headers={"If-Match": str(item["translation_version"]), "X-Change-Reason": "Protect manual Arabic"},
        json={"translated_text": "هذه صياغة يدوية {language}.", "origin": "manual", "reviewed": True},
    )
    assert manual.status_code == 200

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        administrator_id = connection.execute(
            "SELECT id FROM users WHERE email='admin@test.invalid'"
        ).fetchone()[0]
        connection.execute(
            "SELECT set_config('app.change_reason','Prepare superseded generated translation',true)"
        )
        connection.execute(
            """UPDATE ui_message_translations SET
                   translated_text='السجلات',published_text='السجلات',
                   status='published',origin='generated',
                   reviewed_by_user_id=%s,date_reviewed=CURRENT_TIMESTAMP,
                   published_by_user_id=%s,date_published=CURRENT_TIMESTAMP
                 WHERE message_key=%s AND language_tag='ar'""",
            (administrator_id, administrator_id, corrected_key),
        )

    result = synchronize_generated_arabic_drafts()
    manifest = json.loads((Path(__file__).parents[4] / "frontend/webui/i18n/messages.en.json").read_text())
    assert result == {
        "stored": len(manifest) - 2,
        "corrected": 1,
        "protected": 1,
        "failed": 0,
        "awaiting_generation": 0,
    }
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        artifact = json.loads((Path(__file__).parents[4] / "frontend/webui/i18n/messages.ar.generated.json").read_text())
        expected_origins = {item["message_key"]: "imported" if isinstance(item.get("provenance"), dict) else "generated" for item in artifact["items"]}
        seeded_rows = connection.execute(
            "SELECT message_key,origin,status,reviewed_by_user_id,generation_metadata FROM ui_message_translations WHERE language_tag='ar' AND message_key<>%s", (protected_key,),
        ).fetchall()
        assert len(seeded_rows) == len(manifest) - 1
        provenance = {item["message_key"]: item.get("provenance") for item in artifact["items"]}
        for key, origin, status, reviewer, metadata in seeded_rows:
            assert origin == expected_origins[key] and status == "draft" and reviewer is None
            if provenance[key]:
                assert metadata["export_provenance"] == provenance[key]
        protected = connection.execute(
            "SELECT translated_text,origin,reviewed_by_user_id FROM ui_message_translations WHERE message_key=%s AND language_tag='ar'",
            (protected_key,),
        ).fetchone()
        corrected = connection.execute(
            """SELECT translated_text,status,origin,published_text,reviewed_by_user_id
                 FROM ui_message_translations
                WHERE message_key=%s AND language_tag='ar'""",
            (corrected_key,),
        ).fetchone()
    assert protected[0] == "هذه صياغة يدوية {language}."
    assert protected[1] == "manual"
    assert protected[2] is not None
    assert corrected == ("الوثائق", "draft", expected_origins[corrected_key], None, None)


def _translation(client):
    page = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "ar", "key": MESSAGE_KEY, "limit": 20, "offset": 0,
    })
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    return page.json()["items"][0]


def test_translation_administration_pages_complete_context_groups(client):
    first = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "ar", "limit": 1, "offset": 0,
    })
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["group_total"] > 1
    assert payload["total"] >= payload["group_total"]
    assert len({item["context_group"] for item in payload["items"]}) == 1
    first_group = payload["items"][0]["context_group"]

    second = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "ar", "limit": 1, "offset": 1,
    })
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert len({item["context_group"] for item in second_payload["items"]}) == 1
    assert second_payload["items"][0]["context_group"] != first_group


def test_catalogue_reports_fallback_keys_without_exposing_draft_metadata(client):
    catalogue = client.get("/api/v1/i18n/catalogues/ar")
    assert catalogue.status_code == 200
    payload = catalogue.json()
    assert MESSAGE_KEY in payload["fallback_keys"]
    assert payload["messages"][MESSAGE_KEY] == "The language {language} is not available."
    assert "origin" not in payload
    assert "status" not in payload


def test_checked_in_definitions_are_synchronized_with_source_copy_queue(client):
    manifest = json.loads((Path(__file__).parents[4] / "frontend/webui/i18n/messages.en.json").read_text())
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute("SELECT count(*) FROM ui_message_definitions").fetchone()[0] == len(manifest)
        assert connection.execute(
            "SELECT count(*) FROM ui_message_translations WHERE language_tag='ar' AND origin='source_copy' AND status='draft'"
        ).fetchone()[0] == len(manifest)


def test_english_source_catalogue_is_a_complete_published_baseline(client):
    page = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "en", "needs_attention": False, "limit": 200, "offset": 0,
    })
    assert page.status_code == 200, page.text
    payload = page.json()
    assert payload["total"] > 0
    assert all(item["translated_text"] == item["default_text"] for item in payload["items"])
    assert all(item["published_text"] == item["default_text"] for item in payload["items"])
    assert all(item["status"] == "published" for item in payload["items"])
    assert all(item["validity"] == "valid" for item in payload["items"])

    attention = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "en", "needs_attention": True, "limit": 20, "offset": 0,
    })
    assert attention.status_code == 200, attention.text
    assert attention.json()["total"] == 0


def test_translation_draft_publication_etag_and_published_value_preservation(client):
    item = _translation(client)
    blank = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(item["translation_version"]), "X-Change-Reason": "Test blank rejection"},
        json={"translated_text": "   ", "origin": "manual", "reviewed": False},
    )
    assert blank.status_code == 422
    assert blank.json()["detail"]["code"] == "blank_translation"

    saved = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(item["translation_version"]), "X-Change-Reason": "Provide reviewed Arabic wording"},
        json={"translated_text": "اللغة {language} غير متاحة.", "origin": "manual", "reviewed": True},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar/publish",
        headers={"If-Match": str(saved.json()["version"]), "X-Change-Reason": "Publish reviewed Arabic wording"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["catalogue_revision"] == 2

    catalogue = client.get("/api/v1/i18n/catalogues/ar")
    assert catalogue.status_code == 200
    assert catalogue.json()["messages"][MESSAGE_KEY] == "اللغة {language} غير متاحة."
    assert MESSAGE_KEY not in catalogue.json()["fallback_keys"]
    assert client.get(
        "/api/v1/i18n/catalogues/ar", headers={"If-None-Match": catalogue.headers["etag"]},
    ).status_code == 304

    draft = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(published.json()["version"]), "X-Change-Reason": "Prepare a later wording"},
        json={"translated_text": "صياغة جديدة {language}.", "origin": "manual", "reviewed": False},
    )
    assert draft.status_code == 200
    unchanged = client.get("/api/v1/i18n/catalogues/ar")
    assert unchanged.json()["revision"] == 2
    assert unchanged.json()["messages"][MESSAGE_KEY] == "اللغة {language} غير متاحة."

    stale = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(published.json()["version"]), "X-Change-Reason": "Stale competing edit"},
        json={"translated_text": "تعديل متعارض {language}.", "origin": "manual", "reviewed": False},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["translated_text"] == "صياغة جديدة {language}."


def test_filters_publication_review_and_new_language_source_copies(client):
    item = _translation(client)
    generated = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(item["translation_version"]), "X-Change-Reason": "Store generated candidate"},
        json={"translated_text": "اللغة {language} غير متاحة.", "origin": "generated", "reviewed": False, "generation_metadata": {"model": "test"}},
    )
    assert generated.status_code == 200
    published = client.post(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar/publish",
        headers={"If-Match": str(generated.json()["version"]), "X-Change-Reason": "Review and publish generated wording"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["reviewed_by_user_id"] is not None
    assert published.json()["date_reviewed"] is not None

    filtered = client.get("/api/v1/admin/i18n/messages", params={
        "language_tag": "ar", "key": "preferences.validation", "translated_text": "اللغة",
        "semantic_meaning": "requested language", "status": "published", "origin": "generated",
        "limit": 10, "offset": 0,
    })
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1

    created = client.post(
        "/api/v1/admin/i18n/languages",
        headers={"X-Change-Reason": "Add French translation queue"},
        json={"language_tag":"fr","english_name":"French","native_name":"Français","direction":"ltr","is_enabled":True,"is_default":False,"formatting_config":{"locale":"fr"}},
    )
    assert created.status_code == 201, created.text
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        definitions = connection.execute("SELECT count(*) FROM ui_message_definitions").fetchone()[0]
        source_copies = connection.execute("SELECT count(*) FROM ui_message_translations WHERE language_tag='fr' AND origin='source_copy'").fetchone()[0]
    assert source_copies == definitions
    preview = client.get(
        "/api/v1/admin/i18n/translations/fr/bulk-publication-preview",
        params={"context_group": "preferences"},
    )
    assert preview.status_code == 200, preview.text
    selection = preview.json()
    assert selection["count"] == 0
    assert selection["source_copy_excluded"] > 0
    assert selection["items"] == []
    assert selection["invalid"] == []
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        source_copy = connection.execute(
            """SELECT translation.message_key,translation.version,translation.translated_text
                 FROM ui_message_translations translation
                 JOIN ui_message_definitions definition USING(message_key)
                WHERE translation.language_tag='fr'
                  AND translation.origin='source_copy'
                  AND definition.context_group='preferences'
                ORDER BY translation.message_key LIMIT 1"""
        ).fetchone()
    assert source_copy is not None

    source_copy_bulk_publication = client.post(
        "/api/v1/admin/i18n/translations/fr/bulk-review-publish",
        headers={"X-Change-Reason": "Attempt to publish an untouched fallback"},
        json={"items": [{"message_key": source_copy[0], "version": source_copy[1]}]},
    )
    assert source_copy_bulk_publication.status_code == 422
    assert source_copy_bulk_publication.json()["detail"]["parameters"]["invalid"] == [
        {"message_key": source_copy[0], "code": "source_copy_not_publishable"}
    ]

    source_copy_publication = client.post(
        f"/api/v1/admin/i18n/messages/{source_copy[0]}/translations/fr/publish",
        headers={
            "If-Match": str(source_copy[1]),
            "X-Change-Reason": "Attempt to publish an untouched fallback",
        },
    )
    assert source_copy_publication.status_code == 422
    assert source_copy_publication.json()["detail"]["code"] == "source_copy_not_publishable"

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "SELECT set_config('app.change_reason','Attempt direct source-copy publication',true)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """UPDATE ui_message_translations
                          SET status='published',published_text=translated_text
                        WHERE language_tag='fr' AND message_key=%s""",
                    (source_copy[0],),
                )

    deliberate_same_wording = client.put(
        f"/api/v1/admin/i18n/messages/{source_copy[0]}/translations/fr",
        headers={
            "If-Match": str(source_copy[1]),
            "X-Change-Reason": "Deliberately retain the English wording",
        },
        json={
            "translated_text": source_copy[2],
            "origin": "manual",
            "reviewed": False,
        },
    )
    assert deliberate_same_wording.status_code == 200, deliberate_same_wording.text
    deliberate_publication = client.post(
        f"/api/v1/admin/i18n/messages/{source_copy[0]}/translations/fr/publish",
        headers={
            "If-Match": str(deliberate_same_wording.json()["version"]),
            "X-Change-Reason": "Publish deliberately retained wording",
        },
    )
    assert deliberate_publication.status_code == 200, deliberate_publication.text
    assert deliberate_publication.json()["origin"] == "manual"


def test_bulk_generated_review_publication_is_atomic_audited_and_revision_bounded(client):
    seeded = synchronize_generated_arabic_drafts()
    assert seeded["failed"] == 0
    preview = client.get(
        "/api/v1/admin/i18n/translations/ar/bulk-publication-preview",
        params={"context_group": "preferences"},
    )
    assert preview.status_code == 200, preview.text
    selection = preview.json()
    assert selection["count"] > 0
    assert selection["invalid"] == []

    published = client.post(
        "/api/v1/admin/i18n/translations/ar/bulk-review-publish",
        headers={"X-Change-Reason": "Approve generated preference validation translations", "X-Event-Source": "web_ui"},
        json={"items": selection["items"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["published"] == selection["count"]
    assert published.json()["catalogue_revision"] == 2
    keys = [item["message_key"] for item in selection["items"]]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        rows = connection.execute(
            """SELECT status,origin,reviewed_by_user_id,published_by_user_id,message_key
                 FROM ui_message_translations WHERE language_tag='ar' AND message_key=ANY(%s)""",
            (keys,),
        ).fetchall()
        events = connection.execute(
            """SELECT count(*) FROM event_history
                 WHERE entity_type='ui_message_translation'
                   AND source='web_ui' AND reason=%s""",
            ("Approve generated preference validation translations",),
        ).fetchone()[0]
    artifact = json.loads((Path(__file__).parents[4] / "frontend/webui/i18n/messages.ar.generated.json").read_text())
    expected_origins = {item["message_key"]: "imported" if isinstance(item.get("provenance"), dict) else "generated" for item in artifact["items"]}
    assert all(row[0] == "published" and row[1] == expected_origins[row[4]] for row in rows)
    assert all(row[2] is not None and row[3] is not None for row in rows)
    assert events == selection["count"]

    stale_preview = client.get(
        "/api/v1/admin/i18n/translations/ar/bulk-publication-preview",
        params={"context_group": "translation_inspector.value"},
    ).json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "SELECT set_config('app.change_reason','Simulate concurrent translation edit',true)"
        )
        connection.execute(
            "UPDATE ui_message_translations SET translated_text=translated_text WHERE language_tag='ar' AND message_key=%s",
            (stale_preview["items"][0]["message_key"],),
        )
    blocked = client.post(
        "/api/v1/admin/i18n/translations/ar/bulk-review-publish",
        headers={"X-Change-Reason": "Attempt stale bulk publication"},
        json={"items": stale_preview["items"]},
    )
    assert blocked.status_code == 409
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ui_message_translations WHERE language_tag='ar' AND status='published' AND message_key=ANY(%s)",
            ([item["message_key"] for item in stale_preview["items"]],),
        ).fetchone()[0] == 0


def test_english_source_catalogue_is_exportable_without_publication(client):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "SELECT set_config('app.change_reason','Prepare English source catalogue',true)"
        )
        connection.execute(
            """INSERT INTO ui_message_translations(
                   message_key,language_tag,translated_text,status,origin
               )
               SELECT message_key,'en',default_text,'draft','source_copy'
                 FROM ui_message_definitions
                WHERE NOT is_deprecated
               ON CONFLICT(message_key,language_tag) DO NOTHING"""
        )
    preview = client.get("/api/v1/admin/i18n/translations/en/export-preview")
    assert preview.status_code == 200, preview.text
    summary = preview.json()
    assert summary["active_keys"] > 0
    assert summary["exportable_keys"] == summary["active_keys"]
    assert summary["missing_keys"] == []
    assert summary["invalid_keys"] == []

    exported = client.get("/api/v1/admin/i18n/translations/en/export")
    assert exported.status_code == 200, exported.text
    assert len(exported.json()["artifact"]["items"]) == summary["active_keys"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        published = connection.execute(
            """SELECT count(*) FROM ui_message_translations
                WHERE language_tag='en' AND published_text IS NOT NULL"""
        ).fetchone()[0]
    assert published == 0

    page = client.get(
        "/api/v1/admin/i18n/messages",
        params={"language_tag": "en", "key": MESSAGE_KEY, "limit": 20, "offset": 0},
    )
    assert page.status_code == 200, page.text
    source = page.json()["items"][0]
    source_publication = client.post(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/en/publish",
        headers={
            "If-Match": str(source["translation_version"]),
            "X-Change-Reason": "Publish the English source baseline",
        },
    )
    assert source_publication.status_code == 200, source_publication.text
    assert source_publication.json()["origin"] == "source_copy"

    english_edit = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/en",
        headers={
            "If-Match": str(source_publication.json()["version"]),
            "X-Change-Reason": "Apply an English editorial revision",
        },
        json={
            "translated_text": "The requested language {language} is unavailable.",
            "origin": "manual",
            "reviewed": False,
        },
    )
    assert english_edit.status_code == 200, english_edit.text
    edited_publication = client.post(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/en/publish",
        headers={
            "If-Match": str(english_edit.json()["version"]),
            "X-Change-Reason": "Publish the English editorial revision",
        },
    )
    assert edited_publication.status_code == 200, edited_publication.text
    assert edited_publication.json()["published_text"] == (
        "The requested language {language} is unavailable."
    )


@pytest.fixture
def round_trip_catalogue(client):
    """A controlled active catalogue for artifact mechanics, independent of drafts.

    New product translations can legitimately require review. Keep their flags
    intact; this test exports only four established fixture definitions and
    restores the original active catalogue after exercising the round trip.
    """
    keys={MESSAGE_KEY,"common.error.bad_request","navigation.item.records","navigation.item.dashboard"}
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        prior=c.execute("SELECT message_key,is_deprecated FROM ui_message_definitions").fetchall()
        c.execute("SELECT set_config('app.event_source','seeding',true),set_config('app.change_reason','Scope disposable artifact round-trip fixture',true)")
        c.execute("UPDATE ui_message_definitions SET is_deprecated=NOT(message_key=ANY(%s))",(sorted(keys),))
    try:
        yield keys
    finally:
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            c.execute("SELECT set_config('app.event_source','seeding',true),set_config('app.change_reason','Restore disposable artifact catalogue fixture',true)")
            c.cursor().executemany("UPDATE ui_message_definitions SET is_deprecated=%s WHERE message_key=%s",[(deprecated,key) for key,deprecated in prior])


def test_translation_artifact_export_import_round_trip_is_validated_and_non_destructive(client,round_trip_catalogue):
    seeded = synchronize_generated_arabic_drafts()
    # Candidates outside this controlled active catalogue remain unchanged.
    assert seeded["stored"] >= len(round_trip_catalogue)
    preview = client.get(
        "/api/v1/admin/i18n/translations/ar/bulk-publication-preview",
    ).json()
    assert preview["invalid"] == []
    published = client.post(
        "/api/v1/admin/i18n/translations/ar/bulk-review-publish",
        headers={"X-Change-Reason": "Approve Arabic catalogue for export"},
        json={"items": preview["items"]},
    )
    assert published.status_code == 200, published.text

    current = _translation(client)
    manual = client.put(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar",
        headers={"If-Match": str(current["translation_version"]), "X-Change-Reason": "Refine Arabic wording"},
        json={"translated_text": "هذه اللغة {language} غير متاحة.", "origin": "manual", "reviewed": True},
    )
    assert manual.status_code == 200, manual.text
    republished = client.post(
        f"/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar/publish",
        headers={"If-Match": str(manual.json()["version"]), "X-Change-Reason": "Publish refined Arabic wording"},
    )
    assert republished.status_code == 200, republished.text

    export_preview = client.get(
        "/api/v1/admin/i18n/translations/ar/export-preview",
    )
    assert export_preview.status_code == 200, export_preview.text
    assert export_preview.json()["complete"] is True
    assert export_preview.json()["exportable_keys"] == export_preview.json()["active_keys"]

    exported = client.get("/api/v1/admin/i18n/translations/ar/export")
    assert exported.status_code == 200, exported.text
    result = exported.json()
    artifact = result["artifact"]
    assert result["filename"] == "messages.ar.admin-export.json"
    assert artifact["artifact_type"] == "wathiq_translation_administration_export"
    assert artifact["language_metadata"]["english_name"] == "Arabic"
    assert artifact["language_metadata"]["native_name"] == "العربية"
    assert artifact["language_metadata"]["direction"] == "rtl"
    assert isinstance(artifact["language_metadata"]["formatting_config"], dict)
    root = Path(__file__).parents[4]
    manifest = json.loads((root / "frontend/webui/i18n/messages.en.json").read_text())
    checked_in = json.loads(
        (root / "frontend/webui/i18n/messages.ar.generated.json").read_text()
    )
    assert [item["message_key"] for item in artifact["items"]] == [
        item["message_key"] for item in manifest if item["message_key"] in round_trip_catalogue
    ]
    assert artifact["superseded_translations"] == checked_in[
        "superseded_translations"
    ]
    by_key = {item["message_key"]: item for item in artifact["items"]}
    assert by_key[MESSAGE_KEY]["translated_text"] == "هذه اللغة {language} غير متاحة."
    assert by_key[MESSAGE_KEY]["provenance"]["kind"] == "manual_admin_export"

    misordered_artifact = json.loads(json.dumps(artifact))
    misordered_artifact["items"][0], misordered_artifact["items"][1] = (
        misordered_artifact["items"][1], misordered_artifact["items"][0]
    )
    misordered_preview = client.post(
        "/api/v1/admin/i18n/translations/ar/import-preview",
        json={"artifact": misordered_artifact},
    )
    assert misordered_preview.status_code == 200, misordered_preview.text
    assert misordered_preview.json()["complete"] is False
    assert {item["code"] for item in misordered_preview.json()["invalid_keys"]} >= {
        "artifact_key_order_mismatch"
    }
    rejected_import = client.post(
        "/api/v1/admin/i18n/translations/ar/import",
        headers={"X-Change-Reason": "Reject noncanonical artifact order"},
        json={"artifact": misordered_artifact},
    )
    assert rejected_import.status_code == 422, rejected_import.text
    assert rejected_import.json()["detail"]["code"] == "translation_import_invalid"

    import_key = "navigation.item.dashboard"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("SELECT set_config('app.change_reason','Prepare import target',true)")
        connection.execute(
            """UPDATE ui_message_translations SET
                   translated_text=(SELECT default_text FROM ui_message_definitions WHERE message_key=%s),
                   published_text=NULL,status='draft',origin='source_copy',generation_metadata=NULL,
                   reviewed_by_user_id=NULL,date_reviewed=NULL,published_by_user_id=NULL,date_published=NULL
                 WHERE language_tag='ar' AND message_key=%s""",
            (import_key, import_key),
        )
    import_preview = client.post(
        "/api/v1/admin/i18n/translations/ar/import-preview", json={"artifact": artifact},
    )
    assert import_preview.status_code == 200, import_preview.text
    assert import_preview.json()["complete"] is True
    assert import_preview.json()["importable"] == 1
    imported = client.post(
        "/api/v1/admin/i18n/translations/ar/import",
        headers={"X-Change-Reason": "Import reviewed Arabic catalogue copy"},
        json={"artifact": artifact},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute(
            "SELECT translated_text,status,origin,date_reviewed,published_text FROM ui_message_translations WHERE language_tag='ar' AND message_key=%s",
            (import_key,),
        ).fetchone()
    assert row == (by_key[import_key]["translated_text"], "draft", "imported", None, None)
    reviewable = client.get(
        "/api/v1/admin/i18n/translations/ar/bulk-publication-preview",
        params={"context_group": "navigation"},
    ).json()
    assert import_key in {item["message_key"] for item in reviewable["items"]}

    new_language_artifact = json.loads(json.dumps(artifact))
    new_language_artifact["language_tag"] = "fr"
    new_language_artifact["language_metadata"] = {
        "english_name": "French",
        "native_name": "Français",
        "direction": "ltr",
        "formatting_config": {"locale": "fr"},
    }
    new_language_preview = client.post(
        "/api/v1/admin/i18n/translations/fr/import-preview",
        json={"artifact": new_language_artifact},
    )
    assert new_language_preview.status_code == 200, new_language_preview.text
    assert new_language_preview.json()["complete"] is True
    assert new_language_preview.json()["creates_language"] is True
    new_language_import = client.post(
        "/api/v1/admin/i18n/translations/fr/import",
        headers={"X-Change-Reason": "Import a new supported French language"},
        json={"artifact": new_language_artifact},
    )
    assert new_language_import.status_code == 200, new_language_import.text
    assert new_language_import.json()["created_language"] is True
    languages = client.get("/api/v1/admin/i18n/languages").json()
    assert any(
        language["language_tag"] == "fr"
        and language["native_name"] == "Français"
        for language in languages
    )


def test_catalogue_administration_requires_localization_privilege(client):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        user_id = connection.execute("INSERT INTO users(name,email) VALUES('Ordinary user','ordinary@test.invalid') RETURNING id").fetchone()[0]
        from backend.services.api.authentication import hash_password
        connection.execute("INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)",(user_id,hash_password("Temporary-Test-Password-123!")))
    login = client.post("/api/v1/auth/login",json={"email":"ordinary@test.invalid","password":"Temporary-Test-Password-123!"})
    assert login.status_code == 200
    try:
        assert client.get("/api/v1/admin/i18n/languages").status_code == 403
        assert client.get("/api/v1/admin/i18n/translations/ar/export-preview").status_code == 403
        assert client.get("/api/v1/admin/i18n/translations/ar/export").status_code == 403
        assert client.post("/api/v1/admin/i18n/translations/ar/import-preview", json={"artifact": {}}).status_code == 403
        assert client.post("/api/v1/admin/i18n/translations/ar/import", json={"artifact": {}}).status_code == 403
        assert client.get("/api/v1/i18n/catalogues/en").status_code == 200
    finally:
        client.cookies.clear()


def test_arabic_generation_input_batch_protection_and_report(client):
    generation_input = client.get(
        "/api/v1/admin/i18n/generation-input/ar", params={"limit": 5, "offset": 0},
    )
    assert generation_input.status_code == 200, generation_input.text
    payload = generation_input.json()
    assert payload["data_contract"] == "application_owned_source_context_and_placeholder_metadata_only"
    assert payload["approved_terminology"]["Record"] == "وثيقة"
    assert payload["items"]
    assert set(payload["items"][0]) == {
        "message_key", "context_group", "default_text", "semantic_meaning",
        "common_locations", "translator_guidance", "grammatical_role",
        "parameter_schema", "rendered_example",
    }

    item = _translation(client)
    generated = client.post(
        "/api/v1/admin/i18n/generated-drafts/ar",
        headers={"X-Change-Reason": "Seed best-effort Arabic draft"},
        json={
            "generator": "approved-test-generator",
            "model": "test-model",
            "model_version": "2026-09-26",
            "prompt_version": "test-prompt-v1",
            "specification_sha256": "1" * 64,
            "catalogue_sha256": "2" * 64,
            "terminology_sha256": "3" * 64,
            "batch_id": "test-batch-1",
            "generated_at": "2026-09-26T12:00:00Z",
            "items": [{
                "message_key": MESSAGE_KEY,
                "translated_text": "اللغة {language} غير متاحة.",
            }],
        },
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["stored"] == 1
    assert generated.json()["published"] == 0

    stored = _translation(client)
    assert stored["origin"] == "generated"
    assert stored["status"] == "draft"
    assert stored["reviewed_by_user_id"] is None
    assert stored["generation_metadata"] == {
        "generator": "approved-test-generator",
        "model": "test-model",
        "model_version": "2026-09-26",
        "prompt_version": "test-prompt-v1",
        "specification_sha256": "1" * 64,
        "catalogue_sha256": "2" * 64,
        "terminology_sha256": "3" * 64,
            "batch_id": "test-batch-1",
            "generated_at": "2026-09-26T12:00:00+00:00",
            "quality_flags": [],
        }

    protected = client.post(
        "/api/v1/admin/i18n/generated-drafts/ar",
        headers={"X-Change-Reason": "Attempt a second generated seed"},
        json={
            "generator": "approved-test-generator",
            "model": "test-model",
            "model_version": "2",
            "prompt_version": "test-prompt-v1",
            "specification_sha256": "1" * 64,
            "catalogue_sha256": "2" * 64,
            "terminology_sha256": "3" * 64,
            "batch_id": "test-batch-2",
            "generated_at": "2026-09-26T12:05:00Z",
            "items": [{
                "message_key": MESSAGE_KEY,
                "translated_text": "يجب ألا تستبدل هذه الصياغة {language}.",
            }],
        },
    )
    assert protected.status_code == 200
    assert protected.json()["stored"] == 0
    assert protected.json()["protected"] == [{"message_key": MESSAGE_KEY, "origin": "generated"}]
    assert _translation(client)["translated_text"] == "اللغة {language} غير متاحة."

    report = client.get("/api/v1/admin/i18n/generation-report/ar")
    assert report.status_code == 200
    assert report.json()["generated"] == 1
    assert report.json()["generated_reviewed"] == 0
    assert report.json()["generated_published"] == 0
    assert report.json()["awaiting_generation"] == report.json()["total"] - 1


def test_generation_batch_reports_invalid_placeholders_without_writing(client):
    result = client.post(
        "/api/v1/admin/i18n/generated-drafts/ar",
        headers={"X-Change-Reason": "Validate failed Arabic candidate"},
        json={
            "generator": "approved-test-generator",
            "model": "test-model",
            "model_version": "1",
            "prompt_version": "test-prompt-v1",
            "specification_sha256": "1" * 64,
            "catalogue_sha256": "2" * 64,
            "terminology_sha256": "3" * 64,
            "batch_id": "test-batch-invalid",
            "generated_at": "2026-09-26T12:00:00Z",
            "items": [{"message_key": MESSAGE_KEY, "translated_text": "لغة غير متاحة."}],
        },
    )
    assert result.status_code == 200
    assert result.json()["stored"] == 0
    assert result.json()["failures"] == [{
        "message_key": MESSAGE_KEY,
        "code": "placeholder_mismatch",
        "parameters": {"missing": ["language"], "unexpected": []},
    }]
    assert _translation(client)["origin"] == "source_copy"


def test_arabic_change_reason_survives_translation_save_publish_and_audit(client):
    reason = 'تصحيح الترجمة العربية — مراجعة المصطلحات'
    current = _translation(client)
    path = f'/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar'
    updated = client.put(path, headers={
        'If-Match': str(current['translation_version']),
        'X-Change-Reason': reason.encode('utf-8'),
    }, json={'translated_text': 'اللغة {language} غير مدعومة.', 'origin': 'manual', 'reviewed': True})
    assert updated.status_code == 200, updated.text
    published = client.post(path + '/publish', headers={
        'If-Match': str(updated.json()['version']),
        'X-Change-Reason': reason.encode('utf-8'),
    })
    assert published.status_code == 200, published.text
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        events = connection.execute(
            "SELECT reason FROM event_history WHERE entity_type='ui_message_translation' ORDER BY id DESC LIMIT 2"
        ).fetchall()
    assert events == [(reason,), (reason,)]


def test_arabic_change_reason_limit_counts_characters_not_utf8_bytes(client):
    current = _translation(client)
    path = f'/api/v1/admin/i18n/messages/{MESSAGE_KEY}/translations/ar'
    payload = {'translated_text': 'اللغة {language} غير مدعومة.', 'origin': 'manual', 'reviewed': True}
    headers = {'If-Match': str(current['translation_version']), 'X-Change-Reason': ('ع' * 2001).encode('utf-8')}
    rejected = client.put(path, headers=headers, json=payload)
    assert rejected.status_code == 400
    headers['X-Change-Reason'] = ('ع' * 2000).encode('utf-8')
    accepted = client.put(path, headers=headers, json=payload)
    assert accepted.status_code == 200, accepted.text


def test_bulk_review_acknowledges_review_marker_but_blocks_real_quality_flags(client):
    synchronize_generated_arabic_drafts()
    key='disposition.ui.accelerate'
    other='disposition.ui.accelerate_scope'
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.change_reason','Prepare review-marker regression',true)")
        connection.execute("UPDATE ui_message_translations SET generation_metadata=jsonb_set(generation_metadata,'{quality_flags}','[\"needs_human_review\",\"unknown_quality_defect\"]'::jsonb) WHERE message_key=%s AND language_tag='ar'",(other,))
        before=connection.execute("SELECT message_key,version,generation_metadata FROM ui_message_translations WHERE message_key=ANY(%s) AND language_tag='ar' ORDER BY message_key",([key,other],)).fetchall()
        revision=connection.execute("SELECT catalogue_revision FROM supported_languages WHERE language_tag='ar'").fetchone()[0]
    preview=client.get('/api/v1/admin/i18n/translations/ar/bulk-publication-preview').json()
    assert not any(e['message_key']==key for e in preview['invalid'])
    assert {'message_key':other,'code':'generation_quality_attention'} in preview['invalid']
    selected=[i for i in preview['items'] if i['message_key'] in (key,other)]
    blocked=client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',json={'items':selected},headers={'X-Change-Reason':'Review mixed valid and invalid drafts'})
    assert blocked.status_code==422
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        assert connection.execute("SELECT message_key,version,generation_metadata FROM ui_message_translations WHERE message_key=ANY(%s) AND language_tag='ar' ORDER BY message_key",([key,other],)).fetchall()==before
        assert connection.execute("SELECT catalogue_revision FROM supported_languages WHERE language_tag='ar'").fetchone()[0]==revision
    result=client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',json={'items':[i for i in selected if i['message_key']==key]},headers={'X-Change-Reason':'Explicitly review generated Arabic draft','X-Event-Source':'web_ui'})
    assert result.status_code==200,result.text
    assert result.json()['catalogue_revision']==revision+1
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        row=connection.execute("SELECT status,generation_metadata,reviewed_by_user_id,published_by_user_id,date_reviewed,date_published,needs_review FROM ui_message_translations WHERE message_key=%s AND language_tag='ar'",(key,)).fetchone()
        expected=dict(next(r[2] for r in before if r[0]==key));expected['quality_flags']=[]
        assert row[0]=='published' and row[1]==expected
        assert row[2] is not None and row[2]==row[3] and row[4]==row[5] and not row[6]
        event=connection.execute("SELECT before_state,after_state FROM event_history WHERE entity_type='ui_message_translation' AND reason='Explicitly review generated Arabic draft' AND source='web_ui'").fetchone()
        assert event[0]['generation_metadata']['quality_flags']==['needs_human_review']
        assert event[1]['generation_metadata']['quality_flags']==[]


@pytest.mark.parametrize('text,flags',[
    ('', ['needs_human_review']),
    ('نص {unexpected}', ['needs_human_review']),
    ('<script>نص</script>', ['needs_human_review']),
    ('نص', ['needs_human_review','placeholder_mismatch']),
])
def test_review_marker_never_bypasses_translation_validation(text,flags):
    from backend.services.api.localization import _bulk_validation_errors
    assert _bulk_validation_errors([{'message_key':'test','translated_text':text,'parameter_schema':{},'is_html':False,'generation_metadata':{'quality_flags':flags}}])
