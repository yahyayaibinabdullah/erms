"""Use the same authorized options for creation shortcuts and form selectors."""
from nicegui import ui

from .api_client import ApiError
from .type_controls import base, label, pick, t


def creation_shortcut(api, context, create, error_message, *, direction, flat=False):
    """Load one bounded page on open. The standard picker reaches the full catalogue."""
    group = ui.context.slot.parent.classes("creation-button-group")
    arrow = None
    revision = 0

    async def opened(menu, owner):
        nonlocal revision
        if menu.is_deleted or context() != owner:
            return
        revision += 1
        request_revision = revision
        kind, _ = owner
        path = base(kind) + "/options"

        def current():
            return not menu.is_deleted and request_revision == revision and context() == owner

        async def choose(identifier):
            if current():
                # QMenu unmounts its contents when the user selects an item.
                with menu.client:
                    await create(identifier)

        async def browse():
            with menu.client:
                row = await pick(api, path, t("type"), params={"access": "use"})
            if row:
                await choose(row["id"])

        menu.clear()
        with menu:
            pending = ui.spinner().classes("m-3")
        try:
            result = await api.request("GET", path, params={
                "access": "use", "paged": True, "sort": "name", "offset": 0, "limit": 25,
            })
        except ApiError as error:
            if current():
                with menu:
                    ui.label(error_message(error)).classes("p-3 text-negative")
            return
        finally:
            if not pending.is_deleted:
                pending.delete()
        if current() and menu.value:
            with menu:
                for row in result["items"]:
                    ui.menu_item(label(row), on_click=lambda _, value=row["id"]: choose(value))
                if result["total"] > len(result["items"]):
                    ui.menu_item(t("search"), on_click=browse)
                if not result["items"]:
                    ui.menu_item(t("empty")).disable()
            menu.run_method("updatePosition")

    async def refresh():
        nonlocal revision, arrow
        revision += 1
        request_revision = revision
        # A hidden second button still counts as the last child of QBtnGroup
        # and squares off the visible primary button.
        if arrow is not None:
            if not arrow.is_deleted:
                arrow.delete()
            arrow = None
        owner = context()
        if not owner:
            return
        try:
            result = await api.request("GET", base(owner[0]) + "/options", params={"access": "use", "limit": 1})
        except ApiError as error:
            if not group.is_deleted and request_revision == revision and context() == owner:
                ui.notify(error_message(error), color="negative")
            return
        if not result or group.is_deleted or request_revision != revision or context() != owner:
            return
        with group:
            title = t(owner[0] + "_catalogue")
            arrow = ui.button(icon="arrow_drop_down").props(
                f"aria-label={title!r} aria-haspopup=menu " + ("flat dense" if flat else "unelevated dense")
            )
        with arrow:
            edge = "left" if direction() == "rtl" else "right"
            menu = ui.menu().props(f'anchor="bottom {edge}" self="top {edge}"')
            ui.tooltip(title).props('anchor="top middle" self="bottom middle"').bind_visibility_from(
                menu, "value", value=False
            )
        menu.on("hide", menu.clear)
        menu.on("show", lambda: opened(menu, owner))

    return refresh
