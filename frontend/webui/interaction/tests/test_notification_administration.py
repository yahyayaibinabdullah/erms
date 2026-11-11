"""Real administration controls, bounded fake API, no database."""
from frontend.webui.entity_selectors import build_relationship_selector

import ast
import asyncio
import json
from pathlib import Path
from typing import Any, Callable
import pytest
from nicegui import ui, background_tasks
from nicegui.testing import User
from frontend.webui.app import (
    relationship_select,
    relationship_options,
    relationship_search_query,
)
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import set_active_messages, render_message_plain
from frontend.webui.notification_administration import notification_administration

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).parents[2]


class Api:
    def __init__(self):
        self.calls = []
        self.block = None
        self.stale = False
        self.info = {
            "producer_code": "preview.review",
            "feature_code": "preview",
            "event_type": "reviewed",
            "contract_version": 1,
            "required_for_business_commit": True,
            "active_configuration_version_id": None,
            "latest_version": 0,
            "sample_context": {"name": "Example"},
            "contract_definition": {
                "placeholders": {"name": {"type": "text", "max_length": 80}},
                "audience_modes": ["static"],
                "resource_configuration": None,
            },
            "registered_languages": [
                {"language_tag": "en", "direction": "ltr", "is_enabled": True},
                {"language_tag": "ar", "direction": "rtl", "is_enabled": True},
            ],
            "limits": {"TEST_MAX_RECIPIENTS": 10, "TEST_SENDS_PER_HOUR": 20},
        }
        self.saved = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.block:
            await self.block.wait()
        if path.endswith("/producers"):
            return {
                "items": [
                    {
                        "producer_code": "preview.review",
                        "name": self.info.get("name"),
                        "localized": self.info.get("localized"),
                        "operational_owner": None,
                        "active_version": None,
                    }
                ],
                "next_cursor": None,
            }
        if path.endswith("/producers/preview.review"):
            return self.info
        if "/recipients/" in path:
            return {"items": [{"id": 2, "name": "Recipient"}], "next_cursor": None}
        if path.endswith("/preview"):
            return {
                "variants": [
                    {
                        "language_tag": tag,
                        "direction": direction,
                        "subject": "Notice Example",
                        "body_rich_text": "<p>Example</p>",
                    }
                    for tag, direction in [("en", "ltr"), ("ar", "rtl")]
                ]
            }
        if path.endswith("/versions"):
            if method == "POST":
                if self.stale:
                    raise ApiError(409, "stale")
                self.saved.append(kwargs["json"])
                return {"id": "version-one"}
            return {"items": [], "next_cursor": None}
        return {"items": [], "next_cursor": None}


async def setup(user, language="en"):
    api = Api()
    api.info["name"] = "Review notification"
    api.info["localized"] = {"name": "إشعار المراجعة" if language == "ar" else "Review notification"}
    alive = {"value": True}
    scope = dict(
        ui=ui,
        api=api,
        Any=Any,
        Callable=Callable,
        asyncio=asyncio,
        json=json,
        background_tasks=background_tasks,
        ApiError=ApiError,
        error_message=str,
        render_message_plain=render_message_plain,
        relationship_options=relationship_options,
        relationship_search_query=relationship_search_query,
    )
    scope["bind_remote_relationship_select"] = build_relationship_selector(scope["api"], error_message=str)

    @ui.page("/notification-test")
    async def page():
        set_active_messages(
            {
                r["message_key"]: r["translated_text"]
                for r in json.loads(
                    (ROOT / "i18n/messages.ar.generated.json").read_text()
                )["items"]
            }
            if language == "ar"
            else {}
        )
        await notification_administration(
            api=api,
            container=ui.column(),
            relationship_select=relationship_select,
            bind_relationship=scope["bind_remote_relationship_select"],
            format_timestamp=str,
            active=lambda: alive["value"],
        )

    await user.open("/notification-test")
    return api, alive


@pytest.mark.parametrize(
    "language,open_label,new_label",
    [("en", "Open", "New configuration version"), ("ar", "فتح", "إصدار إعدادات جديد")],
)
async def test_registered_contract_and_directional_templates(
    user: User, language, open_label, new_label
):
    api, _ = await setup(user, language)
    await user.should_see(api.info["localized"]["name"])
    user.find(open_label, kind=ui.button).click()
    await user.should_see(new_label)
    await user.should_see("preview.review")
    user.find(new_label, kind=ui.button).click()
    await user.should_see("{name}")
    editors = list(user.find(ui.editor).elements)
    assert {editor._props["dir"] for editor in editors} == {"ltr", "rtl"}
    assert any(c._props.get("disable") for c in user.find(ui.checkbox).elements)
    assert all(call[2].get("params", {}).get("limit", 25) <= 25 for call in api.calls)


async def test_save_requires_preview_and_preserves_edits_on_conflict(user: User):
    api, _ = await setup(user)
    user.find("Open", kind=ui.button).click()
    await user.should_see("New configuration version")
    user.find("New configuration version", kind=ui.button).click()
    await user.should_see("Operational owner or team")
    next(
        c
        for c in user.find(ui.input).elements
        if c.label == "Operational owner or team"
    ).value = "Team"
    user.find("Save as a new version", kind=ui.button).click()
    await user.should_see("Review the previews below")
    assert not api.saved
    api.stale = True
    user.find("Save as a new version", kind=ui.button).click()
    await user.should_see("The configuration changed")
    assert (
        next(
            c
            for c in user.find(ui.input).elements
            if c.label == "Operational owner or team"
        ).value
        == "Team"
    )
    api.stale = False
    user.find("Save as a new version", kind=ui.button).click()
    await user.should_see("Configuration version saved.")
    assert len(api.saved) == 1


async def test_abandonment_and_repeated_navigation(user: User):
    api, alive = await setup(user)
    user.find("Open", kind=ui.button).click()
    await user.should_see("Back to producers")
    user.find("Back to producers", kind=ui.button).click()
    await asyncio.sleep(0.05)
    await user.should_see("Search producers")
    assert sum(path.endswith("/producers") for _, path, _ in api.calls) == 2
    api.block = asyncio.Event()
    user.find("Open", kind=ui.button).click()
    await asyncio.sleep(0.05)
    alive["value"] = False
    api.block.set()
    await asyncio.sleep(0.05)
    assert not any(
        b.text == "New configuration version" for b in user.find(ui.button).elements
    )


@pytest.mark.parametrize('language,mode,label', [
    ('en','current_responsible_people','Current owner and contributors'),
    ('ar','current_responsible_people','المالك والمساهمون الحاليون'),
    ('en','newly_assigned_person','Newly assigned owner or contributor'),
    ('ar','newly_assigned_person','المالك أو المساهم المُعيَّن حديثًا'),
])
async def test_recipient_rules_have_localized_labels_and_stable_values(user: User, language, mode, label):
    api, _ = await setup(user, language)
    api.info['contract_definition']['audience_modes'] = [mode]
    user.find('فتح' if language == 'ar' else 'Open', kind=ui.button).click()
    await user.should_see('إصدار إعدادات جديد' if language == 'ar' else 'New configuration version')
    user.find('إصدار إعدادات جديد' if language == 'ar' else 'New configuration version', kind=ui.button).click()
    await user.should_see(label)
    controls = list(user.find(ui.select).elements)
    selected = next(control for control in controls if control.value == mode)
    assert selected.options == {mode:label}
