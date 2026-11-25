"""Turn a Records collection drop into one editable, privately staged draft."""
from contextlib import ExitStack
import os
import re
from pathlib import PurePath

from nicegui import ui
from nicegui.element import Element

from .api_client import ApiError
from .i18n_catalogue import render_message


def suggested_title(names):
    words = [re.sub(r"[\s_.-]+", " ", PurePath(name).stem).split() for name in names]
    prefix = []
    for group in zip(*words):
        if len({word.casefold() for word in group}) != 1:
            break
        prefix.append(group[0])
    if len(names) > 1 and not any(any(c.isalpha() for c in w) and w.casefold() not in {"scan", "document", "file", "image"} for w in prefix):
        return ""
    title = " ".join(prefix)
    return title[:1].upper() + title[1:]


class RecordsDrop(Element, component="aggregation_file_drop.js"):
    def __init__(self, page, open_draft):
        super().__init__()
        self._props.update(pageId=page.id, collection=True, enabled=True)
        self.busy = False
        with self.add_slot("single"), ui.card().classes("items-center p-8"):
            ui.icon("cloud_upload", color="primary", size="36px")
            ui.label(render_message("records.collection.drop_files"))
        async def dropped(event):
            if self.busy or self.is_deleted:
                return
            files = event.args.get("files")
            if not isinstance(files, list) or not files or not all(
                isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"]
                and isinstance(f.get("size"), int) and f["size"] >= 0 and isinstance(f.get("type"), str)
                for f in files
            ):
                self.run_method("clear")
                return
            self.busy = True
            batch = DraftDrop(self, files)
            try:
                with self.client:
                    await open_draft(dropped=batch)
            finally:
                if not batch.opened:
                    batch.close()
        self.on("files-dropped", dropped)


class DraftDrop:
    def __init__(self, source, files):
        self.source = source
        self.files = files
        self.queue = list(range(len(files)))
        self.opened = False
        self.active = True
        self.running = False
        self.failure = None
        self.position = None

    def close(self):
        self.active = False
        self.source.busy = False
        if not self.source.is_deleted:
            self.source.run_method("clear")

    async def upload_file(self, api, draft_id, index):
        file = self.files[index]
        # NiceGUI supplies a temporary UploadFile. Duplicate its descriptor
        # before the request ends, so staging a large file does not copy all
        # its bytes into memory or block the UI loop copying it to another file.
        with ExitStack() as handles:
            stream = None

            def receive(event):
                nonlocal stream
                if self.active and stream is None and event.name == file["name"]:
                    stream = handles.enter_context(os.fdopen(os.dup(event.content.fileno()), "rb"))

            receiver = ui.upload(on_upload=receive).classes("hidden")
            try:
                sent = await self.source.run_method("transfer", index, receiver._props["url"], timeout=600)
                if not self.active:
                    return
                if not sent or stream is None or os.fstat(stream.fileno()).st_size != file["size"]:
                    raise OSError(render_message("aggregation_file_drop.upload_failed"))
                stream.seek(0)
                await api.upload_draft_component(draft_id, self.position, file["name"], stream, file["type"])
            finally:
                if not receiver.is_deleted:
                    receiver.delete()

    async def stage(self, api, draft_id, refresh, render, error_message):
        if self.running or not self.active:
            return
        self.running = True
        self.failure = None
        render()
        try:
            while self.queue and self.active:
                index = self.queue[0]
                file = self.files[index]
                rows = await api.draft_components(draft_id)
                # A lost acknowledgement may follow a successful upload. Keep the
                # position reserved until this file is staged or explicitly removed.
                if self.position is None:
                    self.position = max((r["component_order"] for r in rows), default=0) + 1
                prior = next((r for r in rows if r["component_order"] == self.position), None)
                if prior is None:
                    await self.upload_file(api, draft_id, index)
                    if not self.active:
                        return
                elif prior["file_name"] != file["name"] or prior["size_in_bytes"] != file["size"]:
                    raise OSError(render_message("aggregation_file_drop.upload_failed"))
                self.queue.pop(0)
                self.position = None
                if self.active:
                    await refresh()
                    render()
        except (ApiError, OSError, TimeoutError) as error:
            self.failure = error_message(error) if isinstance(error, ApiError) else str(error)
        finally:
            self.running = False
            if self.active:
                render()
