"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
import asyncio
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message


def style_person_select(control: Any, *, multiple: bool = False) -> None:
    """Give user selectors a consistent name/email hierarchy and compact identity chips."""
    control.props(
        'use-input input-debounce=0 behavior=menu options-dense '
        'popup-content-style="min-width:420px;max-width:calc(100vw - 48px)"'
    ).classes("person-select")
    control.add_slot("option", """
        <q-item v-bind="props.itemProps" class="person-select-option q-py-sm">
          <q-item-section avatar style="min-width:44px">
            <q-avatar color="blue-1" text-color="primary" size="34px">
              {{ props.opt.label.split(' — ')[0].split(' ').filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() }}
            </q-avatar>
          </q-item-section>
          <q-item-section style="min-width:0">
            <q-item-label class="text-weight-medium ellipsis">{{ props.opt.label.split(' — ')[0] }}</q-item-label>
            <q-item-label caption class="ellipsis">{{ props.opt.label.split(' — ').slice(1).join(' — ') }}</q-item-label>
          </q-item-section>
        </q-item>
    """)
    if multiple:
        control.add_slot("selected-item", """
            <q-chip
              dense removable outline color="primary" text-color="blue-grey-9"
              class="person-select-chip"
              @remove="props.removeAtIndex(props.index)"
              :tabindex="props.tabindex"
            >
              <q-avatar color="blue-1" text-color="primary">
                {{ props.opt.label.split(' — ')[0].split(' ').filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() }}
              </q-avatar>
              <span class="ellipsis">{{ props.opt.label.split(' — ')[0] }}</span>
              <q-tooltip>{{ props.opt.label }}</q-tooltip>
            </q-chip>
        """)
    else:
        # NiceGUI's single-select `with_input=True` defaults to hiding the
        # selected-item slot and filling the filter input with the raw label.
        # Keep search enabled, but let the selected identity render through
        # the same visual chip slot used by the contributors selector.
        control._props["hide-selected"] = False
        control._props["fill-input"] = False
        control.add_slot("selected-item", """
            <q-chip
              dense outline color="primary" text-color="blue-grey-9"
              class="person-select-chip"
              :tabindex="props.tabindex"
            >
              <q-avatar color="blue-1" text-color="primary">
                {{ props.opt.label.split(' — ')[0].split(' ').filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() }}
              </q-avatar>
              <span class="ellipsis">{{ props.opt.label.split(' — ')[0] }}</span>
              <q-tooltip>{{ props.opt.label }}</q-tooltip>
            </q-chip>
        """)


def build_people_select(
    *, api, error_message,
):
    def bind_remote_people_select(
        control: Any,
        *,
        excluded_ids: Callable[[], set[int]] | None = None,
    ) -> Callable[..., Any]:
        """Attach debounced active-person typeahead behavior to a user selector."""
        request_state: dict[str, Any] = {"revision": 0, "task": None}

        async def load_options(query: str = "") -> None:
            request_state["revision"] += 1
            revision = request_state["revision"]
            selected_values = (
                set(control.value or []) if control.multiple
                else ({control.value} if control.value is not None else set())
            )
            selected_options = {
                key: value for key, value in dict(control.options).items()
                if key in selected_values
            }
            term = query.strip()
            if len(term) < 2:
                control.options = selected_options
                control.update()
                return
            try:
                result = await api.active_people(term, limit=25, offset=0)
            except asyncio.CancelledError:
                return
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            if revision != request_state["revision"]:
                return
            excluded = excluded_ids() if excluded_ids else set()
            page_options = {
                int(person["id"]): (
                    f"{(person.get('localized') or {}).get('name') or person['name']} — "
                    f"{person.get('email') or render_message('webui.select_user_details.label.no_email_address_1d665180')}"
                )
                for person in result.get("items", [])
                if int(person["id"]) not in excluded
            }
            control.options = {**selected_options, **page_options}
            control.update()

        def schedule_filter(event: Any) -> None:
            previous = request_state.get("task")
            if previous is not None and not previous.done():
                previous.cancel()

            async def delayed() -> None:
                await asyncio.sleep(0.2)
                await load_options(str(event.args or ""))

            request_state["task"] = asyncio.create_task(delayed())

        control.on("input-value", schedule_filter)
        return load_options


    return bind_remote_people_select
