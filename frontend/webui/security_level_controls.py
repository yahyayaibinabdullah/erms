"""Security-level selectors and governed changes; each control retains its own request state."""
from __future__ import annotations

from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
import asyncio
import json
from html import escape as html_escape
from nicegui import background_tasks
from .entity_selectors import relationship_options, relationship_search_query
from .relationship_select import relationship_select


def build_security_selector(
    api, *, error_message: Callable,
):
    def bind_resource_security_select(
        control: Any, *, parent_control: Any = None,
        parent_id: int | None = None, aggregation_id: int | None = None,
    ) -> Callable[..., Any]:
        """Keep resource choices within freshly evaluated server-side bounds."""
        revision = 0
        search_task: Any = None
        hint = render_message_plain("security_level.selection.constraints")
        # A normal-flow NiceGUI label reserves space for wrapped guidance;
        # the select's native hint overlaps the next field at narrow widths.
        with ui.column().classes("w-full min-w-0 gap-1") as field_group:
            control.move(field_group)
            ui.label(hint).classes("w-full text-xs text-slate-500 leading-relaxed")

        async def load(query: str = "") -> None:
            nonlocal revision
            if control.is_deleted:
                return
            revision += 1
            current = revision
            selected = control.value
            try:
                page = await api.administration_reference_page(
                    "security-levels", query=query, sort="level_number", limit=25,
                    filters={"assignable": True,
                             "parent_aggregation_id": parent_control.value if parent_control else parent_id,
                             "aggregation_id": aggregation_id},
                )
                if "maximum_level" not in page or "minimum_level" not in page:
                    # An older API ignores assignable=true and returns unfiltered
                    # choices. Never interpret missing bounds as unrestricted.
                    raise ApiError(503, {"message_key": "shared.errors.unexpected"})
                rows = list(page["items"])
                if selected is not None and selected not in {item["id"] for item in rows}:
                    rows.append(await api.get("security-levels", int(selected)))
                if current != revision or control.is_deleted or control.value != selected:
                    return
                maximum, minimum = page["maximum_level"], page["minimum_level"]
                rows = [item for item in rows if maximum is not None
                        and item["level_number"] <= maximum
                        and (minimum is None or item["level_number"] >= minimum)]
                with control:
                    options = relationship_options(rows, ("code", "name"), include_level_number=True)
                control.set_options(options, value=selected if selected in options else None)
                control.enable()
            except ApiError as error:
                if current != revision or control.is_deleted:
                    return
                control.set_options({}, value=None)
                with control:
                    ui.notify(error_message(error), color="negative", close_button=True)

        def search(event: Any) -> None:
            nonlocal search_task, revision
            query = relationship_search_query(control, event.args)
            if query is not None:
                revision += 1
                if search_task is not None and not search_task.done():
                    search_task.cancel()
                async def delayed() -> None:
                    await asyncio.sleep(0.2)
                    if not control.is_deleted:
                        await load(query)
                search_task = background_tasks.create(delayed())

        control.disable()
        control.on("input-value", search)
        control.on("popup-show", lambda: background_tasks.create(load()))
        if parent_control is not None:
            parent_control.on_value_change(lambda: background_tasks.create(load()))
        background_tasks.create(load())
        return load


    return bind_resource_security_select


def build_security_level_change(
    api, *, bind_remote_relationship_select: Callable, error_message: Callable,
):
    async def show_security_level_change(
        resource_type: str, resource: dict[str, Any], on_saved: Any,
    ) -> None:
        try:
            levels = [await api.get("security-levels", int(resource["security_level_id"]))]
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        options = relationship_options(
            levels, ("code", "name"), include_level_number=True,
        )
        dialog = ui.dialog().props("persistent")
        preview_state: dict[str, Any] = {}
        with dialog, ui.card().classes("w-[620px] max-w-[calc(100vw-32px)]"):
            ui.label(render_message("webui.show_security_level_change.label.change_security_level_b3ecad36")).classes("text-xl font-semibold")
            ui.label(
                render_message("webui.show_security_level_change.label.this_governed_action_remains_available_whe_7b7f9891")
            ).classes("text-sm text-slate-500")
            target = relationship_select(
                render_message_plain("webui.show_security_level_change.select.security_level_2a839288"),
                options, value=resource["security_level_id"], required=True,
            )
            bind_remote_relationship_select(
                target,
                resource="security-levels",
                search_fields=("code", "name"),
                label_fields=("code", "name"),
            )
            remedy_options = {
                "none": render_message("webui.show_security_level_change.text.change_only_this_resource_338bd39b"),
                "raise_ancestors": render_message("webui.show_security_level_change.text.also_raise_parent_aggregations_as_needed_8cd69521"),
                "downgrade_subtree": render_message("webui.show_security_level_change.text.also_lower_contained_resources_as_needed_e69b8640"),
            }
            remedy_descriptions = {
                "none": render_message_plain("webui.security_level_remedy.description.none"),
                "raise_ancestors": render_message_plain("webui.security_level_remedy.description.raise_ancestors"),
                "downgrade_subtree": render_message_plain("webui.security_level_remedy.description.downgrade_subtree"),
            }
            remedy = ui.select(
                remedy_options, value="none", label=render_message("webui.show_security_level_change.select.hierarchy_remedy_925ecf92"),
            ).props(
                'outlined options-dense '
                'popup-content-style="width:572px;max-width:calc(100vw - 64px)"'
            ).classes("w-full")
            remedy.add_slot("option", """
                <q-item v-bind="props.itemProps" class="q-py-sm" style="width:100%; max-width:100%;">
                  <q-item-section style="min-width:0; max-width:100%;">
                    <q-item-label class="text-weight-medium" style="white-space:normal; overflow-wrap:anywhere;">{{ props.opt.label }}</q-item-label>
                    <q-item-label caption style="white-space:normal; overflow-wrap:anywhere; line-height:1.35;">
                      {{ __REMEDY_DESCRIPTIONS__[props.opt.value] }}
                    </q-item-label>
                  </q-item-section>
                </q-item>
            """.replace("__REMEDY_DESCRIPTIONS__", html_escape(json.dumps(list(remedy_descriptions.values()), ensure_ascii=False), quote=True)))
            remedy_description = ui.label(remedy_descriptions["none"]).classes(
                "-mt-2 px-3 text-xs leading-relaxed text-slate-500"
            )
            reason = ui.textarea(render_message("webui.show_security_level_change.textarea.reason_d03ff5f6")).props("outlined autogrow maxlength=2000").classes("w-full")
            impact = ui.column().classes("w-full gap-1 rounded-lg bg-slate-50 p-3")
            apply_button: Any = None

            def invalidate_preview() -> None:
                preview_state.clear()
                impact.clear()
                with impact:
                    ui.label(render_message("webui.invalidate_preview.label.review_the_change_before_applying_it_47fa0daa")).classes("text-sm text-slate-500")
                if apply_button is not None:
                    apply_button.disable()

            async def review() -> None:
                if target.value == resource["security_level_id"]:
                    ui.notify(render_message("webui.review.notify.choose_a_different_security_level_be7a0438"), color="warning")
                    return
                try:
                    preview = await api.preview_security_level_change({
                        "resource_type": resource_type,
                        "resource_id": resource["id"],
                        "target_security_level_id": int(target.value),
                        "remedy": remedy.value,
                    })
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)
                    return
                preview_state.clear(); preview_state.update(preview)
                impact.clear()
                with impact:
                    if preview["conflict"] and remedy.value == "none":
                        ui.label(render_message("webui.review.label.this_change_conflicts_with_the_security_le_fe1be5fd")).classes("text-sm font-medium text-negative")
                    else:
                        ui.label(render_message("webui.review.label.security_level_change_reviewed_96f32743")).classes("text-sm font-semibold")
                        affected = len(preview["affected_aggregations"]) + len(preview["affected_records"])
                        ui.label(
                            render_message(
                                "webui.review.label.related_resources_affected",
                                count=affected,
                            )
                        ).classes("text-xs text-slate-600")
                apply_button.set_enabled(not preview["conflict"] or remedy.value != "none")

            async def apply_change() -> None:
                change_reason = (reason.value or "").strip()
                if not change_reason:
                    ui.notify(render_message("webui.apply_change.notify.a_reason_is_required_4346f523"), color="warning")
                    return
                if not preview_state:
                    ui.notify(render_message("webui.apply_change.notify.review_the_change_before_applying_it_1d5df14d"), color="warning")
                    return
                try:
                    result = await api.apply_security_level_change({
                        "resource_type": resource_type,
                        "resource_id": resource["id"],
                        "target_security_level_id": int(target.value),
                        "remedy": remedy.value,
                        "reviewed_versions": preview_state["reviewed_versions"],
                    }, reason=change_reason)
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)
                    return
                dialog.close()
                ui.notify(render_message("webui.apply_change.notify.security_level_changed_ae3a3c4b"), color="positive")
                await on_saved(result["resource"])

            target.on_value_change(lambda _: invalidate_preview())
            def remedy_changed() -> None:
                remedy_description.set_text(remedy_descriptions.get(remedy.value, ""))
                invalidate_preview()

            remedy.on_value_change(lambda _: remedy_changed())
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.show_security_level_change.button.cancel_d37961e9"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_security_level_change.button.review_change_e13907fc"), icon="fact_check", on_click=review).props("outline no-caps")
                apply_button = ui.button(render_message("webui.show_security_level_change.button.apply_change_aee38579"), icon="security", on_click=apply_change).props("unelevated no-caps")
                apply_button.disable()
            invalidate_preview()
        dialog.open()


    return show_security_level_change
