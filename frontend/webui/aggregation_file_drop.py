"""One ordered multipart request and transaction for an aggregation file drop."""
import asyncio
from uuid import uuid4

from nicegui import background_tasks, ui
from nicegui.element import Element

from .api_client import ApiError
from .type_controls import MetadataForm, base
from .i18n_catalogue import render_message
from .creation_submission import CreationAttempt
from .upload_buffers import retain_upload_file


class AggregationFileDrop(Element, component="aggregation_file_drop.js"):
    def __init__(self, *, page, aggregation, api, active, on_committed, error_message, direction="ltr"):
        super().__init__()
        self.aggregation, self.api, self.active = aggregation, api, active
        self.on_committed, self.error_message = on_committed, error_message
        self.direction = direction
        self.pending = None
        self.saving = False
        self.retry_dialog = None
        self._props.update(pageId=page.id, enabled=False, physical=aggregation.get("medium") == "physical")
        with self:
            self.uploader = ui.upload(multiple=True, on_multi_upload=self.receive).classes("hidden")
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
        pending, self.pending = self.pending, None
        if not self.saving:
            self.release(pending)
        if pending and pending.get("dialog") is not None and not pending["dialog"].is_deleted:
            pending["dialog"].delete()
        if self.retry_dialog is not None and not self.retry_dialog.is_deleted:
            self.retry_dialog.close()
            self.retry_dialog.delete()
        self.retry_dialog = None
        if not self.is_deleted:
            self.run_method("clear")

    @staticmethod
    def release(pending):
        if pending:
            for _, content, _ in pending.pop("files", []):
                content.close()

    def _handle_delete(self):
        pending, self.pending = self.pending, None
        if not self.saving:
            self.release(pending)
        if pending and pending.get("dialog") is not None and not pending["dialog"].is_deleted:
            pending["dialog"].delete()
        super()._handle_delete()

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
                        "order": list(range(count)), "attempt": CreationAttempt()}
        try:
            roles, usable = await asyncio.gather(
                self.api.creation_role_options(),
                self.api.request("GET", base("record") + "/options", params={"access": "use", "limit": 1}),
            )
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
            if not confirm_title and not usable:
                self.pending["confirmed"] = True
                self.run_method("upload")
                return
        separate = count > 1 and event.args["separate"]
        if usable and (not isinstance(filenames, list) or len(filenames) != count
                       or any(not isinstance(name, str) or not name.strip() for name in filenames)):
            self.clear()
            return
        if filenames is not None:
            self.pending["filenames"] = filenames
        typed = MetadataForm(self.api, "record", filenames=filenames if separate else ()) if usable else None
        submitted = False
        dialog = ui.dialog()
        self.pending["dialog"] = dialog
        selector = title_input = create = None

        def valid():
            return ((selector is None or selector.value in eligible)
                    and (title_input is None or generated_title or bool((title_input.value or "").strip())))

        def cancel():
            if not submitted and self.pending is not None:
                self.clear()

        async def submit():
            nonlocal submitted
            if submitted or not self.active() or not self.pending or self.pending.get("confirming") or not valid():
                return
            pending = self.pending
            pending["confirming"] = True
            create.disable()
            try:
                if typed:
                    if not await refresh_hints(for_save=True) or not dialog.value:
                        return
                    self.pending["metadata"] = typed.payload()
                elif title_input is not None:
                    if not await refresh_hints() or not dialog.value:
                        return
                if not valid() or pending is not self.pending:
                    return
                submitted = True
                if selector is not None:
                    pending["role"] = selector.value
                if title_input is not None:
                    pending["title"] = title_input.value.strip()
                pending["confirmed"] = True
                dialog.close()
                if "files" in pending:
                    await self.send_pending()
                else:
                    self.run_method("upload")
            except (ValueError, ApiError) as error:
                if self.active():
                    ui.notify(str(error), color="warning")
            finally:
                pending["confirming"] = False
                if not submitted and not create.is_deleted:
                    create.set_enabled(valid())

        def edit_details():
            nonlocal submitted
            submitted = False
            self.pending["confirmed"] = False
            dialog.open()

        self.pending["edit_details"] = edit_details
        generated_title = False

        async def refresh_hints(*, for_save=False):
            nonlocal generated_title
            pending = self.pending
            selected = typed.selected if typed else None
            revisions = (typed.assignment_revision, typed.revision) if typed else None
            ids = list(typed.definitions if for_save else typed.page_field_ids) if typed else []
            chunks = [ids[i:i + 90] for i in range(0, len(ids), 90)] or [[]]
            pages = await asyncio.gather(*(self.api.code_generation_bindings("record",
                parent_aggregation_id=self.aggregation["id"], type_id=selected,
                field_ids=[int(fid) for fid in chunk], limit=100) for chunk in chunks))
            if (pending is not self.pending or not self.active() or typed and
                    (selected != typed.selected or revisions != (typed.assignment_revision, typed.revision))):
                return False
            rows = [item for page in pages for item in page["items"]]
            generated_title = any(item["primary_field"] == "title" for item in rows)
            if typed:
                typed.generated_fields.difference_update(ids)
                typed.generated_fields.update(str(item["field_id"]) for item in rows if item["field_id"])
            if create is not None and not create.is_deleted:
                create.set_enabled(valid())
            return True

        if typed:
            # MetadataForm requests only the visible page's field hints.
            typed.creation_bindings = SimpleDropBindings(refresh_hints, typed)

        with dialog, ui.card().classes("w-[600px] max-w-full"):
            if typed:
                ui.label(render_message("aggregation_file_drop.create_records" if separate else "aggregation_file_drop.create_record")).classes("text-lg font-semibold")
                ui.label(" · ".join(filter(None, (self.aggregation.get("aggregation_number"), self.aggregation.get("title")))))
                if len(eligible) == 1:
                    ui.label(render_message("webui.open_record_draft_editor.select.create_for_857b2d59") + " · " + next(iter(eligible.values())))
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
            if typed:
                if not separate and not confirm_title:
                    ui.label(filenames[0]).classes("font-semibold break-all").props("dir=auto")
                await typed.render()
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
        dialog.open()
        try:
            await refresh_hints()
        except ApiError as error:
            if self.active():
                ui.notify(self.error_message(error), color="negative", close_button=True)

    def receive(self, event):
        # NiceGUI dispatches async handlers after its upload route returns.
        # Retain its temporary files synchronously while that route owns them.
        if self.receive_files(event):
            async def create():
                if self.is_deleted or not self.active():
                    self.clear()
                    return
                with self.parent_slot:
                    await self.send_pending()
            background_tasks.create(create())

    async def save(self, event):
        """Awaitable entry point for callers already holding an upload event."""
        if self.receive_files(event):
            await self.send_pending()

    def receive_files(self, event):
        pending = self.pending
        if not self.active() or self.saving or not pending or pending["role"] is None or not pending["confirmed"]:
            for content in event.contents:
                content.close()
            return
        try:
            if (len(event.names) != pending["count"]
                    or ("filenames" in pending and list(event.names) != pending["filenames"])):
                ui.notify(render_message("aggregation_file_drop.upload_failed"), color="negative", close_button=True)
                self.clear()
                return
            if "files" in pending:
                return  # A duplicate upload callback cannot replace retry bytes.
            pending["files"], pending["file_identities"] = [], []
            # Own the files before the first await. Duplicating a disk file's
            # descriptor avoids copying/hashing a large upload on the UI loop.
            for name, source, mime in zip(event.names, event.contents, event.types, strict=True):
                content, size = retain_upload_file(source)
                pending["files"].append((name, content, mime))
                # These owned bytes cannot be edited by the form. Their stable
                # local identity distinguishes uploads with duplicate names.
                # The API fingerprints the actual ordered file checksums.
                pending["file_identities"].append({"name": name, "mime_type": mime, "size": size,
                                                    "upload_identity": str(uuid4())})
        except (OSError, ValueError):
            self.clear()
            if self.active():
                ui.notify(render_message("aggregation_file_drop.upload_failed"), color="negative", close_button=True)
            return
        finally:
            for content in event.contents:
                content.close()
        return True

    async def send_pending(self):
        pending = self.pending
        if self.saving or not pending or "files" not in pending or not self.active():
            return
        self.saving = True
        attempt = pending["attempt"]
        snapshot = (attempt.payload if attempt.uncertain or attempt.completed_error is not None else
                    {"order": pending["order"], "separate": pending["separate"], "role": pending["role"],
                     "title": pending["title"], "metadata": pending.get("metadata", {}),
                     "files": pending["file_identities"]})

        async def send(key, body):
            files = [pending["files"][index] for index in body["order"]]
            for _, content, _ in files:
                content.seek(0)
            return await self.api.create_records_from_file_drop(self.aggregation["id"], files,
                separate_records=body["separate"], creator_acl_role_id=body["role"], title=body["title"],
                **body["metadata"], submission_key=key)

        succeeded = False
        try:
            count = await attempt.submit(f"aggregation.{self.aggregation['id']}.file-drop", snapshot, send)
            succeeded = True
            if self.active() and not self.is_deleted and self.pending is pending:
                ui.notify(render_message("aggregation_file_drop.created", count=count), color="positive")
                await self.on_committed()
        except ApiError as error:
            if self.active() and not self.is_deleted and self.pending is pending:
                self.show_retry(error)
        finally:
            self.saving = False
            if succeeded or not self.active() or self.is_deleted or self.pending is not pending:
                self.release(pending)
                self.clear()

    def show_retry(self, error):
        if self.retry_dialog is not None and not self.retry_dialog.is_deleted:
            self.retry_dialog.delete()
        pending = self.pending
        attempt = pending["attempt"]
        unresolved = attempt.uncertain or attempt.completed_error is not None
        with ui.dialog().props("persistent") as dialog, ui.card().classes("w-[540px] max-w-full"):
            ui.label(self.error_message(error)).props("role=alert").classes("text-negative")
            ui.label(render_message("code_generation.status.files_retained"))
            if unresolved:
                ui.label(render_message("code_generation.error.unknown_outcome")).classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                if not unresolved:
                    ui.button(render_message("common.action.cancel"), on_click=self.clear).props("flat no-caps")
                    if pending.get("edit_details"):
                        def edit():
                            dialog.close()
                            pending["edit_details"]()
                        ui.button(render_message("code_generation.action.correct_details"), on_click=edit).props("flat no-caps")
                async def retry():
                    dialog.close()
                    await self.send_pending()
                ui.button(render_message("code_generation.action.retry_original"), on_click=retry).props("no-caps")
        self.retry_dialog = dialog
        dialog.open()


class SimpleDropBindings:
    """Adapter for the existing per-page metadata callback; no saved cache."""
    def __init__(self, refresh, typed):
        self.refresh, self.typed = refresh, typed

    def invalidate(self, *, schedule=True):
        self.typed.generated_fields.clear()
