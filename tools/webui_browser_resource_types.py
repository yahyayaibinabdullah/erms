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
        c.execute("""INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id)
            SELECT 'picker-'||n, 'Picker '||lpad(n::text,2,'0'), r.org_unit_id,r.profile_id,r.security_level_id
            FROM (SELECT * FROM roles WHERE org_unit_id IS NOT NULL ORDER BY id LIMIT 1) r
            CROSS JOIN generate_series(1,32) n""")


def check_types(page):
    from selenium.webdriver.common.keys import Keys

    def t(key):
        if key in {"earlier", "later"}:
            message = {"earlier": "webui.render_component_cards.tooltip.move_earlier_0de89c72",
                       "later": "webui.render_component_cards.tooltip.move_later_71077211"}
            return page.t(message[key])
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

    def check_field_editor(lang, fields):
        action("add", fields)
        page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2)
        field_name = "Keyboard limit " + lang
        page.fill(t("name"), field_name)
        order = page.field(t("order"))
        assert [order.get_attribute(key) for key in ("type", "min", "max", "value")] == ["number", "1", "3", "3"]
        page.activate(order)
        order.send_keys(Keys.BACKSPACE, "0-.e4")
        assert order.get_property("value") == ""
        action("save", dialog())
        page.see(t("invalid"))
        page.activate(order)
        order.send_keys("2", "9")
        assert order.get_property("value") == "2"
        order.send_keys(Keys.ARROW_UP, Keys.ARROW_UP)
        assert order.get_property("value") == "3"
        maximum = page.field(t("maximum"))
        assert maximum.get_attribute("type") == "number"
        assert maximum.get_attribute("step") == "1"
        assert maximum.get_attribute("value") == "255"
        page.fill(t("default"), "abc")
        page.activate(maximum)
        maximum.send_keys("1024")
        page.wait.until(lambda _: maximum.get_attribute("value") == "1024",
                        "Typing directly should replace the initial suggestion")
        page.select_field_text(maximum)
        maximum.send_keys(Keys.BACKSPACE)
        action("save", dialog())
        page.see(t("invalid"))
        page.activate(maximum)
        maximum.send_keys("abcd")
        assert maximum.get_attribute("value") == ""
        maximum.send_keys("11--")
        assert maximum.get_property("value") == "11", "Hyphens must leave the entered digits intact"
        maximum.send_keys("+.eE")
        assert maximum.get_property("value") == "11"
        assert not page.driver.execute_script("return arguments[0].validity.badInput", maximum)
        # Check the complete transferred string without touching the user's clipboard.
        for event in ("paste", "drop"):
            for text, allowed in (("1e3", False), ("2048", True)):
                assert page.driver.execute_script("""
                    const [field, name, text] = arguments;
                    const transfer = new DataTransfer();
                    transfer.setData('text/plain', text);
                    const init = {bubbles: true, cancelable: true};
                    const event = name === 'paste'
                        ? new ClipboardEvent(name, {...init, clipboardData: transfer})
                        : new DragEvent(name, {...init, dataTransfer: transfer});
                    return field.dispatchEvent(event);
                """, maximum, event, text) == allowed
        page.select_field_text(maximum)
        maximum.send_keys("2147483647")
        assert maximum.get_property("value") == "2147483647"
        maximum.send_keys("0", Keys.ARROW_UP)
        assert maximum.get_property("value") == "2147483647"
        # Replacing the last digit must validate the resulting number.
        maximum.send_keys(Keys.END, Keys.SHIFT, Keys.ARROW_LEFT, Keys.NULL, "6")
        assert maximum.get_property("value") == "2147483646"
        maximum.send_keys(Keys.END, Keys.SHIFT, Keys.ARROW_LEFT, Keys.NULL, "8")
        assert maximum.get_property("value") == "2147483646"
        # Insert a complete string in one browser edit, as with paste.
        for digits, expected in (("2147483648", "2147483646"), ("2147483647", "2147483647")):
            page.select_field_text(maximum)
            page.driver.execute_script("document.execCommand('insertText', false, arguments[0])", digits)
            assert maximum.get_property("value") == expected
        page.select_field_text(maximum)
        maximum.send_keys(Keys.BACKSPACE, "0")
        assert maximum.get_property("value") == ""
        page.select_field_text(maximum)
        maximum.send_keys("1024")
        maximum.send_keys(Keys.ARROW_UP)
        page.wait.until(lambda _: maximum.get_attribute("value") == "1025")
        maximum.send_keys(Keys.ARROW_DOWN)
        page.wait.until(lambda _: maximum.get_attribute("value") == "1024")
        page.wait.until(lambda _: page.field(t("default")).tag_name == "textarea")
        assert page.field(t("default")).get_attribute("value") == "abc"
        action("save", dialog())
        def wait_position(position):
            page.wait.until(lambda _: row(field_name, fields).find_elements("css selector", "td")[1].text == str(position))

        wait_position(3)
        row_action("earlier", field_name, fields)
        wait_position(2)
        row_action("later", field_name, fields)
        wait_position(3)
        # Show just the test field. Its editor still has all three positions.
        search = fields.find_element("css selector", "input[type=text]")
        search.send_keys(field_name, Keys.ENTER)
        page.wait.until(lambda _: len(page.visible(".erms-page-table tbody tr", fields)) == 1)
        row_action("edit", field_name, fields)
        page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2)
        order = page.field(t("order"))
        assert order.get_attribute("max") == "3"
        page.select_field_text(order)
        page.driver.execute_script("document.execCommand('insertText', false, '4')")
        assert order.get_property("value") == "3"
        assert page.field(t("maximum")).get_attribute("value") == "1024"
        assert page.field(t("default")).get_attribute("value") == "abc"
        page.fill(t("order"), "1")
        page.fill(t("maximum"), "255")
        page.wait.until(lambda _: page.field(t("default")).tag_name == "input")
        assert page.field(t("default")).get_attribute("value") == "abc"
        action("save", dialog())
        page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 1)
        wait_position(1)
        row_action("delete", field_name, fields)
        page.see(t("delete_confirm"))
        action("delete", dialog())
        page.wait.until(lambda _: field_name not in fields.text)
        page.select_field_text(search)
        search.send_keys(Keys.BACKSPACE, Keys.ENTER)
        page.wait.until(lambda _: len(page.visible(".erms-page-table tbody tr", fields)) == 2)

    def check_typed_defaults(fields):
        action("add", fields)
        page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2)
        page.fill(t("name"), "Input regression")
        def open_select(key):
            control = page.wait.until(lambda _: next((item for item in page.visible(".q-select", dialog())
                if item.find_element("css selector", ".q-field__label").text == t(key)), False))
            page.activate(control)

        def select_type(dtype):
            open_select("data_type")
            choose(t(dtype))

        page.fill(t("maximum"), "2")
        value = page.field(t("default"))
        value.send_keys("abx")
        assert value.get_property("value") == "ab"
        for dtype, valid, appended, invalid in (
            ("integer", "-9223372036854775808", "1", "-"),
            ("decimal", "-1.234567890123456789e-2", "x", "1e-"),
        ):
            select_type(dtype)
            value = page.field(t("default"))
            page.wait.until(lambda _: value.get_attribute("inputmode") == ("numeric" if dtype == "integer" else "decimal"))
            value.send_keys(valid)
            value.send_keys(appended)
            assert value.get_property("value") == valid
            page.select_field_text(value)
            value.send_keys(invalid)
            action("save", dialog())
            page.see(t("invalid"))
        for dtype, native_type, valid, invalid in (
            ("date", "date", "2028-02-29", "2027-02-29"),
            ("datetime", "datetime-local", "2028-02-29T13:14", "2028-02-29T25:14"),
        ):
            select_type(dtype)
            value = page.field(t("default"))
            assert value.get_attribute("type") == native_type
            for typed, expected in ((invalid, ""), (valid, valid)):
                assert page.driver.execute_script("arguments[0].value=arguments[1]; return arguments[0].value",
                                                  value, typed) == expected
        select_type("boolean")
        open_select("default")
        choose(t("no"))
        select_type("single_choice")
        page.see(t("default_choice"))
        action("cancel", dialog())

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
                check_field_editor(lang, fields)
                check_typed_defaults(fields)
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
                    order = page.field(t("order"))
                    page.select_field_text(order)
                    order.send_keys(Keys.BACKSPACE, "x.e")
                    assert order.get_property("value") == ""
                    order.send_keys("-2147483648", "0")
                    assert order.get_property("value") == "-2147483648"
                    page.fill(t("order"), "2")
                    order.send_keys(Keys.END, "--")
                    assert order.get_property("value") == "2"

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
                action("add", policy)
                page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2)
                picker = dialog()
                everyone = page.t("webui.render_principals.label.everyone_8d69f084")
                # Select another role on a later page, then find both selections by search.
                named = "Picker 32" if lang == "en" else "Picker 31"
                def box(name, permission):
                    return page.one("[role=checkbox]", t(permission), scope=row(name, picker))

                def toggle_box(name, permission):
                    # Page loads can replace a row between locating and clicking it.
                    def click_current(_):
                        page.activate(box(name, permission))
                        return True
                    page.wait.until(click_current)

                def filter_roles(panel, term, name):
                    query = panel.find_element("css selector", "input[type=text]")
                    page.select_field_text(query)
                    query.send_keys(term, Keys.ENTER)
                    def one_matching_row(_):
                        rows = page.visible(".erms-page-table tbody tr", panel)
                        return len(rows) == 1 and name in rows[0].text
                    page.wait.until(one_matching_row)

                assert not page.button(t("add") + " (0)", picker).is_enabled()
                toggle_box(everyone, "see")
                page.click(page.t("relationships.ui.next"), scope=picker)
                toggle_box(named, "use")
                page.wait.until(lambda _: box(named, "see").get_attribute("aria-checked") == "true")
                filter_roles(picker, everyone, everyone)
                assert box(everyone, "see").get_attribute("aria-checked") == "true"
                assert box(everyone, "use").get_attribute("aria-checked") == "false"
                # Mixed-case interior of the role code (the display name has a space).
                code_fragment = "KeR-" + named.split()[-1]
                filter_roles(picker, code_fragment, named)
                toggle_box(named, "use")
                assert box(named, "see").get_attribute("aria-checked") == "true"
                toggle_box(named, "see")
                page.button(t("add") + " (1)", picker)
                toggle_box(named, "use")
                page.capture("types-" + kind + "-role-picker-" + lang)
                page.click(t("add") + " (2)", scope=picker)
                page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 1)
                assert row(named, policy).text.count(t("yes")) == 2
                assert t("no") in row(everyone, policy).text
                cells = row(everyone, policy).find_elements("css selector", "td")
                assert [c.text for c in cells[:-1]] == [everyone, t("yes"), t("no")]
                edit_button = page.one("button", t("edit"), scope=cells[-1])
                use_x, edit_x = cells[-2].rect["x"], edit_button.rect["x"]
                assert edit_x > use_x if lang == "en" else edit_x < use_x
                page.capture(f"types-{kind}-role-access-{lang}")
                filter_roles(policy, code_fragment, named)
                filter_roles(policy, everyone, everyone)
                row_action("edit", everyone, policy)
                page.wait.until(lambda _: len(page.visible(".q-dialog__inner > .q-card")) == 2)
                grant = dialog()
                page.activate(page.one("[role=checkbox]", t("see"), scope=grant))
                action("save", grant)
                page.wait.until(lambda _: everyone not in policy.text)
                filter_roles(policy, code_fragment, named)
                assert row(named, policy).text.count(t("yes")) == 2
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
