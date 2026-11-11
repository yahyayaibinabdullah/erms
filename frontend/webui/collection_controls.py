"""Bounded collection loading and paging with explicit view callbacks.

One loader is assembled per page. Its request revision suppresses stale results;
collection page settings remain owned by the navigation-restored host view.
"""
from __future__ import annotations
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .entities import ENTITIES


def build_collection_loader(
    api: Any, *, get_resource: Callable[[], str], get_query: Callable,
    pages: dict, accept_results: Callable, clear_result_state: Callable,
    decorate_for_spec: Callable, decorate_record_search_components: Callable,
    page_client: Any, set_connection_status: Callable, render_table: Callable,
    error_message: Callable,
):
    request_revision = 0
    async def load_rows(
        *, repeat_search: bool = False, on_loaded: Callable[[], None] | None = None,
        is_current: Callable[[], bool] | None = None,
    ) -> None:
        spec = ENTITIES[get_resource()]
        nonlocal request_revision
        request_revision += 1
        revision = request_revision

        def request_is_current() -> bool:
            return (get_resource() == spec.key
                    and request_revision == revision
                    and (is_current is None or is_current()))
        try:
            if spec.search_first:
                query = (get_query() or "").strip()
                if not query and not repeat_search:
                    accept_results([], False)
                    clear_result_state(spec.key)
                elif query:
                    rows = await api.search(spec.key, query, spec.search_fields)
                    if not request_is_current():
                        return
                    decorated_rows = await decorate_for_spec(spec, rows)
                    decorated_rows = (
                        await decorate_record_search_components(decorated_rows)
                        if spec.key == "records" else decorated_rows
                    )
                    if not request_is_current() or getattr(page_client, "_deleted", False):
                        return
                    accept_results(decorated_rows, True)
            else:
                page = pages.setdefault(spec.key, {
                    "offset": 0, "limit": 25, "total": 0, "query": "",
                    "status": "all", "account_type": "all",
                    "sort": "level_number" if spec.key == "security-levels" else "name",
                })
                conditions: list[dict[str, Any]] = []
                query = str(page.get("query") or "").strip()
                if query:
                    conditions.append({"or": [
                        {"field": field, "operator": "contains_ci", "value": query}
                        for field in spec.search_fields
                    ]})
                if page.get("status") not in {None, "all"}:
                    conditions.append({
                        "field": "status", "operator": "eq", "value": page["status"],
                    })
                if spec.key == "users" and page.get("account_type") not in {None, "all"}:
                    conditions.append({
                        "field": "account_type", "operator": "eq",
                        "value": page["account_type"],
                    })
                payload: dict[str, Any] = {
                    "limit": int(page["limit"]), "offset": int(page["offset"]),
                    "sort": [
                        {"field": page["sort"], "direction": "asc"},
                        *(
                            [{"field": "id", "direction": "asc"}]
                            if page["sort"] != "id" else []
                        ),
                    ],
                }
                if conditions:
                    payload["where"] = conditions[0] if len(conditions) == 1 else {"and": conditions}
                result = (
                    await api.administration_reference_page(
                        spec.key, query=query, sort=str(page["sort"]),
                        limit=int(page["limit"]), offset=int(page["offset"]),
                    )
                    if spec.key in {"profiles", "security-levels"}
                    else await api.search_request(
                        spec.key, payload,
                        include_system=True if spec.key == "roles" else None,
                    )
                )
                if not request_is_current():
                    return
                decorated = await decorate_for_spec(spec, result["items"])
                if not request_is_current():
                    return
                page["total"] = int(result["total"])
                accept_results(decorated, True)
            set_connection_status(True)
            if on_loaded is not None:
                on_loaded()
            else:
                render_table(spec)
        except ApiError as error:
            if not request_is_current() or getattr(page_client, "_deleted", False):
                return
            set_connection_status(error.status_code != 503)
            ui.notify(error_message(error), color="negative", close_button=True)

    return load_rows


def bind_collection_paging(
    *, card_page: dict, card_filter: Any, card_status: Any,
    card_account_type: Any, card_sort: Any, card_page_size: Any,
    card_host: Any, card_first: Any, card_previous: Any, card_next: Any,
    card_last: Any, load_rows: Callable, render_governance_cards: Callable,
):
    async def reload_governance_cards(*, reset: bool = False) -> None:
        card_page.update(
            query=(card_filter.value or "").strip(),
            status=card_status.value if card_status is not None else "all",
            account_type=card_account_type.value if card_account_type is not None else "all",
            sort=card_sort.value,
            limit=int(card_page_size.value),
        )
        if reset:
            card_page["offset"] = 0
        await load_rows(
            repeat_search=True, on_loaded=render_governance_cards,
            is_current=lambda: not card_host.is_deleted,
        )

    async def move_card_page(offset: int) -> None:
        card_page["offset"] = max(0, offset)
        await load_rows(
            repeat_search=True, on_loaded=render_governance_cards,
            is_current=lambda: not card_host.is_deleted,
        )

    card_filter.on_value_change(lambda: reload_governance_cards(reset=True))
    card_sort.on_value_change(lambda: reload_governance_cards(reset=True))
    card_page_size.on_value_change(lambda: reload_governance_cards(reset=True))
    if card_status is not None:
        card_status.on_value_change(lambda: reload_governance_cards(reset=True))
    if card_account_type is not None:
        card_account_type.on_value_change(lambda: reload_governance_cards(reset=True))
    card_first.on("click", lambda: move_card_page(0))
    card_previous.on("click", lambda: move_card_page(card_page["offset"] - int(card_page_size.value)))
    card_next.on("click", lambda: move_card_page(card_page["offset"] + int(card_page_size.value)))
    card_last.on("click", lambda: move_card_page(max(0, ((card_page["total"] - 1) // int(card_page_size.value)) * int(card_page_size.value))))

    return reload_governance_cards
