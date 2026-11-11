"""Digital-file presentation and supported preview formats."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from html import escape as html_escape
from nicegui import ui
from .i18n_catalogue import render_message

CONVERTIBLE_PREVIEW_EXTENSIONS = {
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".md", ".msg", ".eml", ".html", ".txt", ".xml",
}


def localized_component_status(value: Any) -> str:
    return render_message({
        "available": "advanced_search.value.available",
        "staged": "advanced_search.value.pending",
        "pending": "advanced_search.value.pending",
        "failed": "advanced_search.value.failed",
        "quarantined": "advanced_search.value.quarantined",
        "deleted": "advanced_search.value.deleted",
    }.get(str(value or "").lower(), "common.status.loading"))


def localized_indexing_status(value: Any) -> str:
    return render_message({
        "indexed": "advanced_search.value.available",
        "succeeded": "advanced_search.value.available",
        "failed": "advanced_search.value.failed",
        "unsupported": "translation_inspector.value.no",
        "processing": "webui.select_text_indexers.text.processing_c1ea7da0",
        "leased": "webui.select_text_indexers.text.processing_c1ea7da0",
        "queued": "advanced_search.value.pending",
        "pending": "advanced_search.value.pending",
        "stale": "advanced_search.value.pending",
    }.get(str(value or "").lower(), "common.status.loading"))


def component_file_icon(mime_type: str | None) -> str:
    value = (mime_type or "").lower()
    if value == "application/pdf":
        return "picture_as_pdf"
    if value.startswith("image/"):
        return "image"
    if value.startswith("audio/"):
        return "audio_file"
    if value.startswith("video/"):
        return "video_file"
    if "spreadsheet" in value or "excel" in value or value == "text/csv":
        return "table_view"
    if "word" in value or "document" in value or value.startswith("text/"):
        return "description"
    return "description"


def native_preview_kind(mime_type: str | None) -> str | None:
    value = (mime_type or "").lower()
    if value in {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/avif"}:
        return "image"
    if value.startswith("audio/"):
        return "audio"
    if value.startswith("video/"):
        return "video"
    return None


def requires_document_conversion(component: dict[str, Any]) -> bool:
    return (
        native_preview_kind(component.get("mime_type")) is None
        and (component.get("mime_type") or "").lower() != "application/pdf"
        and Path(component.get("file_name") or "").suffix.lower()
        in CONVERTIBLE_PREVIEW_EXTENSIONS
    )


def component_is_previewable(component: dict[str, Any], *, staged: bool = False) -> bool:
    """Supported saved content, or completed staged content only in a draft context."""
    if component.get("content_status", "pending") not in ({"staged"} if staged else {"available"}):
        return False
    mime_type = (component.get("mime_type") or "").lower()
    return bool(
        native_preview_kind(mime_type)
        or mime_type == "application/pdf"
        or requires_document_conversion(component)
    )


def component_uploader(on_multi_upload, *, label: str | None = None):
    component_label = label or render_message("webui.open_record_draft_editor.label.digital_components_21c9474b")
    component_guidance = render_message("webui.select_record_details.label.files_belonging_to_this_record_can_be_mana_7c78350c")
    browse_label = render_message("navigation.item.organization_browser")
    empty_label = render_message("webui.render_current_components.label.no_digital_components_have_been_uploaded_y_3f61a29a")
    uploader = ui.upload(
        on_multi_upload=on_multi_upload,
        label=component_label,
        auto_upload=True,
        multiple=True,
    ).props("accept=*").classes("record-uploader w-full")
    uploader.add_slot("header", f"""
        <div class="row items-center no-wrap full-width q-pa-md q-gutter-md upload-header">
          <q-avatar icon="cloud_upload" color="blue-1" text-color="primary" size="42px" />
          <div class="column col">
            <span class="text-weight-medium text-slate-800">{html_escape(component_label)}</span>
            <span class="text-caption text-slate-500">{html_escape(component_guidance)}</span>
          </div>
          <q-btn outline no-caps color="primary" icon="folder_open" label="{html_escape(browse_label)}">
            <q-uploader-add-trigger />
          </q-btn>
        </div>
    """)
    uploader.add_slot("list", f"""
        <div v-if="props.files.length === 0" class="upload-empty">
          {html_escape(empty_label)}
        </div>
        <q-list v-else separator class="upload-queue">
          <q-item v-for="file in props.files" :key="file.__key" dense class="q-px-md q-py-sm">
            <q-item-section avatar style="min-width: 38px">
              <q-icon name="description" color="blue-grey-5" size="22px" />
            </q-item-section>
            <q-item-section class="min-width-0">
              <q-item-label class="text-weight-medium ellipsis">{{{{ file.name }}}}</q-item-label>
              <q-item-label caption>{{{{ file.__sizeLabel }}}} · {{{{ file.__progressLabel }}}}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-spinner v-if="file.__status === 'uploading'" color="primary" size="22px" />
              <q-icon v-else-if="file.__status === 'uploaded'" name="check_circle" color="positive" size="22px" />
              <q-icon v-else-if="file.__status === 'failed'" name="error" color="negative" size="22px" />
              <q-icon v-else name="schedule" color="blue-grey-4" size="22px" />
            </q-item-section>
          </q-item>
        </q-list>
    """)
    return uploader
