"""Translation administration with per-client paging and language ownership."""
from __future__ import annotations
import asyncio
import inspect
import json
from typing import Any, Callable
from nicegui import background_tasks, events, ui
from .api_client import ApiError
from .i18n_catalogue import render_message, strip_diagnostic_metadata


def build_translation_administration(
    *, api, register_navigation, show_authenticated_view, enter_translations, current_page, title, subtitle, search_bar, aggregation_mode_bar, add_button, add_record_button, guidance, table_container, page_client, error_message, buffer_upload_batch,
):
    # Persist for this client, including navigation and identity changes, exactly
    # as the original page-owned fields did. No catalogue or response cache.
    translation_state: dict[str, Any] = {}

    async def select_translation_administration(initial_key: str | None = None) -> None:
        register_navigation("translations", render_message("navigation.item.translations"))
        show_authenticated_view()
        enter_translations()
        title.text = render_message("navigation.item.translations")
        subtitle.text = render_message("localization.administration.subtitle")
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False); guidance.text = ""
        table_container.clear()
        languages = await api.localization_languages()
        selected_tag = translation_state.get("translation_language") or next(
            (item["language_tag"] for item in languages if item["language_tag"].lower() != "en"),
            languages[0]["language_tag"],
        )
        administration_language = {"value": selected_tag}
        language_cards: dict[str, Any] = {}
        # The primary pager operates on complete context groups. Individual
        # translation keys are never split arbitrarily between main pages.
        page = {"offset": int(translation_state.get("translation_offset", 0)), "limit": 10, "total": 0, "key_total": 0}
        expanded_contexts = set(translation_state.get("translation_expanded_contexts") or [])
        message_load = {"sequence": 0}

        def set_translation_context_expanded(context_group: str, expanded: bool) -> None:
            if expanded:
                expanded_contexts.add(context_group)
            else:
                expanded_contexts.discard(context_group)
            translation_state["translation_expanded_contexts"] = sorted(expanded_contexts)

        with table_container, ui.column().classes("w-full p-4 gap-4"):
            with ui.card().classes("w-full shadow-none border border-slate-200 p-3 gap-3"):
                with ui.row().classes("translation-card-toolbar w-full items-center justify-between gap-2"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("language", color="primary", size="24px")
                        ui.label(render_message("webui.select_translation_administration.label.supported_languages_0a3fd31a")).classes("text-lg font-semibold")
                    with ui.row().classes("translation-card-actions items-center gap-1"):
                        bulk_publish_all = ui.button(icon="done_all").props(
                            'flat round dense aria-label=' + repr(render_message("localization.bulk.action.review_publish_all"))
                        ).tooltip(render_message("localization.bulk.action.review_publish_all"))
                        import_artifact = ui.button(icon="upload_file").props(
                            'flat round dense aria-label=' + repr(render_message("localization.artifact.import.action"))
                        ).tooltip(render_message("localization.artifact.import.action"))
                        export_artifact = ui.button(icon="download").props(
                            'flat round dense aria-label=' + repr(render_message("localization.artifact.export.action"))
                        ).tooltip(render_message("localization.artifact.export.action"))
                        add_language = ui.button(icon="add").props(
                            'flat round dense aria-label=' + repr(render_message("webui.select_translation_administration.accessible_name.add_supported_language_e7682117"))
                        ).tooltip(render_message("webui.select_translation_administration.tooltip.add_supported_language_59cab869"))
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    for language in languages:
                        is_selected = language["language_tag"] == selected_tag
                        language_card = ui.card().classes(
                            "shadow-none border px-3 py-2 min-w-48 gap-0 cursor-pointer " +
                            ("border-primary bg-blue-50" if is_selected else "border-slate-200")
                        ).props(
                            f"role=button tabindex=0 aria-pressed={'true' if is_selected else 'false'}"
                        )
                        language_cards[language["language_tag"]] = language_card
                        with language_card:
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.label(language["native_name"]).classes("font-semibold")
                                ui.badge(language["language_tag"]).props("outline")
                                if language["is_default"]: ui.icon("home", size="16px").tooltip(render_message("webui.select_translation_administration.tooltip.system_default_9488a1a9"))
                                if not language["is_enabled"]: ui.icon("visibility_off", color="grey").tooltip(render_message("webui.select_translation_administration.tooltip.disabled_ab08d474"))
                            ui.label(render_message(
                                "localization.administration.language_metadata",
                                english_name=language["english_name"],
                                direction=language["direction"].upper(),
                                revision=language["catalogue_revision"],
                            )).classes("text-xs text-slate-500")

            with ui.card().classes("w-full shadow-none border border-slate-200 p-3 gap-2") as generation_card:
                with ui.row().classes("translation-card-toolbar w-full items-center justify-between gap-2"):
                    with ui.row().classes("translation-card-heading items-center gap-2"):
                        ui.icon("auto_awesome", color="primary", size="20px")
                        ui.label(render_message("localization.generation.review.title")).classes("font-semibold")
                    with ui.row().classes("translation-card-actions items-center gap-1"):
                        generation_bulk_publish = ui.button(icon="done_all").props(
                            'flat round dense color=primary aria-label=' +
                            repr(render_message("localization.bulk.action.review_publish_all"))
                        ).tooltip(render_message("localization.bulk.action.review_publish_all"))
                        generation_status_icon = ui.icon("hourglass_empty", color="grey", size="18px")
                        with generation_status_icon:
                            generation_status_tooltip = ui.tooltip(
                                render_message("common.status.loading")
                            )
                generation_coverage = ui.label().classes("text-sm font-medium")
                ui.label(render_message("localization.generation.review.guidance")).classes("text-xs text-slate-500 max-w-4xl")

            with ui.card().classes(
                "w-full shadow-none border border-blue-200 bg-blue-50 p-3 gap-1"
            ):
                with ui.row().classes("w-full items-start gap-2 no-wrap"):
                    ui.icon("data_object", color="primary", size="20px")
                    with ui.column().classes("gap-1 grow min-w-0"):
                        ui.label(
                            render_message("localization.placeholder_guidance.title")
                        ).classes("text-sm font-semibold")
                        ui.label(
                            render_message("localization.placeholder_guidance.body")
                        ).classes("text-xs text-slate-600 leading-5")
                        ui.label(
                            render_message("localization.placeholder_guidance.example")
                        ).classes("font-mono text-xs text-blue-900")

            with ui.card().classes("w-full shadow-none border border-slate-200 p-3 gap-3"):
                with ui.row().classes("translation-filter-row w-full items-end gap-2 flex-wrap"):
                    key_filter = ui.input(
                        render_message("webui.select_translation_administration.input.key_16b82d81"),
                        value=initial_key or "",
                    ).props("outlined dense clearable debounce=350").classes("w-56")
                    source_filter = ui.input(render_message("localization.filter.source_text")).props("outlined dense clearable debounce=350").classes("w-56")
                    text_filter = ui.input(render_message("webui.select_translation_administration.input.translated_text_054048b6")).props("outlined dense clearable debounce=350").classes("w-56")
                    meaning_filter = ui.input(render_message("webui.select_translation_administration.input.semantic_meaning_b8e3fe8d")).props("outlined dense clearable debounce=350").classes("w-60")
                    status_filter = ui.select({"all":render_message("localization.filter.status.all"),"draft":render_message("localization.filter.status.draft"),"published":render_message("localization.filter.status.published")},value="all",label=render_message("webui.select_translation_administration.select.status_9d5af32b")).props("outlined dense options-dense").classes("w-40")
                    review_filter = ui.select(
                        {
                            "all": render_message("localization.filter.review.all"),
                            "reviewed": render_message("localization.filter.review.reviewed"),
                            "unreviewed": render_message("localization.filter.review.unreviewed"),
                        },
                        value="all",
                        label=render_message("localization.filter.review.label"),
                    ).props("outlined dense options-dense").classes("w-40")
                    origin_filter = ui.select({"all":render_message("localization.filter.origin.all"),"source_copy":render_message("localization.filter.origin.source_copy"),"manual":render_message("localization.filter.origin.manual"),"generated":render_message("localization.filter.origin.generated"),"imported":render_message("localization.filter.origin.imported")},value="all",label=render_message("webui.select_translation_administration.select.origin_8d7c0b5f")).props("outlined dense options-dense").classes("w-40")
                    attention_filter = ui.checkbox(render_message("webui.select_translation_administration.checkbox.needs_attention_752fcdc8"), value=False).props("dense")
                    clear_filters = ui.button(icon="filter_alt_off").props('flat round dense aria-label=' + repr(render_message("webui.select_translation_administration.accessible_name.clear_all_filters_ab8e4797"))).tooltip(render_message("webui.select_translation_administration.tooltip.clear_all_filters_c724f659"))
                result_summary = ui.label().classes("text-xs text-slate-500")
            results = ui.column().classes("w-full gap-2")
            with ui.row().classes("w-full items-center justify-between"):
                previous_page = ui.button(icon="chevron_left").props('flat round dense aria-label=' + repr(render_message("webui.select_translation_administration.accessible_name.previous_page_ceba2a82"))).tooltip(render_message("webui.select_translation_administration.tooltip.previous_page_626c5552"))
                page_status = ui.label().classes("text-xs text-slate-500")
                next_page = ui.button(icon="chevron_right").props('flat round dense aria-label=' + repr(render_message("webui.select_translation_administration.accessible_name.next_page_6ae11376"))).tooltip(render_message("webui.select_translation_administration.tooltip.next_page_4579f1d3"))

        async def language_dialog() -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[560px] max-w-full gap-3"):
                ui.label(render_message("webui.language_dialog.label.add_supported_language_5f47cbe5")).classes("text-xl font-semibold")
                ui.label(render_message("webui.language_dialog.label.a_complete_english_source_copy_queue_will_e6ad606f")).classes("text-sm text-slate-500")
                tag = ui.input(render_message("webui.language_dialog.input.language_tag_06f051a8")).props("outlined dense").classes("w-full")
                english = ui.input(render_message("webui.language_dialog.input.english_name_d777670b")).props("outlined dense").classes("w-full")
                native = ui.input(render_message("webui.language_dialog.input.native_name_b20c7ddf")).props("outlined dense").classes("w-full")
                direction = ui.select({"ltr":render_message("localization.direction.ltr"),"rtl":render_message("localization.direction.rtl")},value="ltr",label=render_message("webui.language_dialog.select.direction_06f49582")).props("outlined dense").classes("w-full")
                enabled = ui.checkbox(render_message("webui.language_dialog.checkbox.enabled_6349b67b"), value=True)
                reason = ui.input(render_message("webui.language_dialog.input.change_reason_43395b30")).props("outlined dense").classes("w-full")
                async def submit_language() -> None:
                    if not (tag.value or "").strip() or not (english.value or "").strip() or not (native.value or "").strip() or not (reason.value or "").strip():
                        ui.notify(render_message("webui.submit_language.notify.complete_all_required_fields_and_enter_a_c_ce2134ba"), color="warning"); return
                    try:
                        await api.create_localization_language({"language_tag":tag.value,"english_name":english.value,"native_name":native.value,"direction":direction.value,"is_enabled":enabled.value,"is_default":False,"formatting_config":{"locale":tag.value}},reason.value)
                        dialog.close(); ui.notify(render_message("webui.submit_language.notify.supported_language_added_c62b373a"),color="positive"); await select_translation_administration()
                    except ApiError as error: ui.notify(error_message(error),color="negative",close_button=True)
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.language_dialog.button.cancel_8d45c1e5"),on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.language_dialog.button.add_language_bd158eeb"),icon="add",on_click=submit_language).props("unelevated no-caps")
            dialog.open()

        async def edit_translation(
            item: dict[str, Any], *, after_persist: Callable[[], Any] | None = None,
        ) -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[900px] max-w-full gap-3"):
                with ui.row().classes("w-full items-start gap-2"):
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(item["message_key"]).classes("font-mono text-sm font-semibold break-all")
                        ui.label(
                            render_message("webui.select_translation_administration.input.semantic_meaning_b8e3fe8d")
                        ).classes("detail-field-label mt-2")
                        ui.label(item["semantic_meaning"]).classes("text-sm text-slate-600 leading-5")
                    ui.badge(item["validity"].replace("_"," ").title(),color="amber" if item["validity"]!="valid" else "positive").props("outline")
                with ui.row().classes("w-full gap-3 items-stretch"):
                    with ui.card().classes("shadow-none bg-slate-50 p-3 gap-2 flex-1 min-w-0"):
                        ui.label(render_message("webui.edit_translation.label.english_source_3c72859a")).classes("detail-field-label")
                        ui.label(item["default_text"]).classes("text-sm")
                        ui.label(render_message("webui.edit_translation.label.rendered_example_cb005617")).classes("detail-field-label mt-2")
                        ui.label(item["rendered_example"]).classes("text-sm")
                    with ui.card().classes("shadow-none border border-slate-200 p-3 gap-2 flex-1 min-w-0"):
                        ui.label(render_message("webui.edit_translation.label.translator_guidance_6f283ab4")).classes("detail-field-label")
                        ui.label(item["translator_guidance"]).classes("text-sm")
                        ui.label(render_message("localization.editor.grammatical_role",role=item["grammatical_role"])).classes("text-xs text-slate-500")
                        ui.label(render_message("localization.editor.common_locations",locations=", ".join(item["common_locations"]))).classes("text-xs text-slate-500")
                        ui.label(render_message("localization.editor.parameters",parameters=", ".join(f"{k}: {v}" for k,v in item["parameter_schema"].items()) or render_message("localization.editor.parameters.none"))).classes("text-xs text-slate-500")
                translation = ui.textarea(render_message("webui.edit_translation.textarea.translation_f0b41724"),value=item.get("translated_text") or "").props("outlined autogrow").classes("w-full")
                inline_error = ui.label().classes("text-sm text-negative")
                origin = ui.select({"manual":render_message("localization.filter.origin.manual"),"generated":render_message("localization.filter.origin.generated"),"imported":render_message("localization.filter.origin.imported")},value="manual" if item.get("origin")=="source_copy" else item.get("origin") or "manual",label=render_message("webui.edit_translation.select.origin_65b2b457")).props("outlined dense options-dense").classes("w-48")
                reviewed = ui.checkbox(render_message("webui.edit_translation.checkbox.reviewed_by_me_a4519872"),value=bool(item.get("date_reviewed")))
                reason = ui.input(render_message("webui.edit_translation.input.change_reason_75cafd6a")).props("outlined dense").classes("w-full")
                with ui.row().classes("w-full justify-end gap-2"):
                    cancel = ui.button(icon="close").props('flat round aria-label=' + repr(render_message("webui.edit_translation.accessible_name.close_translation_editor_da93bee8"))).tooltip(render_message("webui.edit_translation.tooltip.close_e743eb2f"))
                    save = ui.button(icon="save").props('flat round color=primary aria-label=' + repr(render_message("webui.edit_translation.accessible_name.save_translation_draft_99ac0e72"))).tooltip(render_message("webui.edit_translation.tooltip.save_draft_fe503c91"))
                    publish = ui.button(icon="publish").props('unelevated round color=primary aria-label=' + repr(render_message("webui.edit_translation.accessible_name.publish_translation_c7947bff"))).tooltip(render_message("webui.edit_translation.tooltip.publish_387dcb6f"))
                cancel.on("click",dialog.close)
                def validate_entry() -> bool:
                    blank=not (translation.value or "").strip(); missing_reason=not (reason.value or "").strip()
                    inline_error.text=render_message("localization.editor.validation.translation_required") if blank else render_message("localization.editor.validation.reason_required") if missing_reason else ""
                    save.set_enabled(not blank and not missing_reason);publish.set_enabled(not blank and not missing_reason)
                    return not blank and not missing_reason
                translation.on_value_change(validate_entry);reason.on_value_change(validate_entry);validate_entry()
                async def persist(do_publish: bool) -> None:
                    if not validate_entry(): return
                    try:
                        scroll_top = await page_client.run_javascript(
                            "document.scrollingElement?.scrollTop || window.scrollY || 0"
                        )
                        saved=await api.update_localization_translation(item["message_key"],administration_language["value"],{"translated_text":translation.value,"origin":origin.value,"reviewed":reviewed.value,"generation_metadata":item.get("generation_metadata")},item["translation_version"],reason.value)
                        if do_publish: await api.publish_localization_translation(item["message_key"],administration_language["value"],saved["version"],reason.value)
                        dialog.close();ui.notify(render_message("localization.editor.notify.published") if do_publish else render_message("localization.editor.notify.saved"),color="positive");await load_messages(restore_scroll=scroll_top)
                        if after_persist is not None:
                            result = after_persist()
                            if inspect.isawaitable(result):
                                await result
                    except ApiError as error:
                        inline_error.text=error_message(error)
                save.on("click",lambda:persist(False));publish.on("click",lambda:persist(True))
            dialog.open()

        async def bulk_review_publish_dialog(
            context_group: str | None = None, *, language_tag: str | None = None,
        ) -> None:
            target_language = language_tag or administration_language["value"]
            try:
                preview = await api.preview_bulk_localization_publication(
                    target_language, context_group or "",
                )
            except ApiError as error:
                ui.notify(error_message(error),color="negative",close_button=True);return
            dialog=ui.dialog().props("persistent")
            with dialog,ui.card().classes("w-[680px] max-w-full gap-3"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("done_all",color="primary",size="22px")
                    ui.label(render_message("localization.bulk.dialog.title")).classes("text-lg font-semibold grow")
                scope_text=(context_group if context_group else render_message("localization.bulk.scope.all"))
                ui.label(render_message("localization.bulk.dialog.summary",count=preview["count"],scope=scope_text)).classes("text-sm")
                ui.label(render_message("localization.bulk.dialog.guidance")).classes("text-xs text-slate-500")
                source_copy_excluded=int(preview.get("source_copy_excluded") or 0)
                if source_copy_excluded:
                    ui.label(render_message(
                        "localization.bulk.dialog.source_copies_excluded",
                        count=source_copy_excluded,
                    )).classes("text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3")
                invalid=preview.get("invalid") or []
                if invalid:
                    with ui.card().classes("w-full shadow-none border border-red-300 bg-red-50 p-3 gap-1"):
                        ui.label(render_message("localization.bulk.dialog.blocked",count=len(invalid))).classes("text-sm font-semibold text-negative")
                        for problem in invalid[:20]:
                            ui.label(render_message("webui.bulk_review_publish_dialog.label.message_key_code_19cb32db", message_key=problem['message_key'], code=problem['code'])).classes("font-mono text-xs break-all")
                        if len(invalid)>20:
                            ui.label(render_message("localization.bulk.dialog.more_invalid",count=len(invalid)-20)).classes("text-xs text-slate-600")
                reason=ui.input(render_message("localization.bulk.field.change_reason")).props("outlined dense").classes("w-full")
                inline_error=ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(icon="close",on_click=dialog.close).props('flat round aria-label=' + repr(render_message("webui.bulk_review_publish_dialog.accessible_name.cancel_9a278e83"))).tooltip(render_message("localization.bulk.action.cancel"))
                    confirm=ui.button(icon="publish").props('unelevated round color=primary aria-label=' + repr(render_message("webui.bulk_review_publish_dialog.accessible_name.review_and_publish_selected_translations_4a6ed1b8"))).tooltip(render_message("localization.bulk.action.confirm"))
                def validate_bulk() -> bool:
                    valid=bool(preview["items"]) and not invalid and bool((reason.value or "").strip())
                    inline_error.text="" if valid or not preview["items"] else render_message("localization.bulk.validation.reason_required") if not (reason.value or "").strip() else ""
                    confirm.set_enabled(valid)
                    return valid
                async def submit_bulk() -> None:
                    if not validate_bulk():return
                    try:
                        result=await api.bulk_review_publish_localization(target_language,preview["items"],reason.value.strip())
                        dialog.close();ui.notify(render_message("localization.bulk.notify.published",count=result["published"]),color="positive");await load_messages(True)
                    except ApiError as error:
                        inline_error.text=error_message(error)
                reason.on_value_change(validate_bulk);confirm.on("click",submit_bulk);validate_bulk()
            dialog.open()

        async def export_artifact_dialog() -> None:
            target_language = administration_language["value"]
            selected_language = next(
                item for item in languages if item["language_tag"] == target_language
            )
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[680px] max-w-full gap-3"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("download", color="primary", size="22px")
                    ui.label(render_message("localization.artifact.export.title")).classes("text-lg font-semibold grow")
                ui.label(render_message("localization.artifact.export.guidance")).classes("text-sm text-slate-600")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label(
                        render_message("webui.select_translation_administration.select.language_5b6f200e")
                    ).classes("text-sm text-slate-500")
                    ui.label(selected_language["native_name"]).classes("font-semibold")
                    ui.badge(target_language).props("outline")
                include_drafts = ui.checkbox(
                    render_message("localization.artifact.export.include_reviewed_drafts"), value=False,
                ).props("dense")
                summary_label = ui.label().classes("text-sm")
                problems = ui.column().classes("w-full gap-1")
                export_actions = ui.row().classes("w-full justify-end gap-2")

                async def focus_export_problem(message_key: str) -> None:
                    """Open one blocked row and return to the refreshed export queue."""
                    try:
                        data = await api.localization_messages(
                            language_tag=target_language,
                            key=message_key,
                            status="all",
                            origin="all",
                            review_state="all",
                            limit=200,
                            offset=0,
                        )
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)
                        return
                    item = next(
                        (entry for entry in data.get("items", []) if entry["message_key"] == message_key),
                        None,
                    )
                    if item is None:
                        return
                    dialog.close()
                    await edit_translation(
                        item,
                        after_persist=export_artifact_dialog,
                    )

                def render_export_problem(message_key: str, code: str | None = None) -> None:
                    with ui.row().classes("w-full items-center gap-2 no-wrap py-1"):
                        ui.label(message_key).classes(
                            "font-mono text-xs break-all grow min-w-0"
                        )
                        if code:
                            ui.badge(code.replace("_", " ")).props("outline color=negative")
                        ui.button(
                            icon="edit",
                            on_click=lambda _, key=message_key: focus_export_problem(key),
                        ).props(
                            'flat round dense aria-label=' +
                            repr(render_message("webui.load_messages.accessible_name.edit_translation_c3be8114"))
                        ).tooltip(
                            render_message("webui.load_messages.tooltip.edit_translation_7e06ffab")
                        )

                async def refresh_export_preview() -> None:
                    try:
                        preview = await api.preview_localization_export(
                            target_language,
                            include_reviewed_drafts=bool(include_drafts.value),
                        )
                    except ApiError as error:
                        summary_label.text = error_message(error); download.disable(); return
                    summary_label.text = render_message(
                        "localization.artifact.export.summary",
                        exportable=preview["exportable_keys"], active=preview["active_keys"],
                        changed=preview["changed_from_checked_in"], drafts=preview["reviewed_draft_overrides"],
                    )
                    problems.clear()
                    with problems:
                        if preview["missing_keys"]:
                            with ui.expansion(
                                render_message(
                                    "localization.artifact.export.missing",
                                    count=len(preview["missing_keys"]),
                                ),
                                icon="warning_amber",
                            ).classes("w-full border border-red-200 rounded-lg text-negative"):
                                with ui.column().classes("w-full gap-0 px-3 pb-2 max-h-72 overflow-y-auto"):
                                    for message_key in preview["missing_keys"]:
                                        render_export_problem(message_key)
                        if preview["invalid_keys"]:
                            with ui.expansion(
                                render_message(
                                    "localization.artifact.export.invalid",
                                    count=len(preview["invalid_keys"]),
                                ),
                                icon="error_outline",
                            ).classes("w-full border border-red-200 rounded-lg text-negative"):
                                with ui.column().classes("w-full gap-0 px-3 pb-2 max-h-72 overflow-y-auto"):
                                    for problem in preview["invalid_keys"]:
                                        render_export_problem(
                                            problem["message_key"], problem.get("code")
                                        )
                    download.set_enabled(bool(preview["complete"]))
                    bulk_review.enable()

                async def download_export() -> None:
                    try:
                        result = await api.export_localization_artifact(
                            target_language,
                            include_reviewed_drafts=bool(include_drafts.value),
                        )
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True); return
                    content = json.dumps(result["artifact"], ensure_ascii=False, indent=2).encode("utf-8")
                    ui.download(content, result["filename"], "application/json")
                    dialog.close()
                    ui.notify(render_message("localization.artifact.export.ready"), color="positive")

                async def open_bulk_review_from_export() -> None:
                    dialog.close()
                    # This is a dialog-to-dialog transition. Wait for the
                    # export overlay to close before opening the bulk review
                    # confirmation, otherwise the new dialog can disappear in
                    # the same close cycle.
                    await asyncio.sleep(0.1)
                    await bulk_review_publish_dialog(language_tag=target_language)

                with export_actions:
                    bulk_review = ui.button(
                        icon="done_all", on_click=open_bulk_review_from_export,
                    ).props(
                        'flat round aria-label=' +
                        repr(render_message("localization.bulk.action.review_publish_all"))
                    ).tooltip(render_message("localization.bulk.action.review_publish_all"))
                    ui.button(icon="close", on_click=dialog.close).props("flat round").tooltip(render_message("common.action.cancel"))
                    download = ui.button(icon="download").props(
                        'unelevated round color=primary aria-label=' + repr(render_message("localization.artifact.export.download"))
                    ).tooltip(render_message("localization.artifact.export.download"))
                include_drafts.on_value_change(refresh_export_preview)
                download.on("click", download_export)
            dialog.open()
            await refresh_export_preview()

        async def import_artifact_dialog() -> None:
            dialog = ui.dialog().props("persistent")
            selected: dict[str, Any] = {"artifact": None, "preview": None, "language_tag": None}
            with dialog, ui.card().classes("w-[720px] max-w-full gap-3"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("upload_file", color="primary", size="22px")
                    ui.label(render_message("localization.artifact.import.title")).classes("text-lg font-semibold grow")
                ui.label(render_message("localization.artifact.import.guidance")).classes("text-sm text-slate-600")
                import_language = ui.label().classes("text-sm font-semibold")
                summary_label = ui.label(render_message("localization.artifact.import.choose_file")).classes("text-sm")
                problems = ui.column().classes("w-full gap-1")
                reason = ui.input(render_message("localization.bulk.field.change_reason")).props("outlined dense").classes("w-full")

                def validate_import() -> None:
                    preview = selected.get("preview") or {}
                    confirm.set_enabled(bool(preview.get("complete") and (reason.value or "").strip()))

                def uploaded(event: events.MultiUploadEventArguments) -> None:
                    try:
                        files = buffer_upload_batch(event)
                        if len(files) != 1:
                            raise ValueError("one JSON artifact is required")
                        artifact = json.loads(files[0][0].decode("utf-8"))
                        if not isinstance(artifact, dict):
                            raise ValueError("artifact root must be an object")
                        artifact_language = str(artifact.get("language_tag") or "").strip()
                        if not artifact_language:
                            raise ValueError("artifact language_tag is required")
                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                        summary_label.text = render_message("localization.artifact.import.unreadable", error=str(error))
                        import_language.text = ""
                        selected.update(artifact=None, preview=None, language_tag=None); validate_import(); return

                    language = next(
                        (
                            item for item in languages
                            if item["language_tag"].lower() == artifact_language.lower()
                        ),
                        None,
                    )
                    import_language.text = (
                        f"{language['native_name']} ({language['language_tag']})"
                        if language else artifact_language
                    )

                    async def preview_import() -> None:
                        try:
                            preview = await api.preview_localization_import(artifact_language, artifact)
                        except ApiError as error:
                            summary_label.text = error_message(error); selected.update(artifact=None, preview=None, language_tag=None); validate_import(); return
                        selected.update(artifact=artifact, preview=preview, language_tag=artifact_language)
                        summary_label.text = render_message(
                            "localization.artifact.import.summary",
                            importable=preview["importable"], protected=preview["protected"],
                            unchanged=preview["unchanged"], active=preview["active_keys"],
                        )
                        problems.clear()
                        with problems:
                            if preview["missing_keys"]:
                                ui.label(render_message("localization.artifact.import.missing", count=len(preview["missing_keys"]))).classes("text-sm text-negative")
                            if preview["invalid_keys"]:
                                invalid_codes = {
                                    item.get("code") for item in preview["invalid_keys"]
                                }
                                if "artifact_key_order_mismatch" in invalid_codes:
                                    ui.label(render_message(
                                        "localization.artifact.import.key_order_mismatch"
                                    )).classes("text-sm text-negative")
                                remaining_invalid = sum(
                                    item.get("code") != "artifact_key_order_mismatch"
                                    for item in preview["invalid_keys"]
                                )
                                if remaining_invalid:
                                    ui.label(render_message(
                                        "localization.artifact.import.invalid",
                                        count=remaining_invalid,
                                    )).classes("text-sm text-negative")
                        validate_import()

                    background_tasks.create(preview_import())

                ui.upload(
                    on_multi_upload=uploaded, auto_upload=True, multiple=False,
                    label=render_message("localization.artifact.import.choose_file"),
                ).props("accept=.json,application/json").classes("w-full")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(icon="close", on_click=dialog.close).props("flat round").tooltip(render_message("common.action.cancel"))
                    confirm = ui.button(icon="upload_file").props(
                        'unelevated round color=primary aria-label=' + repr(render_message("localization.artifact.import.confirm"))
                    ).tooltip(render_message("localization.artifact.import.confirm"))

                async def submit_import() -> None:
                    validate_import()
                    if not (selected.get("preview") or {}).get("complete") or not (reason.value or "").strip() or selected["artifact"] is None:
                        return
                    try:
                        result = await api.import_localization_artifact(
                            selected["language_tag"], selected["artifact"], reason.value.strip(),
                        )
                    except ApiError as error:
                        summary_label.text = error_message(error); return
                    dialog.close()
                    ui.notify(render_message("localization.artifact.import.done", count=result["imported"]), color="positive")
                    translation_state["translation_language"] = selected["language_tag"]
                    await select_translation_administration()

                reason.on_value_change(validate_import)
                confirm.on("click", submit_import)
                validate_import()
            dialog.open()

        async def load_messages(reset: bool=False, restore_scroll: float | None = None) -> None:
            if current_page() != "translations" or results.is_deleted:
                return
            # Clear-all also runs in a background task. Resolve every label in
            # this page's client/language context, including summary updates.
            with table_container:
                await load_translation_messages(reset, restore_scroll)

        async def load_translation_messages(reset: bool=False, restore_scroll: float | None = None) -> None:
            message_load["sequence"] += 1
            request_sequence = message_load["sequence"]
            if reset: page["offset"]=0
            translation_state["translation_language"]=administration_language["value"];translation_state["translation_offset"]=page["offset"]
            try:
                request_params = dict(
                    language_tag=administration_language["value"],
                    key=strip_diagnostic_metadata(key_filter.value or ""),
                    source_text=strip_diagnostic_metadata(source_filter.value or ""),
                    translated_text=strip_diagnostic_metadata(text_filter.value or ""),
                    semantic_meaning=strip_diagnostic_metadata(meaning_filter.value or ""),
                    status=status_filter.value,origin=origin_filter.value,
                    review_state=review_filter.value,
                    needs_attention=True if attention_filter.value else None,
                    limit=page["limit"],offset=page["offset"],
                )
                data=await api.localization_messages(**request_params)
                # Persisted offsets from the former key-based pager do not
                # represent valid group offsets. Filters can also shrink the
                # available group range. Recover instead of showing no data.
                group_total = data.get("group_total", len(data.get("context_groups", [])))
                if group_total and not data["items"] and page["offset"]:
                    page["offset"] = 0
                    translation_state["translation_offset"] = 0
                    request_params["offset"] = 0
                    data = await api.localization_messages(**request_params)
                    group_total = data.get("group_total", len(data.get("context_groups", [])))
                if request_sequence != message_load["sequence"] or current_page() != "translations" or results.is_deleted:
                    return
                generation = await api.localization_generation_report(administration_language["value"])
            except ApiError as error:
                if request_sequence == message_load["sequence"] and current_page() == "translations" and not results.is_deleted:
                    ui.notify(error_message(error),color="negative",close_button=True)
                return
            # Debounced controls can have more than one request in flight. An
            # older response must never replace the newest filter result.
            if request_sequence != message_load["sequence"]:
                return
            if current_page() != "translations" or results.is_deleted:
                return
            generation_coverage.text = render_message(
                "localization.generation.review.coverage",
                total=generation["total"], drafts=generation["drafts"],
                reviewed=generation["reviewed"], unreviewed=generation["unreviewed"],
                published=generation["published"], unpublished=generation["unpublished"],
                quality=generation["quality_attention"],
            )
            generation_complete = generation["unpublished"] == 0 and generation["quality_attention"] == 0
            generation_status_icon.name = "task_alt" if generation_complete else "pending_actions"
            generation_status_icon.props(f"color={'positive' if generation_complete else 'amber-9'}")
            generation_status_tooltip.text = (
                render_message("localization.generation.review.status_complete")
                if generation_complete
                else render_message(
                    "localization.generation.review.status_incomplete",
                    unpublished=generation["unpublished"],
                    quality=generation["quality_attention"],
                )
            )
            generation_status_tooltip.update()
            page["total"]=group_total;page["key_total"]=data["total"];results.clear()
            grouped: dict[str,list[dict[str,Any]]]={}
            for item in data["items"]: grouped.setdefault(item["context_group"],[]).append(item)
            filters_active = bool(
                (key_filter.value or "").strip()
                or (source_filter.value or "").strip()
                or (text_filter.value or "").strip()
                or (meaning_filter.value or "").strip()
                or status_filter.value != "all"
                or origin_filter.value != "all"
                or review_filter.value != "all"
                or attention_filter.value
            )
            with results:
                if not data["items"]: ui.label(render_message("webui.load_messages.label.no_translation_keys_match_these_filters_a6127ac6")).classes("w-full text-center text-sm text-slate-500 py-8")
                for group,items in grouped.items():
                    attention=sum(item["validity"]!="valid" for item in items)
                    context_heading = render_message("localization.administration.context_summary",context=group,count=len(items))
                    if attention:
                        context_heading += " · " + render_message("localization.administration.attention_summary",count=attention)
                    with ui.expansion(
                        context_heading,
                        icon="folder",
                        # A successful search must reveal the matching keys;
                        # requiring another click on a collapsed context made
                        # exact matches appear to be missing.
                        value=filters_active or group in expanded_contexts,
                        on_value_change=lambda event, context=group: set_translation_context_expanded(
                            context, bool(event.value)
                        ),
                    ).classes("w-full border border-slate-200 rounded-lg"):
                        with ui.row().classes("w-full justify-end px-2 pt-1"):
                            ui.button(icon="done_all",on_click=lambda _,scope=group:bulk_review_publish_dialog(scope,language_tag=administration_language["value"])).props(
                                'flat round dense aria-label=' + repr(render_message("webui.load_messages.accessible_name.review_and_publish_generated_drafts_in_thi_b0d0e30d"))
                            ).tooltip(render_message("localization.bulk.action.review_publish_context"))
                        for item in items:
                            card_classes="w-full shadow-none border p-3 gap-1 " + ("border-amber-300 bg-amber-50" if item["validity"]!="valid" else "border-slate-200")
                            with ui.card().classes(card_classes):
                                with ui.row().classes("w-full items-start gap-2 no-wrap"):
                                    if item["validity"]!="valid": ui.icon("warning_amber",color="amber-9",size="18px").props(f"aria-label={item['validity'].replace('_', ' ')!r}").tooltip(item["validity"].replace("_"," ").title())
                                    with ui.column().classes("gap-0 grow min-w-0"):
                                        ui.label(item["message_key"]).classes("font-mono text-xs font-semibold break-all")
                                        ui.label(item.get("translated_text") or render_message("localization.administration.no_translation")).classes("text-sm")
                                        ui.label(item["semantic_meaning"]).classes("text-xs text-slate-500 line-clamp-2")
                                    ui.button(icon="edit",on_click=lambda _,entry=item:edit_translation(entry)).props('flat round dense aria-label=' + repr(render_message("webui.load_messages.accessible_name.edit_translation_c3be8114"))).tooltip(render_message("webui.load_messages.tooltip.edit_translation_7e06ffab"))
            start=page["offset"]+1 if page["total"] else 0;end=min(page["offset"]+len(grouped),page["total"])
            result_summary.text=render_message("localization.administration.result_count",count=page["key_total"]);page_status.text=render_message("localization.administration.page_range",start=start,end=end,total=page["total"])
            previous_page.set_enabled(page["offset"]>0);next_page.set_enabled(page["offset"]+page["limit"]<page["total"])
            if restore_scroll is not None:
                await page_client.run_javascript(
                    "requestAnimationFrame(() => requestAnimationFrame(() => "
                    f"window.scrollTo({{top: {float(restore_scroll)}, behavior: 'auto'}})))"
                )

        def clear_all() -> None:
            key_filter.value="";source_filter.value="";text_filter.value="";meaning_filter.value="";status_filter.value="all";origin_filter.value="all";review_filter.value="all";attention_filter.value=False
            background_tasks.create(load_messages(True))

        async def select_administration_language(language_tag: str) -> None:
            if administration_language["value"] == language_tag:
                return
            administration_language["value"] = language_tag
            translation_state["translation_language"] = language_tag
            page["offset"] = 0
            for tag, card in language_cards.items():
                selected = tag == language_tag
                card.classes(
                    add="border-primary bg-blue-50" if selected else "border-slate-200",
                    remove="border-slate-200" if selected else "border-primary bg-blue-50",
                )
                card.props(f"aria-pressed={'true' if selected else 'false'}")
            await load_messages(True)

        for control in (key_filter,source_filter,text_filter,meaning_filter,status_filter,origin_filter,review_filter,attention_filter): control.on_value_change(lambda:load_messages(True))
        for tag, card in language_cards.items():
            card.on("click", lambda _, language_tag=tag: select_administration_language(language_tag))
        clear_filters.on("click",clear_all);add_language.on("click",language_dialog)
        export_artifact.on("click", lambda: export_artifact_dialog())
        import_artifact.on("click", import_artifact_dialog)
        bulk_publish_all.on(
            "click", lambda: bulk_review_publish_dialog(
                language_tag=administration_language["value"]
            )
        )
        generation_bulk_publish.on(
            "click", lambda: bulk_review_publish_dialog(
                language_tag=administration_language["value"]
            )
        )
        async def move_translation_page(delta: int) -> None:
            page["offset"] = max(0, page["offset"] + delta * page["limit"])
            await load_messages()
        previous_page.on("click",lambda:move_translation_page(-1))
        next_page.on("click",lambda:move_translation_page(1))
        await load_messages()


    return select_translation_administration
