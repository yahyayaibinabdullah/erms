"""On-demand transfer controls. No catalogue/data prefetch at page load."""

from nicegui import ui
from .api_client import ApiError
from .classification_labels import classification_title
from .i18n_catalogue import render_message

MAX_BYTES = 32 * 1024 * 1024


def import_dialog(api, active, refresh, error_message):
    selected = {}
    busy = False
    dialog = ui.dialog()
    with (
        dialog,
        ui.card().classes("classification-transfer-dialog w-[520px] max-w-full gap-4"),
    ):
        ui.label(render_message("classification_transfer.import_title")).classes(
            "text-xl font-semibold"
        )
        ui.label(render_message("classification_transfer.import_hint"))
        problem = ui.label().classes("text-negative")

        def clear_selection():
            selected.clear()
            confirm.disable()

        def rejected():
            clear_selection()
            problem.text = render_message(
                "classification_transfer.error.invalid_package"
            )

        async def uploaded(event):
            content = event.content.read(MAX_BYTES + 1)
            name = event.name
            kind = name.rsplit(".", 1)[-1].lower()
            if len(content) > MAX_BYTES or kind not in ("json", "csv"):
                problem.text = render_message(
                    "classification_transfer.error.invalid_package"
                )
                selected.clear()
                confirm.disable()
                return
            selected.update(content=content, name=name, kind=kind)
            problem.text = ""
            confirm.enable()

        upload = (
            ui.upload(
                on_upload=uploaded,
                on_rejected=rejected,
                auto_upload=True,
                max_file_size=MAX_BYTES,
                max_files=1,
                label=render_message("classification_transfer.choose_file"),
            )
            .props('accept=".json,.csv"')
            .classes("w-full")
        )
        upload.on("removed", clear_selection)

        async def submit():
            nonlocal busy
            if busy or not selected or not active():
                return
            busy = True
            confirm.disable()
            upload.disable()
            confirm.props("loading")
            try:
                await api.request(
                    "POST",
                    "/api/v1/classification-schemes/import",
                    params={"format": selected["kind"]},
                    files={
                        "file": (
                            selected["name"],
                            selected["content"],
                            "application/octet-stream",
                        )
                    },
                )
                dialog.close()
                if active():
                    ui.notify(
                        render_message("classification_transfer.success"),
                        color="positive",
                    )
                    await refresh()
            except ApiError as error:
                if active():
                    problem.text = error_message(error)
            finally:
                busy = False
                if active():
                    confirm.props(remove="loading")
                    if selected:
                        confirm.enable()
                    upload.enable()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(
                render_message("classification_transfer.cancel"), on_click=dialog.close
            ).props("flat no-caps")
            confirm = ui.button(
                render_message("classification_transfer.import"), on_click=submit
            ).props("unelevated no-caps")
            confirm.disable()
    dialog.open()


def export_control(api, scheme, active, error_message):
    busy = False
    # Own the dialog in the details panel, outside the transient export menu.
    word_dialog = ui.dialog()

    async def download(kind, language=None, dialog=None, trigger=None):
        nonlocal busy
        if busy or not active():
            return
        busy = True
        button.disable()
        button.props("loading")
        if trigger:
            trigger.disable()
            trigger.props("loading")
        try:
            content = await api.request(
                "GET",
                f"/api/v1/classification-schemes/{scheme['id']}/export",
                params={"format": kind, **({"language": language} if language else {})},
            )
            if active():
                ui.download(
                    content, filename=f"classification-scheme-{scheme['id']}.{kind}"
                )
                if dialog:
                    dialog.close()
        except ApiError as error:
            if active():
                ui.notify(error_message(error), color="negative", close_button=True)
        finally:
            busy = False
            if active():
                button.props(remove="loading")
                button.enable()
                if trigger:
                    trigger.props(remove="loading")
                    trigger.enable()

    async def word():
        try:
            bootstrap = await api.localization_bootstrap()
        except ApiError as error:
            if active():
                ui.notify(error_message(error), color="negative")
                return
        if not active():
            return
        dialog = word_dialog
        dialog.clear()
        with (
            dialog,
            ui.card().classes(
                "classification-transfer-dialog w-[520px] max-w-full gap-4"
            ),
        ):
            ui.label(render_message("classification_transfer.word_title")).classes(
                "text-xl font-semibold"
            )
            ui.label(scheme["code"] + " — " + classification_title(scheme))
            languages = {
                item["language_tag"]: item["native_name"]
                for item in bootstrap["supported_languages"]
            }
            language = (
                ui.select(
                    languages,
                    value=bootstrap["effective_language"],
                    label=render_message("classification_transfer.language"),
                )
                .props("outlined")
                .classes("w-full")
            )
            ui.label(render_message("classification_transfer.landscape"))
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(
                    render_message("classification_transfer.cancel"),
                    on_click=dialog.close,
                ).props("flat no-caps")
                download_button = ui.button(
                    render_message("classification_transfer.download"),
                    on_click=lambda: download(
                        "docx", language.value, dialog, download_button
                    ),
                ).props("unelevated no-caps")
        dialog.open()

    with ui.button(
        render_message("classification_transfer.export"), icon="download"
    ).props("outline dense no-caps") as button:
        with ui.menu():
            ui.menu_item("JSON", on_click=lambda: download("json"))
            ui.menu_item("CSV", on_click=lambda: download("csv"))
            ui.menu_item("MS Word", on_click=word)
