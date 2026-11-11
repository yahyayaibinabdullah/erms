"""One-time indexer key reveal; retain the original transient close behavior."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from nicegui import ui
from .i18n_catalogue import render_message


def reveal_text_indexer_key(
    result: dict[str, Any], on_closed: Any,
) -> None:
    api_key = result.pop("api_key")
    dialog = ui.dialog().props("persistent")
    with dialog, ui.card().classes("w-[680px] max-w-full gap-4"):
        ui.label(render_message("webui.reveal_text_indexer_key.label.new_text_indexer_api_key_2a85fa1b")).classes("text-xl font-semibold")
        with ui.row().classes(
            "w-full items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3"
        ):
            ui.icon("warning", color="warning")
            ui.label(
                render_message("webui.reveal_text_indexer_key.label.copy_and_store_this_key_now_it_will_not_be_49aad18d")
            ).classes("text-sm font-medium")
        ui.label(api_key).classes(
            "w-full font-mono text-sm bg-slate-100 rounded p-3 break-all select-all"
        )

        async def close_reveal() -> None:
            nonlocal api_key
            api_key = ""
            dialog.close()
            follow_up = on_closed()
            if asyncio.iscoroutine(follow_up):
                await follow_up

        with ui.row().classes("w-full justify-between gap-2 flex-wrap"):
            ui.button(
                render_message("webui.reveal_text_indexer_key.button.copy_e8a7c395"), icon="content_copy",
                on_click=lambda: ui.run_javascript(
                    f"navigator.clipboard.writeText({json.dumps(api_key)}).then(() => true)",
                    timeout=5,
                ),
            ).props("outline no-caps")
            ui.button(
                render_message("webui.reveal_text_indexer_key.button.download_credential_file_99e25d6c"), icon="download",
                on_click=lambda: ui.run_javascript(
                    "(() => { const b=new Blob([" + json.dumps(
                        "TEXT_INDEXER_API_KEY=" + api_key + "\n"
                    ) + "],{type:'text/plain'});const a=document.createElement('a');"
                    "a.href=URL.createObjectURL(b);a.download='wathiq-text-indexer.env';"
                    "a.click();URL.revokeObjectURL(a.href);return true;})()",
                    timeout=5,
                ),
            ).props("flat no-caps color=warning").tooltip(
                render_message("webui.reveal_text_indexer_key.tooltip.downloads_a_sensitive_plaintext_file_0acbd408")
            )
            ui.button(
                render_message("webui.reveal_text_indexer_key.button.i_have_stored_it_safely_e3a69b9d"), on_click=close_reveal,
            ).props("unelevated no-caps")
    dialog.open()

