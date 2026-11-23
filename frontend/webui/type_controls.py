"""Typed metadata controls shared by resource forms, search and administration."""

from datetime import date, datetime
import re
from decimal import Decimal, InvalidOperation
import inspect

from nicegui import ui

from .api_client import ApiError
from .i18n_catalogue import render_message_plain
from .locale_services import (
    current_locale_context,
    format_instant,
    format_local_date,
    utc_instant_to_working,
    working_datetime_to_utc,
)
from .resource_relationships import PageTable
from .relationship_select import relationship_select

TYPE_MESSAGES = {
    "aggregation_catalogue": "resource_types.ui.aggregation_catalogue",
    "record_catalogue": "resource_types.ui.record_catalogue",
    "type": "resource_types.ui.type",
    "primary": "resource_types.ui.primary",
    "section": "resource_types.ui.section",
    "field": "resource_types.ui.field",
    "choice": "resource_types.ui.choice",
    "fields": "resource_types.ui.fields",
    "choices": "resource_types.ui.choices",
    "access": "resource_types.ui.access",
    "see": "resource_types.ui.see",
    "use": "resource_types.ui.use",
    "policy_help": "resource_types.ui.policy_help",
    "admin_help": "resource_types.ui.admin_help",
    "name": "resource_types.ui.name",
    "description": "resource_types.ui.description",
    "data_type": "resource_types.ui.data_type",
    "order": "resource_types.ui.order",
    "maximum": "resource_types.ui.maximum",
    "retry": "webui.render_collection_status.button.retry_a8d0f7d9",
    "required_help": "resource_types.ui.required_help",
    "matches": "resource_types.ui.matches",
    "required": "resource_types.ui.required",
    "default": "resource_types.ui.default",
    "text": "resource_types.ui.text",
    "integer": "resource_types.ui.integer",
    "decimal": "resource_types.ui.decimal",
    "boolean": "resource_types.ui.boolean",
    "date": "resource_types.ui.date",
    "datetime": "resource_types.ui.datetime",
    "single_choice": "resource_types.ui.single_choice",
    "unset": "resource_types.ui.unset",
    "untyped": "resource_types.ui.untyped",
    "yes": "resource_types.ui.yes",
    "no": "resource_types.ui.no",
    "empty": "resource_types.ui.empty",
    "select": "resource_types.ui.select",
    "clear": "resource_types.ui.clear",
    "cancel": "resource_types.ui.cancel",
    "save": "resource_types.ui.save",
    "search": "resource_types.ui.search",
    "add": "resource_types.ui.add",
    "edit": "resource_types.ui.edit",
    "earlier": "webui.render_component_cards.tooltip.move_earlier_0de89c72",
    "later": "webui.render_component_cards.tooltip.move_later_71077211",
    "delete": "resource_types.ui.delete",
    "close": "resource_types.ui.close",
    "continue": "disposition.ui.continue",
    "next": "resource_types.ui.next",
    "previous": "resource_types.ui.previous",
    "condition": "resource_types.ui.condition",
    "assigned": "resource_types.ui.assigned",
    "discard": "resource_types.ui.discard",
    "delete_confirm": "resource_types.ui.delete_confirm",
    "invalid": "resource_types.ui.invalid",
    "saved": "resource_types.ui.saved",
    "conflict": "resource_types.ui.conflict",
    "default_choice": "resource_types.ui.default_choice",
}


def t(key):
    return render_message_plain(TYPE_MESSAGES[key])


def label(row):
    return (row.get("localized") or {}).get("name") or row["name"]


def base(kind):
    return f"/api/v1/{kind}-types"


def col(name, title, sortable=False):
    return dict(
        name=name,
        field=name,
        label=t(title),
        align="right" if current_locale_context()[0].startswith("ar") else "left",
        sortable=sortable,
    )


async def confirmed(message):
    with ui.dialog() as dialog, ui.card():
        ui.label(t(message))
        with ui.row().classes("w-full justify-end"):
            ui.button(t("cancel"), on_click=lambda: dialog.submit(False)).props(
                "flat no-caps"
            )
            ui.button(
                t("continue") if message == "discard" else t("delete"),
                on_click=lambda: dialog.submit(True),
            ).props("unelevated no-caps")
    return bool(await dialog)


async def pick(api, path, title, *, params=None, multiple=False):
    """Search and page on the server. Return None for cancellation."""
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
        ui.label(title).classes("text-lg font-semibold")
        submitted = ""

        async def search():
            nonlocal submitted
            submitted = (query.value or "").strip()
            await page.load(reset=True)

        with ui.row().classes("w-full items-center"):
            query = (
                ui.input(t("search"))
                .props("outlined dense clearable autofocus")
                .classes("grow")
            )
            query.on("keydown.enter", search)
            ui.button(t("search"), icon="search", on_click=search).props(
                "outline no-caps"
            )

        async def fetch(p):
            result = await api.request(
                "GET",
                path,
                params={
                    **(params or {}),
                    "q": submitted,
                    "paged": True,
                    "limit": p.size,
                    "offset": (p.page - 1) * p.size,
                    "sort": (
                        "display_order"
                        if path.endswith("/choices") and not p.sort
                        else "name"
                    ),
                    "descending": p.descending,
                },
            )
            for row in result["items"]:
                row["display_name"] = label(row)
            return result

        page = PageTable(
            columns=[col("display_name", "name", True)],
            fetch=fetch,
            active=lambda: dialog.value,
            on_error=str,
            empty="",
            empty_text=lambda: t("empty"),
            selection="single",
        )

        def choose():
            if page.table.selected:
                dialog.submit(page.table.selected[0])

        with ui.row().classes("w-full justify-end"):
            ui.button(t("cancel"), on_click=lambda: dialog.submit(None)).props(
                "flat no-caps"
            )
            ui.button(t("select"), icon="check", on_click=choose).props(
                "unelevated no-caps"
            ).bind_enabled_from(page.table, "selected", backward=bool)
        ui.timer(0.01, page.load, once=True)
    return await dialog


async def find_option(api, path, identity, access):
    rows = await api.request(
        "GET", path, params={"access": access, "selected": identity, "limit": 1}
    )
    if not rows:
        raise ApiError(404, t("empty"))
    return rows[0]


def choice_dropdown(api, path, title, selected, on_select, *, params=None):
    """Keep the selected ID while the server filters a bounded page of translated choices."""
    rows = {selected["id"]: selected} if selected else {}
    revision = 0
    with ui.row().classes("w-full items-center no-wrap"):
        control = relationship_select(
            title,
            {key: label(row) for key, row in rows.items()},
            value=selected["id"] if selected else None,
            remote=True,
            icon="list",
        ).classes("grow")

        async def load(query=""):
            nonlocal rows, revision
            revision += 1
            request = revision
            try:
                page = await api.request(
                    "GET",
                    path,
                    params={
                        **(params or {}),
                        "paged": True,
                        "q": query,
                        "limit": 25,
                        "offset": 0,
                        "sort": "display_order",
                    },
                )
            except ApiError as error:
                if not control.is_deleted and request == revision:
                    ui.notify(str(error), color="negative")
                return
            if control.is_deleted or revision != request:
                return
            keep = {control.value: rows[control.value]} if control.value in rows else {}
            rows = {**{r["id"]: r for r in page["items"]}, **keep}
            control.set_options({key: label(row) for key, row in rows.items()})

        async def browse():
            row = await pick(api, path, title, params=params)
            if row and not control.is_deleted:
                rows[row["id"]] = row
                control.set_options(
                    {key: label(item) for key, item in rows.items()}, value=row["id"]
                )

        ui.button(icon="search", on_click=browse).props("flat round dense").tooltip(
            t("search")
        )
        control.on("popup-show", lambda: load())
        control.on("input-value", lambda e: load(e.args or ""), throttle=0.25)
        control.on_value_change(lambda e: on_select(rows.get(e.value)))
    return control


def selector(api, path, title, selected, on_select, *, params=None, clearable=True):
    if path.endswith("/choices"):
        return choice_dropdown(api, path, title, selected, on_select, params=params)
    revision = 0
    with ui.row().classes("w-full items-center gap-1") as host:

        async def assign(row):
            nonlocal revision
            revision += 1
            request = revision
            if host.is_deleted:
                return
            result = on_select(row)
            if inspect.isawaitable(result):
                result = await result
            if result is not False and not host.is_deleted and revision == request:
                control.set_text(f"{title} · {label(row) if row else t('unset')}")

        async def choose():
            try:
                row = await pick(api, path, title, params=params)
                if row is not None:
                    await assign(row)
            except ApiError as error:
                if not host.is_deleted:
                    ui.notify(str(error), color="negative")

        control = (
            ui.button(
                f"{title} · {label(selected) if selected else t('unset')}",
                icon="arrow_drop_down",
                on_click=choose,
            )
            .props("outline no-caps align=between")
            .classes("grow")
        )
        if clearable:
            ui.button(icon="clear", on_click=lambda: assign(None)).props(
                "flat round dense"
            ).tooltip(t("clear"))
    return control


def scalar_input(dtype, title, value, maximum=None):
    if dtype == "boolean":
        control = ui.select(
            {True: t("yes"), False: t("no")}, value=value, label=title
        ).props("outlined dense clearable")
    elif dtype == "text" and maximum and maximum > 255:
        control = ui.textarea(title, value=value or "").props("outlined autogrow")
    else:
        if dtype == "datetime" and value:
            try:
                instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                instant = None
            if instant is not None and instant.tzinfo is not None:
                value = (
                    utc_instant_to_working(instant, current_locale_context()[1])
                    .replace(tzinfo=None)
                    .isoformat()
                )
        control = ui.input(title, value="" if value is None else str(value)).props(
            "outlined dense clearable"
        )
        if dtype in {"date", "datetime"}:
            control.props(
                "type=date" if dtype == "date" else "type=datetime-local step=any"
            )
        if dtype in {"integer", "decimal"}:
            control.props(
                "inputmode=" + ("numeric" if dtype == "integer" else "decimal")
            )
    if dtype in {"integer", "decimal"} or (dtype == "text" and maximum):
        # Validate the browser's actual edit, including selection replacement and paste.
        # Keep decimal strings exact and allow incomplete signs/exponents until Save.
        if dtype == "integer":
            predicate = r"""if (/^[+-]?$/.test(v)) return true;
                if (!/^[+-]?[0-9]+$/.test(v)) return false;
                const n = BigInt(v);
                return n >= -9223372036854775808n && n <= 9223372036854775807n;"""
        elif dtype == "decimal":
            predicate = r"""return /^[+-]?(?:\.?|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]*)?)$/.test(v);"""
        else:
            control.props(f"data-character-limit={int(maximum)}")
            predicate = "return event.inputType?.startsWith('delete') || Array.from(v).length <= Number(field.dataset.characterLimit);"
        control.on("beforeinput", js_handler="""event => {
            const field = event.target;
            field.dataset.previousValue = field.value;
        }""")
        control.on("input.capture", js_handler="""event => {
            const field = event.target;
            const valid = v => {""" + predicate + """};
            if (!valid(field.value)) {
                field.value = field.dataset.previousValue ?? field.defaultValue;
            }
            field.dataset.previousValue = field.value;
        }""")
    return control.classes("w-full")


def literal(dtype, value, maximum=None):
    if value is None or value == "":
        return None
    try:
        if dtype in {"text", "date", "datetime"} and not isinstance(value, str):
            raise ValueError
        if dtype == "integer":
            if (
                not re.fullmatch(r"[+-]?[0-9]+", str(value))
                or not -(2**63) <= int(value) < 2**63
            ):
                raise ValueError
            return int(value)
        if dtype == "boolean" and type(value) is not bool:
            raise ValueError
        if dtype == "date":
            date.fromisoformat(value)
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
        if dtype == "decimal":
            if (
                not re.fullmatch(
                    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                    str(value),
                )
                or not Decimal(str(value)).is_finite()
            ):
                raise ValueError
            return str(value)
        if dtype == "datetime":
            if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}", value):
                raise ValueError
            moment = datetime.fromisoformat(value)
            return (
                moment
                if moment.tzinfo
                else working_datetime_to_utc(moment, current_locale_context()[1])
            ).isoformat()
        if dtype == "text" and maximum and len(value) > maximum:
            raise ValueError
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise ValueError(t("invalid")) from error
    return value


class MetadataForm:
    def __init__(self, api, kind, row=None, readonly=False):
        self.api, self.kind, self.row, self.readonly = api, kind, row or {}, readonly
        self.original = self.row.get("type_id")
        self.selected = self.original
        self.existing = self.row.get("field_values") or {}
        self.changes = {}
        self.definitions = {}
        self.revision = 0
        self.assignment_revision = 0
        self.loading = False
        self.access = "see" if readonly else "use"
        self.path = base(kind) + "/options"

    async def render(self):
        if self.readonly and self.selected is None:
            return
        self.host = ui.column().classes("type-metadata-section w-full gap-2")
        with self.host:
            ui.label(t("section")).classes("text-base font-semibold")
            current = None
            if self.selected is not None:
                current = await self.api.request(
                    "GET",
                    self.path + f"/{self.selected}",
                    params={"access": self.access},
                )
                if self.host.is_deleted:
                    return
            if self.readonly:
                ui.label(label(current)).classes("font-medium")
            else:
                selector(
                    self.api,
                    self.path,
                    t("type"),
                    current,
                    self.assign,
                    params={"access": self.access},
                )
            self.fields = ui.column().classes("w-full gap-2")
        if current:
            await self.page(0)

    async def assign(self, row):
        self.assignment_revision += 1
        revision = self.assignment_revision
        target = row["id"] if row else None
        if target == self.selected:
            return True
        if (
            (self.existing or self.changes)
            and self.selected is not None
            and not await confirmed("discard")
        ):
            return False
        if self.host.is_deleted or revision != self.assignment_revision:
            return False
        self.selected = target
        self.changes = {}
        self.definitions.clear()
        await self.page(0)
        return True

    async def page(self, offset):
        import asyncio

        self.revision += 1
        rev = self.revision
        self.fields.clear()
        self.loading = self.selected is not None
        if not self.loading:
            return
        path = f"{self.path}/{self.selected}/fields"
        with self.fields:
            spinner = ui.spinner()
        try:
            data = await self.api.request(
                "GET",
                path,
                params={
                    "access": self.access,
                    "paged": True,
                    "limit": 25,
                    "offset": offset,
                },
            )
            if self.fields.is_deleted or rev != self.revision:
                return
            self.definitions.update({str(f["id"]): f for f in data["items"]})

            def raw(f):
                fid = str(f["id"])
                if fid in self.changes:
                    return self.changes[fid]
                return (
                    self.existing.get(fid)
                    if self.selected == self.original
                    else f.get("default")
                )

            async def choice(f):
                if f["data_type"] == "single_choice" and raw(f) is not None:
                    return await find_option(
                        self.api, f"{path}/{f['id']}/choices", raw(f), self.access
                    )

            choices = await asyncio.gather(*(choice(f) for f in data["items"]))
            if self.fields.is_deleted or rev != self.revision:
                return
            with self.fields:
                for f, chosen in zip(data["items"], choices):
                    fid = str(f["id"])
                    title = label(f) + (" *" if f["required"] else "")
                    dtype = f["data_type"]
                    value = raw(f)
                    if self.readonly:
                        lang, zone = current_locale_context()
                        shown = (
                            label(chosen)
                            if chosen
                            else (
                                t("unset")
                                if value is None
                                else (
                                    t("yes" if value else "no")
                                    if dtype == "boolean"
                                    else (
                                        format_instant(value, zone, lang)
                                        if dtype == "datetime"
                                        else (
                                            format_local_date(value, lang)
                                            if dtype == "date"
                                            else str(value)
                                        )
                                    )
                                )
                            )
                        )
                        ui.label(title).classes("text-xs text-slate-500")
                        ui.label(shown).classes("whitespace-pre-wrap break-words")
                    elif dtype == "single_choice":
                        selector(
                            self.api,
                            f"{path}/{fid}/choices",
                            title,
                            chosen,
                            lambda r, k=fid: self.changes.update(
                                {k: r["id"] if r else None}
                            ),
                            params={"access": self.access},
                        )
                    else:
                        c = scalar_input(dtype, title, value, f["max_length"])

                        def changed(e, k=fid, d=dtype, m=f["max_length"]):
                            try:
                                self.changes[k] = literal(d, e.value, m)
                            except ValueError:
                                self.changes[k] = e.value

                        c.on_value_change(changed)
                if data["total"] > 25:
                    with ui.row():
                        ui.button(
                            t("previous"), on_click=lambda: self.page(offset - 25)
                        ).props("flat").set_enabled(offset > 0)
                        ui.button(
                            t("next"), on_click=lambda: self.page(offset + 25)
                        ).props("flat").set_enabled(offset + 25 < data["total"])
            self.loading = False
        except ApiError as error:
            if not self.fields.is_deleted and self.revision == rev:
                with self.fields:
                    ui.label(str(error)).classes("text-negative").props("role=alert")
                    ui.button(t("retry"), on_click=lambda: self.page(offset)).props(
                        "flat no-caps"
                    )
        finally:
            if not spinner.is_deleted:
                spinner.delete()

    def payload(self):
        if self.loading:
            raise ValueError(t("invalid"))
        for fid, definition in self.definitions.items():
            original = (
                self.existing.get(fid)
                if self.original == self.selected
                else definition.get("default")
            )
            value = self.changes.get(fid, original)
            if definition["required"] and (
                value is None or isinstance(value, str) and not value.strip()
            ):
                raise ValueError(f"{label(definition)} · {t('required')}")
            if fid in self.changes and definition["data_type"] != "single_choice":
                literal(definition["data_type"], value, definition["max_length"])
        if self.selected == self.original and not self.changes:
            return {}
        return {
            "type_id": self.selected,
            "field_values": self.changes,
            **(
                {"confirm_type_change": True}
                if self.original and self.original != self.selected and self.existing
                else {}
            ),
        }
