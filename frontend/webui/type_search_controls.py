"""Type-scoped controls for the existing Advanced Search rows."""

import asyncio

from nicegui import ui

from .advanced_search_model import advanced_search_operators, typed_field_ids
from .api_client import ApiError
from .i18n_catalogue import render_message
from .type_controls import (
    base,
    find_option,
    label,
    literal,
    pick,
    scalar_input,
    selector,
    t,
)


async def choose_sort(api, resource, active):
    options = base(resource[:-1]) + "/options"
    owner = await pick(api, options, t("type"))
    if owner is None or not active():
        return None
    field = await pick(api, f"{options}/{owner['id']}/fields", t("field"))
    if field and active():
        return (
            f"type.{owner['id']}.field.{field['id']}",
            f"{label(owner)} · {label(field)}",
        )
    return None


async def sort_label(api, resource, name):
    owner, field = typed_field_ids(name)
    path = base(resource[:-1]) + "/options"
    rows = await asyncio.gather(
        api.request("GET", f"{path}/{owner}"),
        find_option(api, f"{path}/{owner}/fields", field, "see"),
    )
    return " · ".join(label(row) for row in rows)


def render_type_condition(api, resource, node, rerender, changed, error_message):
    path = base(resource[:-1]) + "/options"
    host = ui.row().classes("grow items-end gap-2 flex-wrap")

    def reset_value(**updates):
        node.update(value=None, invalid_value=False)
        node.update(updates)
        rerender()

    async def draw():
        if host.is_deleted:
            return
        try:
            assigned = node["kind"] == "assigned"
            field = None
            dtype = "assigned"
            if not assigned:
                ids = typed_field_ids(node.get("field"))
                owner_id = ids[0] if ids else node.get("owner_id")
                owner = (
                    await api.request("GET", f"{path}/{owner_id}") if owner_id else None
                )
                fields_path = f"{path}/{owner_id}/fields"
                field = (
                    await find_option(api, fields_path, ids[1], "see") if ids else None
                )
                if host.is_deleted:
                    return

                def set_owner(row):
                    reset_value(
                        owner_id=row["id"] if row else None, field=None, operator="eq"
                    )

                def set_field(row):
                    name = f"type.{owner_id}.field.{row['id']}" if row else None
                    reset_value(field=name, operator="eq")

                with host:
                    selector(api, path, t("type"), owner, set_owner)
                    if owner:
                        selector(api, fields_path, t("field"), field, set_field)
                if field is None:
                    return
                dtype = field["data_type"]
            mapped = {
                "assigned": "choice",
                "single_choice": "choice",
                "decimal": "integer",
                "date": "datetime",
            }
            operators = advanced_search_operators(mapped.get(dtype, dtype), True)
            if dtype == "boolean":
                operators.update(
                    {
                        k: v
                        for k, v in advanced_search_operators("choice", True).items()
                        if k in {"in", "not_in"}
                    }
                )
            if dtype == "text":
                operators["matches_ci"] = t("matches")
            op = node.get("operator", "eq")
            with host:
                ui.select(
                    operators,
                    value=op,
                    label=render_message(
                        "webui.render_condition.select.operator_e4a90ad3"
                    ),
                ).props("outlined dense options-dense").classes("min-w-44").on_value_change(
                    lambda e: reset_value(operator=e.value)
                )
            if op in {"is_null", "is_not_null"}:
                return
            many = op in {"in", "not_in", "between"}
            raw = node.get("value")
            values = list(raw or []) if many else [raw]
            if not values:
                values = [None, None] if op == "between" else [None]
            if many:
                node["value"] = values
            option_path = (
                path
                if assigned
                else (
                    f"{path}/{ids[0]}/fields/{ids[1]}/choices"
                    if dtype == "single_choice"
                    else None
                )
            )

            async def selected(value):
                if value is not None and option_path:
                    return (
                        (await api.request("GET", f"{path}/{value}"))
                        if assigned
                        else await find_option(api, option_path, value, "see")
                    )

            rows = await asyncio.gather(*(selected(v) for v in values))
            if host.is_deleted:
                return
            invalid = set()

            def update(i, value):
                values[i] = value
                node["value"] = values if many else value
                node["invalid_value"] = bool(invalid)
                changed()

            with host:
                for i, (value, row) in enumerate(zip(values, rows)):
                    title = render_message("advanced_search.field.value")
                    if option_path:
                        selector(
                            api,
                            option_path,
                            title,
                            row,
                            lambda r, i=i: update(i, r["id"] if r else None),
                        )
                    else:
                        control = scalar_input(dtype, title, value)

                        def change(e, i=i):
                            try:
                                value = literal(dtype, e.value)
                                invalid.discard(i)
                            except ValueError:
                                value = e.value
                                invalid.add(i)
                            update(i, value)

                        control.on_value_change(change)
                    if many and op != "between" and len(values) > 1:
                        ui.button(
                            icon="clear",
                            on_click=lambda _, i=i: reset_value(
                                value=values[:i] + values[i + 1 :]
                            ),
                        ).props("flat round dense").tooltip(t("clear"))
                if op in {"in", "not_in"} and len(values) < 100:
                    ui.button(
                        t("add"),
                        icon="add",
                        on_click=lambda: reset_value(value=values + [None]),
                    ).props("flat no-caps")
        except ApiError as error:
            if not host.is_deleted:
                node["invalid_value"] = True
                with host:
                    ui.label(error_message(error)).classes("text-negative").props(
                        "role=alert"
                    )
                changed()

    with host:
        ui.timer(0.01, draw, once=True)
