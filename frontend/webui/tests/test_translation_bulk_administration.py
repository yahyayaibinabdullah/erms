from pathlib import Path


ROOT = Path(__file__).parents[3]
APP_SOURCE = (ROOT / "frontend/webui/translation_administration.py").read_text()
CLIENT_SOURCE = (ROOT / "frontend/webui/api_client.py").read_text()


def test_translation_screen_uses_governed_bulk_publication_api():
    assert "preview_bulk_localization_publication" in CLIENT_SOURCE
    assert "bulk_review_publish_localization" in CLIENT_SOURCE
    assert "bulk_review_publish_dialog" in APP_SOURCE
    assert 'bulk_publish_all.on(' in APP_SOURCE
    assert "localization.bulk.dialog.guidance" in APP_SOURCE
    assert 'preview.get("source_copy_excluded") or 0' in APP_SOURCE
    assert "localization.bulk.dialog.source_copies_excluded" in APP_SOURCE


def test_language_cards_select_the_administration_language_for_bulk_publication():
    assert "language_select = ui.select(" not in APP_SOURCE
    assert 'administration_language = {"value": selected_tag}' in APP_SOURCE
    assert "async def select_administration_language(language_tag: str)" in APP_SOURCE
    assert 'card.on("click"' in APP_SOURCE
    assert 'language_tag=administration_language["value"]' in APP_SOURCE
    assert "def select_bulk_publication_language_dialog()" not in APP_SOURCE


def test_selected_language_statistics_expose_bulk_publication_directly():
    summary = APP_SOURCE.index("generation_bulk_publish = ui.button")
    coverage = APP_SOURCE.index("generation_coverage = ui.label", summary)
    assert summary < coverage
    assert 'generation_bulk_publish.on(' in APP_SOURCE
    assert 'language_tag=administration_language["value"]' in APP_SOURCE
    assert 'generation_card.set_visibility(administration_language["value"].lower() == "ar")' not in APP_SOURCE
    assert 'total=generation["total"]' in APP_SOURCE
    assert 'unpublished=generation["unpublished"]' in APP_SOURCE


def test_context_badge_wall_is_removed_in_favour_of_real_group_controls():
    assert "group_summary" not in APP_SOURCE
    assert "group['published']} published" not in APP_SOURCE
    assert "localization.bulk.action.review_publish_context" in APP_SOURCE


def test_translation_editor_labels_the_semantic_meaning_explicitly():
    editor = APP_SOURCE[APP_SOURCE.index("async def edit_translation("):]
    label = 'render_message("webui.select_translation_administration.input.semantic_meaning_b8e3fe8d")'
    assert label in editor
    assert 'ui.label(item["semantic_meaning"])' in editor
