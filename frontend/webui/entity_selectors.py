"""Bounded relationship controls; each binding owns its pending reads."""
from __future__ import annotations
import asyncio
import json
from typing import Any, Callable
from nicegui import background_tasks, ui
from .api_client import ApiError
from .i18n_catalogue import render_message_plain

def relationship_options(
    rows: list[dict[str, Any]], label_fields: tuple[str, ...], *,
    include_level_number: bool = False,
    level_label: str | None = None,
) -> dict[int, str]:
    options: dict[int, str] = {}
    for item in rows:
        localized = item.get("localized") or {}
        values = [
            str(localized.get(name) or item.get(name) or "").strip()
            for name in label_fields
        ]
        values = [value for value in values if value]
        code = values[0] if len(values) > 1 else ""
        name = values[-1] if values else render_message_plain("webui.relationship_options.text.item_id_0e84a7f9", id=item['id'])
        label = (
            f"{code} · {name}"
            if code else name
        )
        if include_level_number and item.get("level_number") is not None:
            label = (
                f"{label} · "
                f"{level_label or render_message_plain('webui.render_table.text.level_167db239')} "
                f"{item['level_number']}"
            )
        options[item["id"]] = label
    return options


def relationship_search_query(control: Any, raw_query: object) -> str | None:
    """Ignore the select's display-label echo, but preserve typed/cleared input."""
    query = str(raw_query or "")
    if not control.multiple and control.value is not None and query:
        selected_label = dict(control.options or {}).get(control.value)
        if selected_label is not None and query == str(selected_label):
            return None
    return query


def apply_relationship_selection(control: Any, value: int, label: str) -> None:
    """Atomically add a browsed relationship option and select it."""
    options = dict(control.options or {})
    options[int(value)] = label
    control.set_options(options, value=int(value))


def build_relationship_selector(api: Any, *, error_message: Callable[[ApiError], str]):
    def bind_remote_relationship_select(
        control: Any,
        resource: str,
        search_fields: tuple[str, ...],
        label_fields: tuple[str, ...],
        *,
        filters: dict[str, Any] | None = None,
        exclude_id: int | None = None,
        item_filter: Callable[[dict[str, Any]], bool] | None = None,
        on_options_resolved: Callable[[dict[int, str]], None] | None = None,
        eligible_classifications: bool = False,
        page_loader: Callable | None = None,
        selected_loader: Callable | None = None,
        option_reason: Callable | None = None,
        active: Callable = lambda: True,
        min_query_length: int = 0,
    ) -> Callable[..., Any]:
        """Load a bounded relationship page as the user filters a selector."""
        request_state: dict[str, Any] = {"revision": 0, "task": None, "loaded": False}
        # Capture localized static labels while rendering the page. The remote
        # typeahead later runs in a background task, where falling back to the
        # process-level English catalogue would leak English into an RTL menu.
        # Option labels also enter the select's input-value events; inspector
        # diagnostics belong on rendered UI text, never in searchable values.
        security_level_label = render_message_plain(
            "webui.render_table.text.level_167db239"
        )

        def make_options(rows: list[dict[str, Any]]) -> dict[int, str]:
            options = relationship_options(
                rows, label_fields,
                include_level_number=resource == "security-levels",
                level_label=security_level_label,
            )
            if option_reason is not None:
                disabled = request_state.setdefault("disabled", {})
                for row in rows:
                    reason = option_reason(row)
                    disabled[row["id"]] = bool(reason)
                    if hasattr(control, "option_details"):
                        control.option_details[row["id"]] = {
                            "email": row.get("email") or "", "reason": reason or "",
                        }
                    elif reason:
                        options[row["id"]] += " · " + reason
            return options

        def apply_disabled_options() -> None:
            if option_reason is None:
                return
            disabled = request_state.setdefault("disabled", {})
            # NiceGUI maps option IDs to ordinal values for Quasar. Using
            # ordinals avoids disabling a different person with the same name.
            indices = [index for index, key in enumerate(control.options) if disabled.get(key)]
            request_state["disabled"] = {key: value for key, value in disabled.items() if key in control.options}
            control._props[":option-disable"] = "opt => " + json.dumps(indices) + ".includes(opt.value)"
            control.update()

        async def resolve_selected_options() -> None:
            """Replace restored foreign-key placeholders with localized labels."""
            selected_values = (
                list(control.value or []) if control.multiple
                else ([control.value] if control.value is not None else [])
            )
            if not selected_values:
                return
            try:
                rows = await asyncio.gather(*(
                    (selected_loader(int(value)) if selected_loader else api.get(resource, int(value))) for value in selected_values
                ))
            except (ApiError, TypeError, ValueError):
                # A deleted or inaccessible reference remains visible as an unresolved
                # value; server-side search validation will reject it when appropriate.
                return
            if not active() or getattr(control, "_deleted", False):
                return
            resolved = make_options(list(rows))
            raw_current_values = (
                set(control.value or []) if control.multiple
                else ({control.value} if control.value is not None else set())
            )
            current_values = {
                int(value) if str(value).isdigit() else value
                for value in raw_current_values
            }
            control.options = {
                **dict(control.options or {}),
                **{
                    key: value for key, value in resolved.items()
                    if key in current_values
                },
            }
            control.update()
            apply_disabled_options()
            if on_options_resolved is not None:
                on_options_resolved(resolved)

        async def load_options(query: str = "") -> None:
            if not active() or getattr(control, "_deleted", False):
                return
            request_state["revision"] += 1
            revision = request_state["revision"]
            try:
                result = {'items': []} if len(query.strip()) < min_query_length else await page_loader(query) if page_loader else (
                    await api.administration_reference_page(
                        resource, query=query, limit=25,
                        sort="level_number" if resource == "security-levels" else "name",
                        filters=filters,
                    )
                    if resource in {"profiles", "security-levels"}
                    else await api.relationship_page(
                        resource, search_fields, query, limit=25, filters=filters,
                        eligible_classifications=eligible_classifications,
                    )
                )
            except asyncio.CancelledError:
                return
            except ApiError as error:
                if revision == request_state["revision"] and active() and not getattr(control, "_deleted", False):
                    ui.notify(error_message(error), color="negative", close_button=True)
                return
            if revision != request_state["revision"] or not active() or getattr(control, "_deleted", False):
                return
            selected_values = (
                set(control.value or []) if control.multiple
                else ({control.value} if control.value is not None else set())
            )
            selected_options = {
                key: value for key, value in dict(control.options).items()
                if key in selected_values
            }
            page_options = make_options(
                [
                    item for item in result.get("items", [])
                    if exclude_id is None or int(item["id"]) != int(exclude_id)
                    if item_filter is None or item_filter(item)
                ],
            )
            control.options = {**selected_options, **page_options}
            control.update()
            apply_disabled_options()
            if on_options_resolved is not None:
                on_options_resolved(page_options)
            request_state["loaded"] = True

        def schedule_filter(event: Any) -> None:
            previous = request_state.get("task")
            if previous is not None and not previous.done():
                previous.cancel()
            query = relationship_search_query(control, event.args)
            request_state["revision"] += 1
            if query is None:
                return

            async def delayed() -> None:
                await asyncio.sleep(0.2)
                # Selection may settle after input-value was emitted.
                if relationship_search_query(control, query) is None:
                    return
                await load_options(query)

            request_state["task"] = asyncio.create_task(delayed())

        def ensure_loaded() -> None:
            if not request_state["loaded"]:
                request_state["task"] = asyncio.create_task(load_options())

        control.on("input-value", schedule_filter)
        control.on("popup-show", ensure_loaded)
        if control.value is not None:
            background_tasks.create(resolve_selected_options())
        return load_options

    return bind_remote_relationship_select

