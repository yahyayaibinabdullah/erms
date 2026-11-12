"""Bounded, identity-scoped administration of code-owned notification producers."""

import asyncio
import json
from uuid import uuid4
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message

# Literal values keep catalogue discovery explicit.
MESSAGING_MESSAGE_KEYS = {
    "title": "messaging.admin.title",
    "current_responsible_people": "messaging.admin.audience.current_responsible_people",
    "newly_assigned_person": "messaging.admin.audience.newly_assigned_person",
    "review_preview": "messaging.admin.review_preview",
    "true": "messaging.value.true",
    "false": "messaging.value.false",
    "search": "messaging.admin.search",
    "empty": "messaging.admin.empty",
    "loading": "messaging.admin.loading",
    "failed": "messaging.admin.failed",
    "conflict": "messaging.admin.conflict",
    "validation": "messaging.admin.validation",
    "open": "messaging.action.open",
    "previous": "messaging.action.previous",
    "next": "messaging.action.next",
    "back": "messaging.admin.back",
    "locked": "messaging.admin.locked",
    "required": "messaging.admin.required",
    "optional": "messaging.admin.optional",
    "active": "messaging.admin.active",
    "version": "messaging.admin.version",
    "new": "messaging.admin.new",
    "versions": "messaging.admin.versions",
    "owner": "messaging.admin.owner",
    "enabled": "messaging.admin.enabled",
    "priority": "messaging.field.priority",
    "audience": "messaging.admin.audience",
    "static": "messaging.admin.static",
    "user": "messaging.field.user",
    "role": "messaging.field.role",
    "org_unit": "messaging.field.org_unit",
    "kind": "messaging.field.kind",
    "recipient": "messaging.field.recipient",
    "to": "messaging.field.to",
    "cc": "messaging.field.cc",
    "add": "messaging.action.add",
    "remove": "messaging.action.remove",
    "subject": "messaging.field.subject",
    "body": "messaging.field.body",
    "draft": "messaging.admin.draft",
    "reviewed": "messaging.admin.reviewed",
    "published": "messaging.admin.published",
    "review": "messaging.admin.review",
    "reason": "messaging.field.reason",
    "save": "messaging.admin.save",
    "activate": "messaging.admin.activate",
    "preview": "messaging.admin.preview",
    "test": "messaging.admin.test",
    "confirm_test": "messaging.admin.confirm_test",
    "test_help": "messaging.admin.test_help",
    "history": "messaging.admin.history",
    "values": "messaging.admin.values",
    "resources": "messaging.admin.resources",
    "cancel": "messaging.action.cancel",
    "saved": "messaging.admin.saved",
    "activated": "messaging.admin.activated",
    "sent": "messaging.admin.sent",
    "test_label": "messaging.test.label",
    "normal": "messaging.priority.normal",
    "high": "messaging.priority.high",
    "very_high": "messaging.priority.very_high",
    "none": "messaging.admin.none",
    "templates_help": "messaging.admin.templates_help",
    "success": "messaging.admin.success",
    "failure": "messaging.admin.failure",
    "initiator": "messaging.admin.initiator",
    "recipient_count": "messaging.admin.recipient_count",
}


def producer_name(item):
    return (
        (item.get("localized") or {}).get("name")
        or item.get("name")
        or item["producer_code"]
    )


def text(key):
    return render_message(MESSAGING_MESSAGE_KEYS[key])


async def notification_administration(
    *, api, container, relationship_select, bind_relationship, format_timestamp, active
):
    base = "/api/v1/notification-administration"
    state = {"revision": 0, "cursor": "", "previous": [], "next": None, "query": "", "loading": False}
    with container:
        with ui.column().classes("w-full gap-3 p-3"):
            with ui.row().classes(
                "detail-action-row " + "w-full gap-2 items-center"
            ) as search_bar:
                search = (
                    ui.input(text("search")).props("outlined dense").classes("grow")
                )
                ui.button(
                    text("search"), icon="search", on_click=lambda: load(True, query=search.value or "")
                ).props("no-caps")
            progress = ui.label("").props("role=status")
            results = ui.column().classes(
                "w-full gap-0 rounded-xl border border-slate-200 overflow-hidden bg-white"
            )
            with ui.row().classes("detail-action-row " + "gap-2") as paging:
                previous = ui.button(
                    text("previous"), on_click=lambda: page(False)
                ).props("outline no-caps")
                next_button = ui.button(
                    text("next"), on_click=lambda: page(True)
                ).props("outline no-caps")
            details = ui.column().classes("w-full gap-3")

    def current(revision):
        return active() and state["revision"] == revision

    async def request(method, path, **kwargs):
        return await api.request(method, base + path, **kwargs)

    def failure(error):
        key = (
            "conflict"
            if isinstance(error, ApiError) and error.status_code == 409
            else (
                "validation"
                if isinstance(error, (ValueError, TypeError))
                or isinstance(error, ApiError)
                and error.status_code == 422
                else "failed"
            )
        )
        progress.text = text(key)

    async def page(forward):
        if state["loading"] or (forward and not state["next"]) or (not forward and not state["previous"]):
            return
        if forward:
            await load(position=(state["next"], [*state["previous"], state["cursor"]]))
        else:
            await load(position=(state["previous"][-1], state["previous"][:-1]))

    async def load(reset=False, *, position=None, query=None):
        state["revision"] += 1
        revision = state["revision"]
        state["loading"] = True
        cursor, history = ("", []) if reset else position or (state["cursor"], state["previous"])
        query = state["query"] if query is None else query
        progress.text = text("loading")
        try:
            response = await request(
                "GET",
                "/producers",
                params={
                    "q": query,
                    "after": cursor or "",
                    "limit": 25,
                },
            )
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if current(revision):
                failure(error)
            return
        finally:
            if state["revision"] == revision:
                state["loading"] = False
        if not current(revision):
            return
        state.update(cursor=cursor, previous=history, query=query)
        details.clear()
        results.set_visibility(True)
        paging.set_visibility(True)
        search_bar.set_visibility(True)
        results.clear()
        progress.text = ""
        state["next"] = response["next_cursor"]
        previous.set_enabled(bool(state["previous"]))
        next_button.set_enabled(bool(state["next"]))
        with results:
            with ui.column().classes(
                "w-full bg-blue-50 border-b border-blue-100 px-4 py-3"
            ):
                ui.label(text("title")).classes("font-semibold text-blue-900")
            if not response["items"]:
                ui.label(text("empty")).classes("p-5 text-slate-500")
            for item in response["items"]:
                with ui.grid(columns="minmax(0, 1fr) auto").classes(
                    "w-full items-center gap-3 p-4 border-b border-slate-100"
                ):
                    with ui.column().classes("gap-1"):
                        ui.label(producer_name(item)).classes("font-semibold")
                        ui.label(item["operational_owner"] or text("none")).classes(
                            "text-sm text-slate-500"
                        )
                        ui.label(
                            text("active") + ": " + str(item["active_version"] or "—")
                        )
                    ui.button(
                        text("open"),
                        icon="settings",
                        on_click=lambda _, code=item["producer_code"]: open_producer(
                            code
                        ),
                    ).props("flat no-caps")

    async def open_producer(code):
        state["revision"] += 1
        revision = state["revision"]
        progress.text = text("loading")
        try:
            info, versions = await asyncio.gather(
                request("GET", "/producers/" + code),
                request(
                    "GET", "/producers/" + code + "/versions", params={"limit": 25}
                ),
            )
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if current(revision):
                failure(error)
            return
        if not current(revision):
            return
        results.set_visibility(False)
        paging.set_visibility(False)
        search_bar.set_visibility(False)
        details.clear()
        progress.text = ""
        path = "/producers/" + code
        with details:
            ui.button(text("back"), icon="arrow_back", on_click=lambda: load()).props(
                "flat no-caps"
            )
            with ui.card().classes("w-full shadow-none border border-slate-200"):
                ui.label(producer_name(info)).classes("text-xl font-semibold")
                ui.label(code).classes("text-sm text-slate-500").props("dir=ltr")
                ui.label(text("locked")).classes("text-sm text-slate-500")
                ui.label(
                    info["feature_code"]
                    + " · "
                    + info["event_type"]
                    + " · "
                    + str(info["contract_version"])
                )
                ui.badge(
                    text("required")
                    if info["required_for_business_commit"]
                    else text("optional")
                )
                ui.label(
                    text("active")
                    + ": "
                    + str(info["active_configuration_version_id"] or "—")
                ).classes("break-all")
                with ui.row().classes("detail-action-row " + "gap-2"):
                    ui.button(
                        text("new"),
                        icon="add",
                        on_click=lambda: edit(info, None, revision),
                    ).props("no-caps")
                    ui.button(
                        text("history"),
                        icon="history",
                        on_click=lambda: show_history(info, revision),
                    ).props("outline no-caps")
            version_host = ui.column().classes("w-full gap-2")
            version_state = {"before": None, "previous": []}
            with ui.row().classes("detail-action-row " + "gap-2"):
                prev = ui.button(text("previous")).props("outline no-caps")
                nxt = ui.button(text("next")).props("outline no-caps")

        def paint_versions(response):
            if not current(revision):
                return
            version_host.clear()
            version_state["next"] = response["next_cursor"]
            prev.set_enabled(bool(version_state["previous"]))
            nxt.set_enabled(bool(response["next_cursor"]))
            with version_host:
                ui.label(text("versions")).classes(
                    "font-semibold text-blue-900 bg-blue-50 w-full p-3 rounded"
                )
                if not response["items"]:
                    ui.label(text("empty"))
                for row in response["items"]:
                    with ui.card().classes(
                        "w-full shadow-none border border-slate-200"
                    ):
                        ui.label(
                            text("version")
                            + " "
                            + str(row["version"])
                            + " · "
                            + row["operational_owner"]
                        )
                        ui.label(format_timestamp(row["created_at"])).classes(
                            "text-sm text-slate-500"
                        )
                        ui.button(
                            text("open"),
                            on_click=lambda _, identity=row["id"]: open_version(
                                identity
                            ),
                        ).props("flat no-caps")

        async def open_version(identity):
            try:
                version = await request("GET", path + "/versions/" + identity)
                if current(revision):
                    await edit(info, version, revision)
            except ApiError as error:
                if current(revision):
                    failure(error)

        async def version_page(forward):
            if forward:
                version_state["previous"].append(version_state["before"])
                version_state["before"] = version_state["next"]
            else:
                version_state["before"] = version_state["previous"].pop()
            try:
                params = {"limit": 25}
                if version_state["before"]:
                    params["before"] = version_state["before"]
                response = await request("GET", path + "/versions", params=params)
                paint_versions(response)
            except ApiError as error:
                if current(revision):
                    failure(error)

        prev.on("click", lambda: version_page(False))
        nxt.on("click", lambda: version_page(True))
        paint_versions(versions)

    def context_fields(definition, values):
        controls = {}
        for name, rule in definition["placeholders"].items():
            ui.label(
                render_message(
                    "messaging.admin.placeholder",
                    name="{" + name + "}",
                    type=rule["type"],
                )
            ).classes("text-sm text-slate-600")
            value = values.get(name)
            if rule["type"] == "boolean":
                control = ui.select(
                    {True: text("true"), False: text("false")},
                    label=name,
                    value=bool(value),
                )
            elif rule["type"] in {"integer", "decimal"}:
                control = ui.number(
                    name, value=float(value) if value is not None else None
                ).props("outlined dense")
            else:
                control = (
                    ui.input(name, value=str(value) if value is not None else "")
                    .props("outlined dense")
                    .classes("w-full")
                )
            controls[name] = (control, rule["type"])
        return controls

    def values(controls):
        result = {}
        for name, (control, kind) in controls.items():
            value = control.value
            if kind == "integer" and value is not None:
                if int(value) != value:
                    raise ValueError()
                value = int(value)
            result[name] = value
        return result

    async def select_audience(host, selected, is_valid, test=False):
        with host:
            kind = ui.select(
                {key: text(key) for key in ("user", "role", "org_unit")},
                value="user",
                label=text("kind"),
            ).props("outlined dense")
            if test:
                kind.set_visibility(False)
            classification = ui.select(
                {"to": text("to"), "cc": text("cc")}, value="to", label=text("to")
            ).props("outlined dense")
            if test:
                classification.set_visibility(False)
            control = relationship_select(text("recipient"), {})
            selected_host = ui.column().classes("w-full gap-1")

            async def search_people(q, target=None):
                params = {"q": q, "limit": 25}
                if target:
                    params["target_id"] = target
                return await request("GET", "/recipients/" + kind.value, params=params)

            async def chosen(identity):
                response = await search_people("", identity)
                return next(
                    iter(response["items"]), {"id": identity, "name": text("failed")}
                )

            loader = bind_relationship(
                control,
                "users",
                ("name",),
                ("name",),
                page_loader=search_people,
                selected_loader=chosen,
                active=is_valid,
            )

            async def change_kind():
                control.value = None
                control.options = {}
                await loader()

            kind.on_value_change(change_kind)

            def paint():
                selected_host.clear()
                with selected_host:
                    for row in selected:
                        with ui.row().classes(
                            "detail-action-row " + "items-center gap-2"
                        ):
                            ui.label(
                                text(row["recipient_type"]) + ": " + row["display_name"]
                            )

                            def remove(_, row=row):
                                selected.remove(row)
                                paint()

                            ui.button(
                                text("remove"), icon="close", on_click=remove
                            ).props("flat no-caps")

            async def add():
                if not is_valid() or not control.value:
                    return
                row = await chosen(control.value)
                if not is_valid():
                    return
                item = {
                    "selector_kind": kind.value,
                    "target_id": int(control.value),
                    "recipient_type": classification.value,
                    "display_name": row["name"],
                }
                if not any(
                    all(
                        r[k] == item[k]
                        for k in ("selector_kind", "target_id", "recipient_type")
                    )
                    for r in selected
                ):
                    selected.append(item)
                control.value = None
                paint()

            ui.button(text("add"), icon="person_add", on_click=add).props(
                "outline no-caps"
            )
            paint()

    async def edit(info, version, revision):
        if not current(revision):
            return
        path = "/producers/" + info["producer_code"]
        form = {"open": True}
        is_valid = lambda: current(revision) and form["open"]
        selected = [dict(row) for row in (version or {}).get("selectors", [])]
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl gap-3"):
            ui.label(producer_name(info)).classes("text-xl font-semibold")
            ui.label(text("templates_help")).classes("text-sm text-slate-500")
            error_label = ui.label("").props("role=alert")
            owner = (
                ui.input(
                    text("owner"), value=(version or {}).get("operational_owner", "")
                )
                .props("outlined dense")
                .classes("w-full")
            )
            enabled = ui.checkbox(
                text("enabled"), value=(version or {}).get("enabled", True)
            )
            if info["required_for_business_commit"]:
                enabled.disable()
            priority = ui.select(
                {key: text(key) for key in ("normal", "high", "very_high")},
                value=(version or {}).get("priority", "normal"),
                label=text("priority"),
            ).props("outlined dense")
            modes = info["contract_definition"]["audience_modes"]
            audience = ui.select(
                {key: text("static") if key == "static" else text(key) if key in MESSAGING_MESSAGE_KEYS else key for key in modes},
                value=(version or {}).get("audience_mode", modes[0]),
                label=text("audience"),
            ).props("outlined dense")
            audience_host = ui.column().classes("w-full gap-2")
            await select_audience(audience_host, selected, is_valid)
            audience_host.set_visibility(audience.value == "static")
            audience.on_value_change(
                lambda e: audience_host.set_visibility(e.value == "static")
            )
            resource_controls = {}
            resource_schema = (
                info["contract_definition"].get("resource_configuration") or {}
            )
            if resource_schema.get("properties"):
                ui.label(text("resources")).classes("font-semibold")
                for name, rule in resource_schema["properties"].items():
                    value = (
                        (version or {})
                        .get("resource_presentation", {})
                        .get(name, rule.get("default"))
                    )
                    if rule.get("type") == "boolean":
                        control = ui.checkbox(name, value=bool(value))
                    elif rule.get("enum"):
                        control = ui.select(rule["enum"], value=value, label=name)
                    elif rule.get("type") in ("integer", "number"):
                        control = ui.number(name, value=value)
                    else:
                        control = ui.input(name, value=value or "")
                    resource_controls[name] = (
                        control,
                        (
                            "integer"
                            if rule.get("type") == "integer"
                            else rule.get("type")
                        ),
                    )
            translations = {}
            stored = {
                item["language_tag"]: item
                for item in (version or {}).get("templates", [])
            }
            for language in info["registered_languages"]:
                tag = language["language_tag"]
                original = stored.get(tag, {})
                with ui.expansion(
                    tag, value=language["is_enabled"] or tag in stored
                ).classes("w-full border border-slate-200 rounded"):
                    sub = (
                        ui.input(
                            text("subject"), value=original.get("subject_template", "")
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )
                    ui.label(text("body")).classes("text-sm")
                    editor = (
                        ui.editor(value=original.get("body_template_rich_text", ""))
                        .classes("w-full")
                        .props("min-height=100px")
                    )
                    review = ui.select(
                        {key: text(key) for key in ("draft", "reviewed", "published")},
                        value=original.get("review_status", "draft"),
                        label=text("review"),
                    ).props("outlined dense")
                    translations[tag] = (sub, editor, review, language)
                    sub.props("dir=" + language["direction"])
                    editor.props("dir=" + language["direction"])
            ui.label(text("values")).classes("font-semibold")
            inputs = context_fields(info["contract_definition"], info["sample_context"])
            preview_host = ui.column().classes("w-full gap-3")
            reason = ui.input(text("reason")).props("outlined dense").classes("w-full")
            buttons = ui.row().classes("detail-action-row " + "w-full gap-2")

            def payload():
                return {
                    "expected_version": info["latest_version"],
                    "expected_active_configuration_version_id": info[
                        "active_configuration_version_id"
                    ],
                    "enabled": enabled.value,
                    "priority": priority.value,
                    "audience_mode": audience.value,
                    "operational_owner": owner.value,
                    "resource_presentation": values(resource_controls),
                    "selectors": (
                        [
                            {
                                k: r[k]
                                for k in (
                                    "selector_kind",
                                    "target_id",
                                    "recipient_type",
                                )
                            }
                            for r in selected
                        ]
                        if audience.value == "static"
                        else []
                    ),
                    "templates": [
                        {
                            "language_tag": tag,
                            "subject_template": s.value,
                            "body_template_rich_text": b.value,
                            "review_status": status.value,
                        }
                        for tag, (s, b, status, lang) in translations.items()
                        if lang["is_enabled"] or tag == "en" or s.value or b.value
                    ],
                }

            reviewed = {"payload": None}

            async def perform(action):
                if not is_valid():
                    return
                error_label.text = ""
                for button in buttons.default_slot.children:
                    button.disable()
                try:
                    snapshot = json.dumps(
                        {"configuration": payload(), "context": values(inputs)},
                        sort_keys=True,
                    )
                    if action == "preview" or (
                        action == "save" and reviewed["payload"] != snapshot
                    ):
                        response = await request(
                            "POST",
                            path + "/preview",
                            json={
                                "configuration": payload(),
                                "context": values(inputs),
                            },
                        )
                        if not is_valid():
                            return
                        preview_host.clear()
                        with preview_host:
                            for item in response["variants"]:
                                with (
                                    ui.card()
                                    .classes(
                                        "w-full shadow-none border border-slate-200"
                                    )
                                    .props("dir=" + item["direction"])
                                ):
                                    ui.label(item["language_tag"]).classes(
                                        "text-xs text-slate-500"
                                    )
                                    ui.label(item["subject"]).classes("font-semibold")
                                    ui.html(item["body_rich_text"]).classes("w-full")
                        reviewed["payload"] = snapshot
                        if action == "save":
                            error_label.text = text("review_preview")
                    elif action == "save":
                        await request(
                            "POST",
                            path + "/versions",
                            json=payload(),
                            headers={"X-Change-Reason": reason.value or ""},
                        )
                        if is_valid():
                            ui.notify(text("saved"), color="positive")
                            dialog.close()
                            await open_producer(info["producer_code"])
                    elif action == "activate":
                        await request(
                            "POST",
                            path + "/versions/" + version["id"] + "/activate",
                            json={
                                "expected_version": info["latest_version"],
                                "expected_active_configuration_version_id": info[
                                    "active_configuration_version_id"
                                ],
                            },
                            headers={"X-Change-Reason": reason.value or ""},
                        )
                        if is_valid():
                            ui.notify(text("activated"), color="positive")
                            dialog.close()
                            await open_producer(info["producer_code"])
                except asyncio.CancelledError:
                    return
                except (ApiError, ValueError, TypeError) as error:
                    if is_valid():
                        error_label.text = text(
                            "conflict"
                            if isinstance(error, ApiError) and error.status_code == 409
                            else (
                                "validation"
                                if isinstance(error, (ValueError, TypeError))
                                or isinstance(error, ApiError)
                                and error.status_code == 422
                                else "failed"
                            )
                        )
                finally:
                    if is_valid():
                        for button in buttons.default_slot.children:
                            button.enable()

            with buttons:
                ui.button(
                    text("preview"),
                    icon="visibility",
                    on_click=lambda: perform("preview"),
                ).props("outline no-caps")
                ui.button(
                    text("save"), icon="save", on_click=lambda: perform("save")
                ).props("no-caps")
                if version:
                    ui.button(
                        text("activate"),
                        icon="check",
                        on_click=lambda: perform("activate"),
                    ).props("outline no-caps")
                    ui.button(
                        text("test"),
                        icon="science",
                        on_click=lambda: test_dialog(info, version, revision),
                    ).props("outline no-caps")
                ui.button(text("cancel"), on_click=dialog.close).props("flat no-caps")
        dialog.on("hide", lambda: form.update(open=False))
        dialog.open()

    async def test_dialog(info, version, revision):
        if not current(revision):
            return
        form = {"open": True}
        is_valid = lambda: current(revision) and form["open"]
        selected = []
        test_id = str(uuid4())
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl gap-3"):
            ui.label(text("test_label")).classes("text-lg font-bold")
            ui.label(
                producer_name(info)
                + " · "
                + text("version")
                + " "
                + str(version["version"])
            )
            ui.label(text("test_help")).classes("text-sm text-slate-600")
            ui.label(
                render_message(
                    "messaging.admin.test_limits",
                    recipients=info["limits"]["TEST_MAX_RECIPIENTS"],
                    rate=info["limits"]["TEST_SENDS_PER_HOUR"],
                )
            ).classes("text-sm font-semibold")
            host = ui.column().classes("w-full gap-2")
            await select_audience(host, selected, is_valid, test=True)
            inputs = context_fields(info["contract_definition"], info["sample_context"])
            error_label = ui.label("").props("role=alert")

            async def send():
                if not is_valid():
                    return
                submit.disable()
                try:
                    response = await request(
                        "POST",
                        "/producers/" + info["producer_code"] + "/test",
                        json={
                            "test_run_id": test_id,
                            "configuration_version_id": version["id"],
                            "context": values(inputs),
                            "recipient_user_ids": [r["target_id"] for r in selected],
                        },
                    )
                    if is_valid():
                        ui.notify(text("sent"), color="positive")
                        dialog.close()
                except asyncio.CancelledError:
                    return
                except (ApiError, ValueError, TypeError):
                    if is_valid():
                        error_label.text = text("validation")
                        submit.enable()

            with ui.row().classes("detail-action-row " + "gap-2"):
                submit = ui.button(
                    text("confirm_test"), icon="science", on_click=send
                ).props("no-caps")
                ui.button(text("cancel"), on_click=dialog.close).props("flat no-caps")
        dialog.on("hide", lambda: form.update(open=False))
        dialog.open()

    async def show_history(info, revision):
        form = {"open": True, "before": None, "previous": [], "next": None}
        is_valid = lambda: current(revision) and form["open"]
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl gap-3"):
            ui.label(text("history")).classes("text-xl font-semibold")
            ui.label(text("test_label")).classes("font-bold")
            host = ui.column().classes("w-full gap-2")
            with ui.row().classes("detail-action-row " + "gap-2"):
                prev = ui.button(text("previous")).props("outline no-caps")
                nxt = ui.button(text("next")).props("outline no-caps")
                ui.button(text("cancel"), on_click=dialog.close).props("flat no-caps")

        async def load_history(forward=None):
            if forward is True:
                form["previous"].append(form["before"])
                form["before"] = form["next"]
            elif forward is False:
                form["before"] = form["previous"].pop()
            try:
                params = {"limit": 25}
                if form["before"]:
                    params["before"] = form["before"]
                response = await request(
                    "GET",
                    "/producers/" + info["producer_code"] + "/tests",
                    params=params,
                )
            except asyncio.CancelledError:
                return
            except ApiError:
                if is_valid():
                    host.clear()
                    with host:
                        ui.label(text("failed"))
                return
            if not is_valid():
                return
            host.clear()
            form["next"] = response["next_cursor"]
            prev.set_enabled(bool(form["previous"]))
            nxt.set_enabled(bool(form["next"]))
            with host:
                if not response["items"]:
                    ui.label(text("empty"))
                for row in response["items"]:
                    with ui.card().classes(
                        "w-full shadow-none border border-slate-200"
                    ):
                        ui.label(
                            text("success")
                            if row["metadata"]["result"] in ("created", "existing")
                            else text("failure")
                        ).classes("font-semibold")
                        ui.label(format_timestamp(row["occurred_at"]))
                        ui.label(
                            text("initiator")
                            + ": "
                            + (row["actor_name"] or str(row["actor_user_id"]))
                        )
                        ui.label(
                            text("recipient_count")
                            + ": "
                            + str(row["metadata"]["recipient_count"])
                        )
                        ui.label(
                            text("version")
                            + ": "
                            + row["metadata"]["configuration_version_id"]
                        ).classes("text-sm break-all")

        prev.on("click", lambda: load_history(False))
        nxt.on("click", lambda: load_history(True))
        dialog.on("hide", lambda: form.update(open=False))
        dialog.open()
        await load_history()

    await load(True)
