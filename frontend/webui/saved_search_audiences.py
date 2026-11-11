"""Bounded saved-search role and organization audience selectors."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
import asyncio
from .i18n_catalogue import strip_diagnostic_metadata
from nicegui import ui

def build_saved_search_audiences(
    *, api, error_message,
):
    def bind_remote_saved_audience_select(
        control: Any, audience_kind: str, more_button: Any,
    ) -> tuple[Callable[..., Any], Callable[..., Any]]:
        """Attach a bounded typeahead to a saved-search role or unit selector."""
        request_state: dict[str, Any] = {"revision": 0, "task": None, "query": "", "offset": 0}

        def selected_values() -> list[int]:
            if control.multiple:
                return list(control.value or [])
            return [control.value] if control.value is not None else []

        def option_label(item: dict[str, Any]) -> str:
            name = (item.get("localized") or {}).get("name") or item.get("name") or item["id"]
            return f"{name} ({item['code']})" if item.get("code") else str(name)

        async def load_options(query: str = "", *, append: bool = False) -> None:
            request_state["revision"] += 1
            revision = request_state["revision"]
            selected = set(selected_values())
            retained = {key: value for key, value in dict(control.options).items() if key in selected}
            term = strip_diagnostic_metadata(query).strip()
            offset = request_state["offset"] if append else 0
            if not append:
                more_button.set_visibility(False)
            if len(term) < 2:
                control.options = retained
                control.update()
                return
            try:
                page = await api.saved_search_audience_options(
                    audience_kind, query=term, limit=25, offset=offset,
                )
            except asyncio.CancelledError:
                return
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            if revision != request_state["revision"]:
                return
            retained = dict(control.options) if append else {key: value for key, value in dict(control.options).items() if key in set(selected_values())}
            request_state.update(query=term, offset=offset + len(page.get("items", [])))
            more_button.set_visibility(request_state["offset"] < page["total"])
            control.options = {
                **retained,
                **{int(item["id"]): option_label(item) for item in page.get("items", [])},
            }
            control.update()

        async def load_selected(ids: list[int]) -> None:
            if not ids:
                return
            try:
                pages = await asyncio.gather(*(
                    api.saved_search_audience_options(
                        audience_kind, ids=ids[index:index + 50],
                        limit=min(50, len(ids[index:index + 50])), offset=0,
                    )
                    for index in range(0, len(ids), 50)
                ))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            items = [item for page in pages for item in page.get("items", [])]
            control.options = {
                **dict(control.options),
                **{int(item["id"]): option_label(item) for item in items},
            }
            resolved = [value for value in ids if value in control.options]
            control.value = resolved if control.multiple else (resolved[0] if resolved else None)
            control.update()

        def schedule(event: Any) -> None:
            request_state["revision"] += 1
            more_button.set_visibility(False)
            previous = request_state.get("task")
            if previous is not None and not previous.done():
                previous.cancel()
            async def delayed() -> None:
                await asyncio.sleep(0.2)
                await load_options(str(event.args or ""))
            request_state["task"] = asyncio.create_task(delayed())

        more_button.set_visibility(False)
        more_button.on("click", lambda: load_options(request_state["query"], append=True))
        control.on("input-value", schedule)
        if control.multiple:
            # NiceGUI exposes no separate input-text setter. Clear the QSelect
            # search buffer through its public method, leaving selected IDs intact.
            control.on_value_change(lambda: control.run_method("updateInputValue", ""))
        return load_options, load_selected


    return bind_remote_saved_audience_select
