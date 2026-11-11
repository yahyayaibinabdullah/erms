"""Existing record/resource presentation and editor rules."""
from __future__ import annotations
from .i18n_catalogue import render_message

RECORD_DETAIL_HEADER_CLASSES = "w-full items-center gap-3 no-wrap"


RECORD_DETAIL_TITLE_CLASSES = "gap-0 grow min-w-0"


RECORD_UPLOAD_WAIT_MESSAGE = render_message("webui.module.text.please_wait_until_all_files_have_finished_65b4bf18")
