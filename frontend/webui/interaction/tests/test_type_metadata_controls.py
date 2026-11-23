"""Exercise typed forms, cancellation and stale responses with real NiceGUI controls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nicegui import ui
import pytest

from frontend.webui import type_controls
from frontend.webui.api_client import ApiError
from frontend.webui.type_controls import MetadataForm

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.asyncio


def definition(identity, dtype, **extra):
    return {
        "id": identity,
        "name": dtype.title(),
        "data_type": dtype,
        "required": False,
        "default": None,
        "max_length": None,
        **extra,
    }


async def test_new_assignment_defaults_required_unicode_exact_scalars_and_paging(
    user, monkeypatch
):
    fields = [
        definition(1, "boolean", default=False, required=True),
        definition(2, "text", max_length=256, required=True),
        definition(3, "integer", default=0),
        definition(4, "decimal", default="1.0000000000000001"),
    ]
    fields += [definition(i, "date") for i in range(5, 27)]

    async def request(method, path, *, params):
        assert method == "GET" and params["limit"] == 25
        start = params["offset"]
        return {"total": len(fields), "items": fields[start : start + 25]}

    form = MetadataForm(SimpleNamespace(request=request), "record")

    @ui.page("/")
    async def page():
        await form.render()

    await user.open("/")
    with user:
        assert await form.assign({"id": 5})
        editor = next(
            e for e in form.fields.descendants() if isinstance(e, ui.textarea)
        )
        with pytest.raises(ValueError):
            form.payload()
        editor.value = "ع" * 256
        decimal = next(
            e
            for e in form.fields.descendants()
            if isinstance(e, ui.input) and e.label == "Decimal"
        )
        decimal.value = "0.00000000000000000001"
        await form.page(25)
        assert form.payload() == {
            "type_id": 5,
            "field_values": {"2": "ع" * 256, "4": "0.00000000000000000001"},
        }
        await form.page(0)
        assert (
            next(
                e for e in form.fields.descendants() if isinstance(e, ui.textarea)
            ).value
            == "ع" * 256
        )
        monkeypatch.setattr(type_controls, "confirmed", AsyncMock(return_value=False))
        assert not await form.assign(None)
        assert form.selected == 5


async def test_reassignment_confirms_only_stored_data_and_revoked_or_stale_reads_cannot_submit(
    user, monkeypatch
):
    pending = asyncio.Event()
    started = asyncio.Event()

    async def request(method, path, *, params):
        if path.endswith("/1"):
            return {"id": 1, "name": "Original"}
        if "/1/fields" in path:
            return {"items": [definition(1, "text", max_length=8)], "total": 1}
        if "/2/fields" in path:
            started.set()
            await pending.wait()
            return {"items": [definition(22, "integer")], "total": 1}
        raise ApiError(404, "No access")

    form = MetadataForm(
        SimpleNamespace(request=request),
        "aggregation",
        {"type_id": 1, "field_values": {"1": "Old"}},
    )

    @ui.page("/")
    async def page():
        await form.render()

    await user.open("/")
    monkeypatch.setattr(type_controls, "confirmed", AsyncMock(return_value=True))
    with user:
        slow = asyncio.create_task(form.assign({"id": 2}))
        await asyncio.wait_for(started.wait(), 2)
        await form.assign({"id": 3})
        with pytest.raises(ValueError):
            form.payload()
        pending.set()
        await slow
        assert "22" not in form.definitions
        await form.assign(None)
        assert form.payload() == {
            "type_id": None,
            "field_values": {},
            "confirm_type_change": True,
        }


async def test_catalogue_pages_use_submitted_filter_and_ignore_old_navigation(user):
    from frontend.webui.type_administration import type_administration
    from frontend.webui.type_controls import t

    from frontend.webui.locale_services import set_locale_context

    called = asyncio.Event()

    class Directory:
        requests = []

        async def request(self, method, path, *, params):
            self.requests.append(dict(params))
            called.set()
            start = params["offset"]
            return {
                "total": 75,
                "items": [
                    {"id": i + 1, "name": f"Type {i+1}", "version": 1}
                    for i in range(start, start + params["limit"])
                ],
            }

    api = Directory()

    @ui.page("/")
    async def page():
        set_locale_context("en", "UTC")
        await type_administration(
            api=api,
            kind="aggregation",
            container=ui.column(),
            languages=[],
            active=lambda: True,
            on_error=str,
        )

    await user.open("/")
    with user:
        query = next(
            e for e in user.client.elements.values() if isinstance(e, ui.input)
        )
        called.clear()
        query.value = "submitted"
        button = next(
            e
            for e in user.client.elements.values()
            if isinstance(e, ui.button) and e.text == t("search")
        )
        button.mark("apply-directory-filter")
        user.find(marker="apply-directory-filter").click()
    await asyncio.wait_for(called.wait(), 2)
    assert api.requests[-1]["q"] == "submitted"
    with user:
        called.clear()
        query.value = "unsubmitted"
        next_button = next(
            e
            for e in user.client.elements.values()
            if isinstance(e, ui.button) and e.props.get("icon") == "chevron_right"
        )
        next_button.mark("next-directory-page")
        user.find(marker="next-directory-page").click()
    await asyncio.wait_for(called.wait(), 2)
    assert (
        api.requests[-1]["q"] == "submitted" and api.requests[-1]["offset"] == 25
    ), api.requests


@pytest.mark.parametrize("kind", ["aggregation", "record"])
@pytest.mark.parametrize(("dtype", "valid", "wire", "bad"), [
    ("text", "ع😀", "ع😀", "ع😀x"),
    ("integer", "-9223372036854775808", -(2**63), "9223372036854775808"),
    ("decimal", "-1.230000000000000001e-12", "-1.230000000000000001e-12", "1e-"),
    ("boolean", False, False, None),
    ("date", "2028-02-29", "2028-02-29", "2027-02-29"),
    ("datetime", "2028-02-29T14:15", "2028-02-29T10:15:00+00:00", "2028-02-29"),
    ("single_choice", 17, 17, None),
])
async def test_resource_editor_and_search_condition_values(user, kind, dtype, valid, wire, bad):
    from frontend.webui.locale_services import set_locale_context
    from frontend.webui.type_search_controls import render_type_condition

    field = definition(1, dtype, max_length=2 if dtype == "text" else None,
                       default=17 if dtype == "single_choice" else None)
    choice = {"id": 17, "name": "Closed"}
    owner = {"id": 5, "name": "Case"}

    async def request(method, path, *, params=None):
        if path.endswith("/5"):
            return owner
        items = [choice] if path.endswith("/choices") else [field]
        return {"items": items, "total": len(items)} if (params or {}).get("paged") else items

    api = SimpleNamespace(request=request)
    form = MetadataForm(api, kind)
    node = {"kind": "type_field", "field": "type.5.field.1", "operator": "eq",
            "value": 17 if dtype == "single_choice" else None}
    search_panel = []
    @ui.page("/")
    async def page():
        set_locale_context("en", "Asia/Dubai")
        await form.render()
        await form.assign(owner)
        with ui.column() as panel:
            search_panel.append(panel)
            render_type_condition(api, kind + "s", node, lambda: None, lambda: None, str)

    await user.open("/")
    await user.should_see("Value")
    with user:
        editor = next(e for e in form.fields.descendants() if getattr(e, "label", "") == dtype.title())
        criterion = next(e for e in search_panel[0].descendants() if getattr(e, "label", "") == "Value")
        if dtype in {"boolean", "single_choice"}:
            assert isinstance(editor, ui.select) and isinstance(criterion, ui.select)
            assert "new-value-mode" not in editor.props and "new-value-mode" not in criterion.props
        if bad is not None:
            editor.value = bad
            with pytest.raises(ValueError):
                form.payload()
            # Search terms can exceed a stored text field's limit.
            if dtype != "text":
                criterion.value = bad
                assert node["invalid_value"]
        if dtype == "single_choice":
            editor.value = criterion.value = None
        editor.value = criterion.value = valid
        assert form.payload()["field_values"] == {"1": wire}
        assert node["value"] == wire and not node["invalid_value"]
