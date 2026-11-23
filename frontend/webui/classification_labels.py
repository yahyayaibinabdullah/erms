"""Display existing API-localized classification values without changing entity data."""
from collections.abc import Mapping
from typing import Any


def classification_title(item: Mapping[str, Any]) -> str:
    """Use the request's effective title; legacy or missing projections fall back.

    Language resolution belongs to the API. Never select from ``translations``
    here or cache a rendered label across requests, identities or languages.
    Canonical fields remain available unchanged to editors and write payloads.
    """
    localized = item.get("localized") or {}
    title = localized.get("title")
    if isinstance(title, str) and title.strip():
        return title
    return item.get("title") or ""


CLASSIFICATION_PAGES = {
    "classification-scheme-details": "classification-schemes",
    "classification-details": "classifications",
}


def update_classification_navigation(
    trail: list[dict[str, Any]], page: str, item: Mapping[str, Any] | None,
) -> None:
    """Refresh all visits to the entity from the already-loaded fresh response."""
    if page not in CLASSIFICATION_PAGES or item is None or "code" not in item:
        return
    label = f"{item['code']} — {classification_title(item)}"
    for entry in trail:
        if entry.get("page") == page and entry.get("entity_id") == item["id"]:
            entry.update(label=label, accessible_label=label)


async def refresh_classification_navigation(api: Any, trail: list[dict[str, Any]]) -> None:
    """Revalidate persisted breadcrumb titles on reload, including locale changes.

    The existing bounded navigation trail stores rendered labels. Fetch each
    distinct classification reference once; the destination itself is refreshed
    by its normal detail read. Unavailable references are removed; transient
    failures show only stable identity until the next successful read. No entity
    snapshot or new label cache is retained.
    """
    import asyncio
    from .api_client import ApiError

    destination = (trail[-1].get("page"), trail[-1].get("entity_id")) if trail else None
    references = {
        (entry["page"], entry["entity_id"])
        for entry in trail
        if entry.get("page") in CLASSIFICATION_PAGES and entry.get("entity_id") is not None
        and (entry["page"], entry["entity_id"]) != destination
    }

    async def refresh(page: str, entity_id: int) -> None:
        try:
            item = await api.get(CLASSIFICATION_PAGES[page], entity_id)
        except ApiError as error:
            if error.status_code in {403, 404}:
                trail[:] = [
                    entry for entry in trail
                    if (entry.get("page"), entry.get("entity_id")) != (page, entity_id)
                ]
            else:
                # A breadcrumb read must not sign out an otherwise valid
                # session or retain a title rendered in the previous language.
                for entry in trail:
                    if (entry.get("page"), entry.get("entity_id")) == (page, entity_id):
                        code, separator, _ = str(entry.get("label") or "").partition(" — ")
                        label = code if separator and code else str(entity_id)
                        entry.update(label=label, accessible_label=label)
            return
        update_classification_navigation(trail, page, item)

    await asyncio.gather(*(refresh(*reference) for reference in references))
