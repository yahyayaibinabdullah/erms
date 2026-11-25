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


MAX_INT32 = 2_147_483_647  # PostgreSQL integer


def _positive_integer(value: str | None, upper_bound: int) -> int | None:
    digits = (value or "").strip()
    if not digits.isdecimal():
        return None
    try:
        limit = int(digits)
    except ValueError:  # Excessively long pasted numbers.
        return None
    return limit if 1 <= limit <= upper_bound else None


def _integer_input(title: str, value: int, upper_bound: int, *, select_initial: bool, lower_bound: int = 1):
    control = (
        ui.input(title, value=str(value))
        .props(f"outlined dense type=number inputmode=numeric min={lower_bound} max={upper_bound} step=1")
        .classes("w-full")
    )
    # Native number inputs allow signs, decimal points and exponents while editing.
    for event_name in ("beforeinput", "paste", "drop"):
        control.on(event_name, js_handler=r"""event => {
            event.target.dataset.acceptedValue = event.target.value;
            const text = event.data ?? (event.clipboardData ?? event.dataTransfer)?.getData('text/plain');
            if (!text) return;
            const signed = Number(event.target.min) < 0;
            const allowed = signed ? /^-?\p{Nd}*$/u : /^\p{Nd}+$/u;
            const field = event.target;
            const replacingValue = !field.value || window.getSelection()?.toString() === field.value;
            field.dataset.editingMinus = String(signed && text === '-' && replacingValue && !field.validity.badInput);
            if (!allowed.test(text) || (text === '-' && event.target.validity.badInput)) event.preventDefault();
        }""")
    # Number inputs do not expose selection offsets. Let the browser apply
    # the complete edit, then restore the previous value before Quasar sees it.
    control.on("input.capture", js_handler="""event => {
        const field = event.target;
        if (!field.validity.valid && !(field.validity.badInput && field.dataset.editingMinus === 'true')) {
            field.value = field.dataset.acceptedValue ?? field.defaultValue;
        }
        field.dataset.acceptedValue = field.value;
    }""")
    if select_initial:
        # First keyboard entry replaces the suggested value.
        control.on("focus.once", js_handler="event => event.target.select()")
    return control


async def _add_role_grants(api, type_path, owner, grants_page, current, on_error):
    version = owner["version"]
    selected = {}
    submitted = ""
    saving = False

    with ui.dialog() as dialog, ui.card().classes("messaging-workspace w-full max-w-4xl"):
        ui.label(f"{t('add')} · {t('access')}").classes("text-lg font-semibold")

        async def search():
            nonlocal submitted
            submitted = (query.value or "").strip()
            await page.load(reset=True)

        with ui.row().classes("w-full items-center"):
            query = ui.input(t("search")).props("outlined dense clearable autofocus").classes("grow")
            query.on("keydown.enter", search)
            ui.button(t("search"), icon="search", on_click=search).props("outline no-caps")

        async def fetch(p):
            result = await api.request("GET", f"{type_path}/role-options", params={
                "scope": "available", "q": submitted, "limit": p.size,
                "offset": (p.page - 1) * p.size, "descending": p.descending,
            })
            for row in result["items"]:
                row.update(display_name=label(row), selected=row["id"] in selected, use=selected.get(row["id"], False))
            return result

        page = PageTable(columns=[col("selected", "select"), col("display_name", "name", True),
                                  col("see", "see"), col("use", "use")],
                         fetch=fetch, active=lambda: dialog.value and current(), on_error=on_error,
                         empty="", empty_text=lambda: t("empty"), wrap_cells=True)
        page.table.add_slot("body-cell-selected", f"""
            <q-td :props="props"><q-checkbox :model-value="props.row.selected"
                aria-label="{escape(t('select'))}" :aria-description="props.row.display_name"
                @update:model-value="props.row.selected=$event; props.row.use=false;
                    $parent.$emit('grant_change', [props.row.id, $event, false])"/></q-td>""")
        page.table.add_slot("body-cell-see", f"""
            <q-td :props="props"><q-checkbox :model-value="props.row.selected" disable
                aria-label="{escape(t('see'))}" :aria-description="props.row.display_name"/></q-td>""")
        page.table.add_slot("body-cell-use", f"""
            <q-td :props="props"><q-checkbox :model-value="props.row.use" :disable="!props.row.selected"
                aria-label="{escape(t('use'))}" :aria-description="props.row.display_name"
                @update:model-value="props.row.use=$event;
                    $parent.$emit('grant_change', [props.row.id, props.row.selected, $event])"/></q-td>""")

        def change(event):
            if saving or not dialog.value:
                return
            identity, is_selected, use = event.args
            if is_selected:
                selected[identity] = use
            else:
                selected.pop(identity, None)
            button.set_text(f"{t('add')} ({len(selected)})")
            button.set_enabled(bool(selected))

        page.table.on("grant_change", change)
        feedback = ui.label("").classes("text-negative").props("role=alert")

        async def save():
            nonlocal saving
            if saving or not selected or not current() or not dialog.value:
                return
            saving = True
            button.disable()
            try:
                result = await api.request("POST", f"{type_path}/role-grants",
                    headers={"If-Match": str(version)},
                    json=[{"role_id": identity, "can_use": use} for identity, use in selected.items()])
                owner["version"] = result["version"]
            except ApiError as error:
                if error.status_code not in (409, 412):
                    feedback.text = on_error(error)
                    return
                ui.notify(t("conflict") if error.status_code == 412 else on_error(error), color="negative")
                try:
                    owner.update(await api.request("GET", type_path))
                except ApiError as refresh_error:
                    feedback.text = on_error(refresh_error)
                    return
            finally:
                saving = False
                button.set_enabled(bool(selected))
            dialog.close()
            if current():
                await grants_page.load(reset=True)

        with ui.row().classes("w-full justify-end"):
            ui.button(t("cancel"), on_click=dialog.close).props("flat no-caps")
            button = ui.button(f"{t('add')} (0)", icon="group_add", on_click=save).props("unelevated no-caps")
            button.disable()
    dialog.open()
    await page.load()


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

        async def add_grant():
            await _add_role_grants(api, f"{root}/{owner['id']}", owner, page, current, on_error)

        submitted = ""
        with ui.row().classes("w-full items-center"):
            search = (
                ui.input(t("search")).props("outlined dense clearable").classes("grow")
            )
            search.on("keydown.enter", submit)
            ui.button(t("search"), icon="search", on_click=submit).props(
                "outline no-caps"
            )
            if level == "access":
                ui.button(t("add"), icon="group_add", on_click=add_grant).props("outline no-caps")
            else:
                ui.button(t("add"), icon="add", on_click=lambda: edit({})).props(
                    "outline no-caps"
                )

        async def fetch(p):
            result = await api.request(
                "GET",
                path,
                params={
                    "paged": True,
                    **({"scope": "granted"} if level == "access" else {}),
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
                    row["show_moves"] = not submitted and p.sort in ("", "display_order") and not p.descending
                    row["first"] = row["display_order"] <= 1
                    row["last"] = row["display_order"] >= result["total"]
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
            wrap_cells=level == "access",
            fetch=fetch,
            active=current,
            on_error=on_error,
            empty="",
            empty_text=lambda: t("empty"),
            initial={"sort": "display_order"} if level == "field" else None,
        )
        actions = [("edit", "edit")]
        if level == "type":
            actions.extend([("fields", "list"), ("access", "groups")])
        if level == "field":
            actions = [("earlier", "arrow_upward"), ("later", "arrow_downward"), *actions,
                       ("choices", "format_list_bulleted")]
        actions.append(("remove_access" if level == "access" else "delete", "delete_outline"))
        buttons = []
        for action, icon in actions:
            visible = (
                """v-if="props.row.data_type === 'single_choice'" """
                if action == "choices"
                else ""
            )
            if action in {"earlier", "later"}:
                boundary = "first" if action == "earlier" else "last"
                visible = f'v-if="props.row.show_moves" :disable="props.row.{boundary}" '
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
            if action in {"earlier", "later"}:
                if not row["show_moves"]:
                    return
                try:
                    saved = await api.request(
                        "PUT", f"{path}/{identity}/position",
                        headers={"If-Match": str(owner["version"])},
                        json={"position": row["display_order"] + (-1 if action == "earlier" else 1)},
                    )
                    owner["version"] = saved["type_version"]
                except ApiError as error:
                    if error.status_code != 412:
                        ui.notify(on_error(error), color="negative")
                        return
                    ui.notify(t("conflict"), color="negative")
                    owner.update(await api.request("GET", f"{root}/{owner['id']}"))
                if current():
                    await page.load()
            elif action == "edit":
                await edit(row)
            elif action == "remove_access" and level == "access":
                version = owner["version"]
                if not await confirmed("remove_access_confirm", action="remove_access",
                                       role=label(row), type_name=label(owner)) or not current():
                    return
                type_path = f"{root}/{owner['id']}"
                try:
                    result = await api.request("PUT", f"{type_path}/role-grants/{identity}",
                                               headers={"If-Match": str(version)},
                                               json={"can_see": False, "can_use": False})
                    owner["version"] = result["version"]
                except ApiError as error:
                    if not current():
                        return
                    if error.status_code != 412:
                        ui.notify(on_error(error), color="negative")
                        return
                    ui.notify(t("conflict"), color="negative")
                    try:
                        owner.update(await api.request("GET", type_path))
                    except ApiError as refresh_error:
                        ui.notify(on_error(refresh_error), color="negative")
                        return
                if current():
                    await page.load()
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
            if level == "field":
                field_count = page.total
                if submitted or not page.count.text or "loading" in page.table.props:
                    try:
                        unfiltered = await api.request("GET", path, params={"paged": True, "limit": 1})
                    except ApiError as error:
                        ui.notify(on_error(error), color="negative")
                        return
                    field_count = unfiltered["total"]
                    if not current():
                        return
                last_position = field_count if row else field_count + 1
            with (
                ui.dialog() as editor,
                ui.card().classes("messaging-workspace w-full max-w-xl"),
            ):
                ui.label(f"{t('edit' if row else 'add')} · {t(level)}").classes(
                    "text-lg font-semibold"
                )
                if level == "access":
                    ui.label(label(row))
                    ui.checkbox(t("see"), value=True).disable()
                    use = ui.checkbox(t("use"), value=row["can_use"])
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
                if level == "choice":
                    order = _integer_input(t("order"), row.get("display_order", 1), MAX_INT32,
                                           lower_bound=-(2**31), select_initial=not row)
                if level == "field":
                    order = _integer_input(
                        t("order"), row.get("display_order", last_position), last_position, select_initial=not row,
                    )
                    data_type = ui.select(
                        {s: t(s) for s in DATA_TYPES},
                        label=t("data_type"),
                        value=row.get("data_type", "text"),
                    ).classes("w-full")
                    required = ui.checkbox(
                        t("required"), value=row.get("required", False)
                    )
                    ui.label(t("required_help")).bind_visibility_from(required, "value")
                    maximum = _integer_input(
                        t("maximum"), row.get("max_length") or 255, MAX_INT32, select_initial=not row,
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
                                    _positive_integer(maximum.value, MAX_INT32),
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
                        maximum_size = _positive_integer(maximum.value, MAX_INT32)
                        if maximum_size is None:
                            return
                        if (isinstance(default_control, ui.textarea) == (maximum_size > 255)
                                and "data-character-limit" in default_control.props):
                            default_control.props(f"data-character-limit={maximum_size}")
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
                            body = {"can_see": True, "can_use": use.value}
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
                            elif level == "choice":
                                position = literal("integer", order.value)
                                if position is None or not -(2**31) <= position <= MAX_INT32:
                                    raise ValueError(t("invalid"))
                                body["display_order"] = position
                            elif level == "field":
                                position = _positive_integer(order.value, last_position)
                                if position is None:
                                    raise ValueError(t("invalid"))
                                if not creating or position != last_position:
                                    body["display_order"] = position
                                dtype = data_type.value
                                length = _positive_integer(maximum.value, MAX_INT32) if dtype == "text" else None
                                if dtype == "text" and length is None:
                                    raise ValueError(t("invalid"))
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
