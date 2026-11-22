"""Paged administration of aggregation and record metadata definitions."""

from copy import deepcopy
from html import escape

from nicegui import ui

from .api_client import ApiError
from .entity_translation_editor import entity_translation_editor
from .resource_relationships import PageTable
from .type_controls import (
    base,
    col,
    confirmed,
    find_option,
    label,
    literal,
    scalar_input,
    selector,
    t,
)

DATA_TYPES = (
    "text",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "single_choice",
)


async def type_administration(*, api, kind, container, languages, active, on_error):
    root = base(kind)
    with container:
        host = ui.column().classes("messaging-workspace w-full p-5 gap-3")

    def alive():
        return active() and not host.is_deleted

    async def listing(level, path, owner=None, field=None, dialog=None):
        def current():
            return alive() and (dialog is None or dialog.value)

        async def submit():
            nonlocal submitted
            submitted = (search.value or "").strip()
            await page.load(reset=True)

        submitted = ""
        with ui.row().classes("w-full items-center"):
            search = (
                ui.input(t("search")).props("outlined dense clearable").classes("grow")
            )
            search.on("keydown.enter", submit)
            ui.button(t("search"), icon="search", on_click=submit).props(
                "outline no-caps"
            )
            if level != "access":
                ui.button(t("add"), icon="add", on_click=lambda: edit({})).props(
                    "outline no-caps"
                )

        async def fetch(p):
            result = await api.request(
                "GET",
                path,
                params={
                    "paged": True,
                    "q": submitted,
                    "limit": p.size,
                    "offset": (p.page - 1) * p.size,
                    "sort": p.sort
                    or ("display_order" if level in {"field", "choice"} else "name"),
                    "descending": p.descending,
                },
            )
            for row in result["items"]:
                row["display_name"] = label(row)
                if level == "field":
                    row["display_type"] = t(row["data_type"])
                if level == "access":
                    row["see"] = t("yes" if row["can_see"] else "no")
                    row["use"] = t("yes" if row["can_use"] else "no")
            return result

        columns = [dict(col("name", "name", True), field="display_name")]
        if level in {"field", "choice"}:
            columns.append(col("display_order", "order", True))
        if level == "field":
            columns.append(col("display_type", "data_type"))
        if level == "access":
            columns.extend([col("see", "see"), col("use", "use")])
        columns.append(dict(col("actions", "edit"), label=""))
        page = PageTable(
            columns=columns,
            fetch=fetch,
            active=current,
            on_error=on_error,
            empty="",
            empty_text=lambda: t("empty"),
        )
        actions = [("edit", "edit")]
        if level == "type":
            actions.extend([("fields", "list"), ("access", "groups")])
        if level == "field":
            actions.append(("choices", "format_list_bulleted"))
        if level != "access":
            actions.append(("delete", "delete_outline"))
        buttons = []
        for action, icon in actions:
            visible = (
                """v-if="props.row.data_type === 'single_choice'" """
                if action == "choices"
                else ""
            )
            caption = escape(t(action))
            buttons.append(
                f'<q-btn {visible}flat dense icon="{icon}" aria-label="{caption}" '
                f"@click=\"$parent.$emit('act', ['{action}', props.row.id])\">"
                f"<q-tooltip>{caption}</q-tooltip></q-btn>"
            )
        page.table.add_slot(
            "body-cell-actions",
            '<q-td :props="props"><div class="row no-wrap">'
            + "".join(buttons)
            + "</div></q-td>",
        )

        async def act(event):
            action, identity = event.args
            row = next((r for r in page.table.rows if r["id"] == identity), None)
            if row is None or not current():
                return
            if action == "edit":
                await edit(row)
            elif action == "delete":
                version = (owner or row)["version"]
                if not await confirmed("delete_confirm") or not current():
                    return
                try:
                    await api.request(
                        "DELETE",
                        f"{path}/{identity}",
                        headers={"If-Match": str(version)},
                    )
                    if owner:
                        refreshed = await api.request("GET", f"{root}/{owner['id']}")
                        owner.update(refreshed)
                    await page.load()
                except ApiError as error:
                    ui.notify(on_error(error), color="negative")
            else:
                selected_owner = owner or row
                suffix = "role-options" if action == "access" else action
                with (
                    ui.dialog() as child,
                    ui.card().classes("messaging-workspace w-full max-w-4xl"),
                ):
                    ui.label(f"{label(row)} · {t(action)}").classes(
                        "text-lg font-semibold"
                    )
                    if action == "access":
                        ui.label(t("policy_help"))
                    panel = ui.column().classes("w-full")
                    ui.button(t("close"), on_click=child.close).props("flat no-caps")
                child.open()
                with panel:
                    await listing(
                        {"fields": "field", "choices": "choice", "access": "access"}[
                            action
                        ],
                        f"{path}/{identity}/{suffix}",
                        selected_owner,
                        row if action == "choices" else None,
                        child,
                    )

        page.table.on("act", act)

        async def edit(row):
            if not current():
                return
            version = (owner or row).get("version")
            with (
                ui.dialog() as editor,
                ui.card().classes("messaging-workspace w-full max-w-xl"),
            ):
                ui.label(f"{t('edit' if row else 'add')} · {t(level)}").classes(
                    "text-lg font-semibold"
                )
                if level == "access":
                    ui.label(label(row))
                    see = ui.checkbox(t("see"), value=row["can_see"])
                    use = ui.checkbox(t("use"), value=row["can_use"])
                    use.on_value_change(
                        lambda e: see.set_value(True) if e.value else None
                    )
                    see.on_value_change(
                        lambda e: use.set_value(False) if not e.value else None
                    )
                else:
                    name = (
                        ui.input(t("name"), value=row.get("name", ""))
                        .props("outlined")
                        .classes("w-full")
                    )
                    if level == "type":
                        description = (
                            ui.textarea(
                                t("description"), value=row.get("description") or ""
                            )
                            .props("outlined autogrow")
                            .classes("w-full")
                        )
                    translations = deepcopy(row.get("translations") or {})
                    stage = await entity_translation_editor(
                        api,
                        resource=kind,
                        row=row,
                        fields=(
                            ("name", "description") if level == "type" else ("name",)
                        ),
                        languages=languages,
                        dialog=editor,
                        uses_external_reason=False,
                        get_external_reason=lambda: None,
                        error_message=on_error,
                        show_api_error=lambda error: ui.notify(
                            on_error(error), color="negative"
                        ),
                        definition_translations=translations,
                    )
                if level in {"field", "choice"}:
                    order = ui.number(
                        t("order"),
                        value=row.get("display_order", 1),
                        step=1,
                        precision=0,
                    )
                if level == "field":
                    data_type = ui.select(
                        {s: t(s) for s in DATA_TYPES},
                        label=t("data_type"),
                        value=row.get("data_type", "text"),
                    ).classes("w-full")
                    required = ui.checkbox(
                        t("required"), value=row.get("required", False)
                    )
                    ui.label(t("required_help")).bind_visibility_from(required, "value")
                    maximum = ui.number(
                        t("maximum"),
                        min=1,
                        step=1,
                        precision=0,
                        value=row.get("max_length") or 255,
                    )
                    maximum.bind_visibility_from(
                        data_type, "value", backward=lambda v: v == "text"
                    )
                    default_box = ui.column().classes("w-full")
                    choice_value = (
                        row.get("default")
                        if row.get("data_type") == "single_choice"
                        else None
                    )
                    default_control = None

                    async def default_editor():
                        nonlocal default_control, choice_value
                        default_box.clear()
                        dtype = data_type.value
                        initial = (
                            row.get("default")
                            if dtype == row.get("data_type")
                            else None
                        )
                        with default_box:
                            if dtype != "single_choice":
                                default_control = scalar_input(
                                    dtype,
                                    t("default"),
                                    initial,
                                    int(maximum.value or 255),
                                )
                            elif row and row["data_type"] == "single_choice":
                                choices_path = f"{path}/{row['id']}/choices"
                                selected = (
                                    await find_option(
                                        api, choices_path, choice_value, "see"
                                    )
                                    if choice_value is not None
                                    else None
                                )
                                if default_box.is_deleted or dtype != data_type.value:
                                    return

                                def choose(option):
                                    nonlocal choice_value
                                    choice_value = option["id"] if option else None

                                selector(
                                    api, choices_path, t("default"), selected, choose
                                )
                            else:
                                ui.label(t("default_choice"))

                    def resize_text_default():
                        nonlocal default_control
                        if data_type.value != "text" or default_control is None:
                            return
                        maximum_size = int(maximum.value or 255)
                        if isinstance(default_control, ui.textarea) == (maximum_size > 255):
                            return
                        value = default_control.value
                        default_box.clear()
                        with default_box:
                            default_control = scalar_input("text", t("default"), value, maximum_size)
                    maximum.on_value_change(resize_text_default)
                    data_type.on_value_change(default_editor)
                    await default_editor()
                feedback = ui.label("").classes("text-negative").props("role=alert")

                async def save():
                    if not current() or not editor.value:
                        return
                    button.disable()
                    try:
                        creating = not row
                        target = path if creating else f"{path}/{row['id']}"
                        if level == "access":
                            target = f"{root}/{owner['id']}/role-grants/{row['id']}"
                            body = {"can_see": see.value, "can_use": use.value}
                        else:
                            stage()
                            body = {
                                "name": (name.value or "").strip(),
                                "translations": translations,
                            }
                            if not body["name"]:
                                raise ValueError(t("invalid"))
                            if level == "type":
                                body["description"] = description.value or None
                            else:
                                body["display_order"] = int(order.value)
                            if level == "field":
                                dtype = data_type.value
                                length = int(maximum.value) if dtype == "text" else None
                                body.update(
                                    data_type=dtype,
                                    required=required.value,
                                    max_length=length,
                                    default=(
                                        choice_value
                                        if dtype == "single_choice"
                                        else literal(
                                            dtype, default_control.value, length
                                        )
                                    ),
                                )
                        headers = (
                            {"If-Match": str(version)} if version is not None else {}
                        )
                        saved = await api.request(
                            "POST" if creating else "PUT",
                            target,
                            json=body,
                            headers=headers,
                        )
                        if owner:
                            owner["version"] = saved[
                                "version" if level == "access" else "type_version"
                            ]
                    except (ValueError, TypeError, ApiError) as error:
                        if editor.value and current():
                            feedback.text = (
                                (t("conflict") if error.status_code == 412 else on_error(error))
                                if isinstance(error, ApiError)
                                else t("invalid")
                            )
                            button.enable()
                        return
                    editor.close()
                    if current():
                        await page.load(reset=creating)

                with ui.row().classes("w-full justify-end"):
                    ui.button(t("cancel"), on_click=editor.close).props("flat no-caps")
                    button = ui.button(t("save"), on_click=save).props(
                        "unelevated no-caps"
                    )
            editor.open()

        await page.load()

    with host:
        ui.label(t("admin_help"))
        await listing("type", root)
