"""One ordered multipart request and transaction for an aggregation file drop."""
from nicegui import ui
from nicegui.element import Element

from .api_client import ApiError
from .i18n_catalogue import render_message


class AggregationFileDrop(Element, component="aggregation_file_drop.js"):
    def __init__(self, *, page, aggregation, api, active, on_committed, error_message, direction="ltr"):
        super().__init__()
        self.aggregation, self.api, self.active = aggregation, api, active
        self.on_committed, self.error_message = on_committed, error_message
        self.direction = direction
        self.pending = None
        self.saving = False
        self._props.update(pageId=page.id, enabled=False, physical=aggregation.get("medium") == "physical")
        with self:
            self.uploader = ui.upload(multiple=True, on_multi_upload=self.save).classes("hidden")
        self._props["uploadUrl"] = self.uploader._props["url"]
        with self.add_slot("physical"), ui.card().classes("items-center p-6 text-center"):
            ui.icon("block", color="negative", size="32px")
            ui.label(render_message("aggregation_file_drop.physical"))
        with self.add_slot("single"):
            self.target("single", render_message("aggregation_file_drop.create_record"))
        with self.add_slot("multiple"), ui.grid().classes("grid-cols-1 sm:grid-cols-2 gap-6"):
            self.target("separate", render_message("aggregation_file_drop.separate"))
            self.target("combined", render_message("aggregation_file_drop.combined"))
        self.on("files-dropped", self.choose_role)
        self.on("upload-failed", self.upload_failed)

    def target(self, mode, label):
        with ui.card().classes("pointer-events-auto items-center justify-center p-8 text-center min-h-40").props(
            f"data-drop-mode={mode}",
        ):
            ui.icon("cloud_upload", color="primary", size="36px")
            ui.label(label).classes("font-semibold")

    def set_enabled(self, enabled):
        self._props["enabled"] = enabled
        self.update()

    def clear(self):
        self.pending = None
        if not self.is_deleted:
            self.run_method("clear")

    def upload_failed(self):
        if not self.saving:
            self.clear()
            if self.active():
                ui.notify(render_message("aggregation_file_drop.upload_failed"), color="negative", close_button=True)

    async def choose_role(self, event):
        if not self.active() or self.pending or self.saving:
            return
        if not self._props["enabled"] or self._props["physical"]:
            self.clear()
            return
        count = event.args.get("count")
        if not isinstance(count, int) or count < 1 or not isinstance(event.args.get("separate"), bool):
            self.clear()
            return
        confirm_title = count > 1 and not event.args["separate"]
        filenames = event.args.get("filenames")
        if confirm_title and (not isinstance(filenames, list) or len(filenames) != count
                              or any(not isinstance(name, str) or not name.strip() for name in filenames)):
            self.clear()
            return
        first_filename = filenames[0] if confirm_title else None
        self.pending = {"count": count, "separate": event.args["separate"], "role": None,
                        "title": first_filename if confirm_title else None, "confirmed": False,
                        "order": list(range(count))}
        try:
            roles = await self.api.creation_role_options()
        except ApiError as error:
            self.clear()
            if self.active():
                ui.notify(self.error_message(error), color="negative", close_button=True)
            return
        if not self.active():
            self.clear()
            return
        eligible = {role["role_id"]: role["label"] for role in roles
                    if role["org_unit_id"] == self.aggregation["owning_org_unit_id"]}
        if not eligible:
            self.clear()
            ui.notify(render_message("aggregation_file_drop.owning_role_required"), color="negative", close_button=True)
            return
        if len(eligible) == 1:
            self.pending["role"] = next(iter(eligible))
            if not confirm_title:
                self.pending["confirmed"] = True
                self.run_method("upload")
                return
        submitted = False
        dialog = ui.dialog()
        selector = title_input = None

        def valid():
            return ((selector is None or selector.value in eligible)
                    and (title_input is None or bool((title_input.value or "").strip())))

        def cancel():
            if not submitted:
                self.clear()

        def submit():
            nonlocal submitted
            if submitted or not self.active() or not self.pending or not valid():
                return
            submitted = True
            if selector is not None:
                self.pending["role"] = selector.value
            if title_input is not None:
                self.pending["title"] = title_input.value.strip()
            self.pending["confirmed"] = True
            dialog.close()
            self.run_method("upload")

        with dialog, ui.card().classes("w-[600px] max-w-full"):
            if confirm_title:
                title_input = ui.input(label=render_message("entity_metadata.field.title") + " *",
                                       value=first_filename).props("outlined").classes("w-full")
                ui.label(render_message("aggregation_file_drop.component_order")).classes("font-semibold")
                ui.label(render_message("aggregation_file_drop.reorder_hint")).classes("text-sm text-slate-600")
                rows = {}

                def move_file(file_index, step):
                    if submitted or not self.active() or not self.pending:
                        return
                    order = self.pending["order"]
                    position = order.index(file_index)
                    destination = position + step
                    if not 0 <= destination < len(order):
                        return
                    follows_filename = title_input.value == filenames[order[0]]
                    order[position], order[destination] = order[destination], order[position]
                    rows[file_index][0].move(target_index=destination)
                    for rank, index in enumerate(order):
                        _, badge, earlier, later = rows[index]
                        badge.set_text(str(rank + 1))
                        earlier.set_enabled(rank > 0)
                        later.set_enabled(rank < len(order) - 1)
                    if follows_filename:
                        title_input.set_value(filenames[order[0]])
                    pane.scroll_to(pixels=max(0, (destination - 4) * 56))

                # Keep the scroll widget's coordinates LTR, as in the ACL
                # matrix; give its content the actual language direction.
                with ui.scroll_area().props("dir=ltr").classes("w-full border rounded aggregation-drop-files").style(
                    # Include NiceGUI's native content padding and the border
                    # so five complete 56px rows fit without CSS overrides.
                    f"height: calc({min(count, 5) * 56 + 2}px + 2 * var(--nicegui-default-padding)); flex-shrink: 0",
                ) as pane:
                    with ui.column().props(f"dir={self.direction}").classes("w-full gap-0"):
                        for index, filename in enumerate(filenames):
                            # Native RTL flex flow already mirrors this row.
                            # Remove the legacy class that reverses it again.
                            with ui.row().classes("w-full h-14 min-h-14 items-center no-wrap gap-2 px-2 aggregation-drop-file", remove="row").props(
                                f"data-file-index={index}",
                            ) as row:
                                badge = ui.badge(str(index + 1)).props("outline").classes("shrink-0")
                                ui.label(filename).props("dir=auto").classes(
                                    "grow min-w-0 truncate aggregation-drop-filename "
                                    + ("text-right" if self.direction == "rtl" else "text-left")
                                ).tooltip(filename)
                                controls = []
                                for step, icon, key in (
                                    (-1, "arrow_upward", "webui.render_component_cards.tooltip.move_earlier_0de89c72"),
                                    (1, "arrow_downward", "webui.render_component_cards.tooltip.move_later_71077211"),
                                ):
                                    label = render_message(key)
                                    button = ui.button(icon=icon, on_click=lambda _, i=index, s=step: move_file(i, s)).props(
                                        f"flat round dense aria-label={label!r}",
                                    ).tooltip(label).classes("shrink-0")
                                    button.set_enabled(0 <= index + step < count)
                                    controls.append(button)
                                rows[index] = (row, badge, *controls)
            if len(eligible) > 1:
                selector = ui.select(eligible, label=render_message("webui.open_record_draft_editor.select.create_for_857b2d59")).props("outlined").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2", remove="row"):
                ui.button(render_message("common.action.cancel"), on_click=dialog.close).props("flat no-caps")
                create = ui.button(render_message(
                    "aggregation_file_drop.create_records" if count > 1 and event.args["separate"]
                    else "aggregation_file_drop.create_record"
                ), on_click=submit).props("no-caps")
                create.set_enabled(valid())
                for field in (title_input, selector):
                    if field is not None:
                        field.on_value_change(lambda _: create.set_enabled(valid()))
        dialog.on_value_change(lambda event: cancel() if not event.value else None)
        dialog.on("hide", dialog.delete)
        dialog.open()

    async def save(self, event):
        pending = self.pending
        if not self.active() or self.saving or not pending or pending["role"] is None or not pending["confirmed"]:
            for content in event.contents:
                content.close()
            return
        self.saving = True
        try:
            if len(event.names) != pending["count"]:
                ui.notify(render_message("aggregation_file_drop.upload_failed"), color="negative", close_button=True)
                return
            files = list(zip(event.names, event.contents, event.types, strict=True))
            count = await self.api.create_records_from_file_drop(
                self.aggregation["id"], [files[index] for index in pending["order"]],
                separate_records=pending["separate"], creator_acl_role_id=pending["role"],
                title=pending["title"],
            )
            if self.active():
                ui.notify(render_message("aggregation_file_drop.created", count=count), color="positive")
                await self.on_committed()
        except ApiError as error:
            if self.active():
                ui.notify(self.error_message(error), color="negative", close_button=True)
        finally:
            for content in event.contents:
                content.close()
            self.saving = False
            self.clear()
