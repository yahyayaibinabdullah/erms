"""Exercise metadata administration, rendering and search through the assembled WebUI."""

import re
from time import perf_counter


def seed_language():
    from tools.seed_webui_regression import disposable_url
    import psycopg

    with psycopg.connect(disposable_url()) as c:
        c.execute(
            "SELECT set_config('app.event_source','seeding',true), set_config('app.change_reason','Third language for the disposable UI fixture',true)"
        )
        c.execute(
            """INSERT INTO supported_languages(language_tag,english_name,native_name,direction,is_enabled)
            VALUES('fr','French','Français','ltr',true) ON CONFLICT(language_tag) DO NOTHING"""
        )


def check_types(page):
    def t(key):
        return page.t("resource_types.ui." + key)

    def dialog():
        return page.wait.until(
            lambda _: (page.visible(".q-dialog__inner > .q-card") or [False])[-1]
        )

    def row(label, container=None):
        return page.wait.until(
            lambda _: next(
                (
                    r
                    for r in page.visible(".erms-page-table tbody tr", container)
                    if label in r.text
                ),
                False,
            )
        )

    def action(key, scope):
        page.click(t(key), scope=scope)

    def row_action(key, name, container=None):
        # Vue can replace a visible row as its page finishes rendering. Resolve
        # the row and its button together on each WebDriver poll.
        def click_current(_):
            for item in page.visible(".erms-page-table tbody tr", container):
                if name in item.text:
                    for button in page.visible("button", item):
                        if button.get_attribute("aria-label") == t(key) and button.is_enabled():
                            page.activate(button)
                            return True
            return False

        page.wait.until(click_current, f"Missing {key} action on {name}")

    def enter(kind):
        old_tables = {table.id for table in page.visible(".erms-page-table")}
        page.activate(page.one("button.erms-nav-link", t(kind + "_catalogue")))
        page.wait.until(lambda _: any(table.id not in old_tables for table in page.visible(".erms-page-table")))

    def choose(label):
        page.activate(page.one("[role=option]", label))

    def type_data(kind):
        root = "/api/v1/" + kind + "-types"

        def post(path, body, code=201):
            headers = (
                {
                    "If-Match": str(
                        page.api.get(root + "/" + str(owner["id"])).json()["version"]
                    )
                }
                if path != root
                else {}
            )
            response = page.api.post(path, json=body, headers=headers)
            assert response.status_code == code, response.text
            return response.json()

        owner = post(
            root, {"name": "Permit", "translations": {"ar": {"name": "تصريح"}}}
        )
        fields = root + f"/{owner['id']}/fields"
        f = post(
            fields,
            {
                "name": "Grade",
                "data_type": "single_choice",
                "display_order": 0,
                "translations": {"ar": {"name": "درجة"}},
            },
        )
        choice = post(
            fields + f"/{f['id']}/choices",
            {
                "name": "Standard",
                "display_order": 1,
                "translations": {"ar": {"name": "عادي"}},
            },
        )
        post(
            fields,
            {
                "name": "Note",
                "data_type": "text",
                "display_order": 2,
                "max_length": 700,
                "default": "literal",
                "required": True,
            },
        )
        return owner, f, choice

    fixtures = {kind: type_data(kind) for kind in ("aggregation", "record")}
    root = page.api.post(
        "/api/v1/aggregations/search",
        json={
            "where": {
                "field": "aggregation_number",
                "operator": "eq",
                "value": "TEST-AGG",
            },
            "limit": 1,
        },
    ).json()["items"][0]
    agg_owner, agg_field, agg_choice = fixtures["aggregation"]
    current = page.api.get(f"/api/v1/aggregations/{root['id']}").json()
    page.api.patch(
        f"/api/v1/aggregations/{root['id']}",
        headers={"If-Match": str(current["version"])},
        json={
            "type_id": agg_owner["id"],
            "field_values": {str(agg_field["id"]): agg_choice["id"]},
        },
    ).raise_for_status()
    records = page.api.post(
        "/api/v1/records",
        json={
            "aggregation_id": root["id"],
            "record_number": "TYPED-001",
            "title": "Permit document",
            "medium": "physical",
            "date_originated": "2026-01-01T00:00:00Z",
            "type_id": fixtures["record"][0]["id"],
            "field_values": {
                str(fixtures["record"][1]["id"]): fixtures["record"][2]["id"]
            },
        },
    )
    records.raise_for_status()
    owner, field, choice = fixtures["record"]
    sort_key = f"type.{owner['id']}.field.{field['id']}"
    saved = page.api.post(
        "/api/v1/saved-searches",
        json={
            "name": "Typed permit lookup",
            "audience_mode": "private",
            "definition": {
                "schema_version": 1,
                "resource_type": "record",
                "max_results": 1000,
                "request": {
                    "where": {
                        "and": [
                            {
                                "field": "title",
                                "operator": "contains_ci",
                                "value": "Permit",
                            },
                            {
                                "field": sort_key,
                                "operator": "eq",
                                "value": choice["id"],
                            },
                        ]
                    },
                    "sort": [{"field": sort_key, "direction": "desc"}],
                    "limit": 25,
                    "offset": 0,
                },
            },
        },
    )
    saved.raise_for_status()

    def table_style():
        header = page.one(".erms-page-table thead tr")
        return page.driver.execute_script(
            """
            const cell=arguments[0].querySelector('th'), style=getComputedStyle(cell);
            return [style.backgroundColor,style.fontFamily,style.paddingInlineStart];
        """,
            header,
        )

    for lang in ("en", "ar"):
        if lang == "ar":
            page.settings()
            page.language_change("ar")
        owner_label = "Permit" if lang == "en" else "تصريح"
        field_label = "Grade" if lang == "en" else "درجة"
        choice_label = "Standard" if lang == "en" else "عادي"
        page.activate(
            page.one("button.erms-nav-link", page.t("relationships.ui.catalogue"))
        )
        reference_style = table_style()
        for kind in ("aggregation", "record"):
            with page.check(
                kind
                + " type administration, field choices, role directory and repeat navigation"
            ):
                start = perf_counter()
                before = len(page.events())
                enter(kind)
                row(owner_label)
                assert table_style() == reference_style
                paths = [
                    e
                    for e in page.events()[before:]
                    if e["path"].startswith("/api/v1/" + kind + "-types")
                ]
                assert len(paths) == 1
                page.report.setdefault("type_ui_navigation", []).append(
                    dict(
                        kind=kind,
                        language=lang,
                        seconds=perf_counter() - start,
                        requests=len(paths),
                    )
                )
                row_action("fields", owner_label)
                fields = dialog()
                row_action("choices", field_label, fields)
                page.wait.until(
                    lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2
                )
                choices = dialog()
                row(choice_label, choices)
                if kind == "record" and lang == "en":
                    action("add", choices)
                    page.wait.until(
                        lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 3
                    )
                    page.fill(t("name"), "Expedited")
                    page.fill(t("order"), "2")
                    action("save", dialog())
                    row("Expedited", choices)
                    row_action("edit", "Expedited", choices)
                    page.wait.until(
                        lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 3
                    )
                    page.fill(t("name"), "Urgent")
                    action("save", dialog())
                    row_action("delete", "Urgent", choices)
                    page.see(t("delete_confirm"))
                    action("delete", dialog())
                    page.wait.until(lambda _: "Urgent" not in choices.text)
                page.capture("types-" + kind + "-choices-" + lang)
                if kind == "record":
                    original_size = page.driver.get_window_size()
                    try:
                        page.driver.set_window_size(470, 850)
                        page.wait.until(
                            lambda _: page.driver.execute_script(
                                "const r=arguments[0].getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth+1;",
                                choices,
                            )
                        )
                        search = next(
                            f
                            for f in page.visible(".q-field", choices)
                            if t("search") in f.text
                        ).find_element("css selector", "input")
                        search.click()
                        search.send_keys("\ue004")
                        assert page.driver.execute_script(
                            "return arguments[0].contains(document.activeElement)",
                            choices,
                        )
                        page.capture("types-record-choices-narrow-" + lang)
                    finally:
                        page.driver.set_window_size(
                            original_size["width"], original_size["height"]
                        )
                action("close", choices)
                page.wait.until(
                    lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 1
                )
                action("close", fields)
                page.wait.until(
                    lambda _: not page.visible(".q-dialog__inner > .q-card")
                )
                row_action("access", owner_label)
                page.see(t("policy_help"))
                policy = dialog()
                if kind == "record" and lang == "en":
                    row_action("edit", "Test officer", policy)
                    page.wait.until(
                        lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2
                    )
                    grant = dialog()
                    use = page.one("[role=checkbox]", t("use"), scope=grant)
                    see = page.one("[role=checkbox]", t("see"), scope=grant)
                    page.activate(use)
                    page.wait.until(
                        lambda _: see.get_attribute("aria-checked") == "true"
                    )
                    action("save", grant)
                    page.wait.until(
                        lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 1
                    )
                    page.wait.until(
                        lambda _: row("Test officer", policy).text.count(t("yes")) == 2
                    )
                action("close", policy)
                page.settings()
                enter(kind)
                row_action("edit", owner_label)
                editor = dialog()
                page.activate(page.one(".q-expansion-item .q-item", scope=editor))
                language = page.t("webui.open_editor.select.language_a1337600")
                page.activate(page.field(language))
                choose("Français · French")
                translated = page.t("entity_translation_editor.input.name")
                target = page.wait.until(
                    lambda _: next(
                        (
                            f.find_element("css selector", "input")
                            for f in page.visible(".q-expansion-item .q-field", editor)
                            if any(
                                x.text == translated
                                for x in f.find_elements(
                                    "css selector", ".q-field__label"
                                )
                            )
                        ),
                        False,
                    )
                )
                page.wait.until(lambda _: target.is_enabled())
                page.select_field_text(target)
                target.send_keys("Permis " + kind)
                if kind == "record" and lang == "en":
                    page.control(
                        path=f"/api/v1/record-types/{fixtures[kind][0]['id']}",
                        method="PUT",
                        status=412,
                    )
                    action("save", editor)
                    page.see(t("conflict"))
                    assert target.get_attribute("value") == "Permis record"
                    page.control()
                action("save", editor)
                page.wait.until(
                    lambda _: not page.visible(".q-dialog__inner > .q-card")
                )
                result = page.api.get(
                    f"/api/v1/{kind}-types/{fixtures[kind][0]['id']}"
                ).json()
                assert result["translations"]["fr"]["name"] == "Permis " + kind
                assert result["translations"]["ar"]["name"] == "تصريح"

        for kind, number in [("aggregation", "TEST-AGG"), ("record", "TYPED-001")]:
            with page.check(
                kind
                + " metadata renders below primary metadata and the existing editor uses a dropdown"
            ):
                page.drawer(kind + "s")
                page.fill(
                    page.t(
                        "webui.index.input.search_by_number_title_or_description_e21ed520"
                    ),
                    number,
                )
                page.click(
                    page.t("webui.index.button.search_4d02b714"),
                    scope=page.one(".erms-shared-control.items-end"),
                )
                page.activate(
                    page.one(
                        f'button[aria-label="Open {kind}"]',
                        scope=page.one(".compact-result-item"),
                    )
                )
                page.click(
                    page.t("resource_details.details"),
                    scope=page.one(".resource-detail-header"),
                )
                details = dialog()
                section = page.one(".type-metadata-section", scope=details)
                page.wait.until(
                    lambda _: choice_label in section.text and "literal" in section.text
                )
                assert details.text.index(t("primary")) < details.text.index(
                    t("section")
                )
                page.capture("types-" + kind + "-details-" + lang)
                edit_key = (
                    "webui.select_record_details.button.edit_metadata_d7742b94"
                    if kind == "record"
                    else "webui.open_aggregation.button.edit_metadata_3ee4d255"
                )
                page.click(page.t(edit_key), scope=details)
                page.wait.until(
                    lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2
                )
                editor = dialog()
                page.one(".type-metadata-section .q-select", scope=editor)
                page.one(".type-metadata-section textarea", scope=editor)
                page.capture("types-" + kind + "-editor-" + lang)
                if lang == "en" and kind == "record":
                    note = page.one(".type-metadata-section textarea", scope=editor)
                    page.select_field_text(note)
                    note.send_keys("literal changed in browser")
                    page.click(
                        page.t("webui.open_editor.button.save_46081ed6"), scope=editor
                    )
                    page.wait.until(
                        lambda _: "literal changed in browser"
                        in page.api.get(f"/api/v1/records/{records.json()['id']}")
                        .json()["field_values"]
                        .values()
                    )
                    page.wait.until(lambda _: any(
                        "literal changed in browser" in section.text
                        for section in page.visible(".q-dialog .type-metadata-section")
                    ))
                else:
                    page.click(
                        page.t("webui.open_editor.button.cancel_c07bff03"), scope=editor
                    )
                page.wait.until(
                    lambda _: len(page.visible(".q-dialog__inner > .q-card")) <= 1
                )
                if page.visible(".q-dialog__inner > .q-card"):
                    page.driver.find_element("tag name", "body").send_keys("\ue00c")
                page.wait.until(
                    lambda _: not page.visible(".q-dialog__inner > .q-card")
                )

        if lang == "en":
            with page.check(
                "create a physical typed record from its parent with a static default"
            ):
                page.drawer("aggregations")
                page.fill(
                    page.t(
                        "webui.index.input.search_by_number_title_or_description_e21ed520"
                    ),
                    "TEST-AGG",
                )
                page.click(
                    page.t("webui.index.button.search_4d02b714"),
                    scope=page.one(".erms-shared-control.items-end"),
                )
                page.activate(
                    page.one(
                        'button[aria-label="Open aggregation"]',
                        scope=page.one(".compact-result-item"),
                    )
                )
                page.click(page.t("webui.index.button.add_record_fc8125c4"))
                draft = dialog()
                page.fill(
                    page.t("entity_metadata.field.record_number") + " *", "BROWSER-P5"
                )
                page.fill(
                    page.t("entity_metadata.field.title") + " *",
                    "Browser draft fixture",
                )
                section = page.one(".type-metadata-section", scope=draft)
                page.click(t("type") + " · " + t("unset"), scope=section)
                page.wait.until(
                    lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2
                )
                picker = dialog()
                option = row(owner_label, picker)
                page.activate(page.one("[role=checkbox]", scope=option))
                confirm = page.button(t("select"), scope=picker)
                page.wait.until(lambda _: confirm.is_enabled())
                page.activate(confirm)
                page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 1)
                page.wait.until(
                    lambda _: page.one("textarea", scope=section).get_attribute("value")
                    == "literal"
                )
                page.click(
                    page.t(
                        "webui.open_record_draft_editor.button.create_record_dd0193d6"
                    ),
                    scope=draft,
                )
                page.wait.until(
                    lambda _: not page.visible(".q-dialog__inner > .q-card")
                )
                resource = page.api.post(
                    "/api/v1/records/search",
                    json={
                        "where": {
                            "field": "record_number",
                            "operator": "eq",
                            "value": "BROWSER-P5",
                        }
                    },
                ).json()["items"][0]
                snapshot = page.api.get(f"/api/v1/records/{resource['id']}").json()
                assert (
                    snapshot["type_id"] == fixtures["record"][0]["id"]
                    and "literal" in snapshot["field_values"].values()
                )

        with page.check(
            "mixed saved query restores typed choices and sort before execution"
        ):
            page.drawer("advanced_search")
            page.click(
                page.t("webui.select_advanced_search.button.open_saved_search_8bef667f")
            )
            page.see("Typed permit lookup")
            page.click(
                page.t("webui.load_saved_page.button.open_2606a7e0"), scope=dialog()
            )
            page.wait.until(lambda _: not page.visible(".q-dialog__inner > .q-card"))
            page.see(owner_label + " · " + field_label)
            page.capture("types-advanced-" + lang)
            before = len(page.events())
            start = perf_counter()
            page.click(
                page.t("webui.select_advanced_search.button.search_97989f23"),
                scope=page.one(".advanced-search-submit-row"),
            )
            page.see("TYPED-001")
            requests = page.events()[before:]
            assert not any(
                re.search(r"/(?:records|aggregations)/[0-9]+/capabilities", r["path"])
                for r in requests
            )
            page.report.setdefault("type_ui_search", []).append(
                dict(
                    language=lang,
                    seconds=perf_counter() - start,
                    requests=[
                        {"method": r["method"], "path": r["path"]} for r in requests
                    ],
                )
            )
