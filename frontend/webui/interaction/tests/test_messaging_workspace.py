"""Real NiceGUI controls with bounded fake data; no database connections."""
from frontend.webui.entity_selectors import build_relationship_selector

import ast
import asyncio
import json
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest
from nicegui import ui, background_tasks
from nicegui.testing import User
from frontend.webui.relationship_select import relationship_select
from frontend.webui.entity_selectors import relationship_options
from frontend.webui.entity_selectors import relationship_search_query
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain, set_active_messages
from frontend.webui.messaging_workspace import messaging_workspace

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).parents[2]


class Api:
    def __init__(self):
        self.calls = []
        self.block = None
        self.sent = []

    async def full_text_search(self, payload):
        self.calls.append(("full_text_search", payload))
        return {"items": [{"type": "record", "record": {"id": 5, "title": "Visible record", "security_level_id": 1,
                           "record_number": "R-5"}}], "next_cursor": None}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.block:
            await self.block.wait()
        if path.endswith("/capabilities"):
            return {
                "limits": {
                    "MAX_SELECTORS_PER_SEND": 100,
                    "MAX_RECIPIENTS_PER_SEND": 2000,
                    "MAX_RESOURCE_LINKS": 50,
                },
                "security_levels": [{"id": 1, "name": "General", "level_number": 0}],
                "default_security_level_id": 1,
            }
        if path.endswith("/recipients/validate"):
            return {"expanded_recipient_count": 1}
        if "/recipients/" in path:
            return {
                "items": [
                    {"id": 2, "name": "Recipient", "eligible": True, "email": "recipient@example.test"},
                    {
                        "id": 3,
                        "name": "Restricted recipient",
                        "eligible": False,
                        "reason_code": "message_recipient_clearance_required",
                    },
                ],
                "has_more": False,
            }
        if "/resources/" in path:
            return {
                "items": [{"id": 5, "title": "Visible record", "eligible": True}],
                "has_more": False,
            }
        if path.endswith("/send"):
            self.sent.append(kwargs["json"])
            return {"envelope_id": "sent"}
        return {"items": [], "has_more": False, "next_cursor": None}

    async def administration_reference_page(self, *args, **kwargs):
        self.calls.append(("reference", args[0], kwargs))
        return {"items": [{"id": 1, "name": "General", "level_number": 0}]}

    async def get(self, *args):
        return {"id": 1, "name": "General", "level_number": 0}


async def setup(user, language="en", exchange=True, browse=None, mailbox="inbox", api=None):
    api = api or Api()
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

    @ui.page("/messaging-test")
    async def page():
        if language == "ar":
            set_active_messages(
                {
                    r["message_key"]: r["translated_text"]
                    for r in json.loads(
                        (ROOT / "i18n/messages.ar.generated.json").read_text()
                    )["items"]
                }
            )
        else:
            set_active_messages({})
        await messaging_workspace(
            api=api,
            container=ui.column(),
            mailbox=mailbox,
            can_exchange=exchange,
            relationship_select=relationship_select,
            bind_relationship=scope["bind_remote_relationship_select"],
            open_resource=AsyncMock(),
            format_timestamp=str,
            active=lambda: alive["value"],
            browse_recipients=browse,
        )

    await user.open("/messaging-test")
    return api, alive


async def test_compose_uses_shared_bounded_selector_and_sends_new_content(user: User):
    api, _ = await setup(user)
    await user.should_see("No messages to show")
    user.find("Compose").click()
    await user.should_see("Subject")
    control = next(c for c in user.find(ui.select).elements if c.label == "To")
    control.options = {6: "User · Recipient"}
    control.update()
    control.value = [6]
    await user.should_see("Current recipient count: 1")
    subject = next(c for c in user.find(ui.input).elements if c.label == "Subject")
    subject.value = "A new subject"
    next(iter(user.find(ui.editor).elements)).value = "<p>New content only</p>"
    user.find(marker="messaging-send", kind=ui.button).click()
    await user.should_see("Message sent")
    assert api.sent[0]["subject"] == "A new subject"
    assert all(call[2].get("params", {}).get("limit", 25) <= 25 for call in api.calls)


@pytest.mark.parametrize(
    "language,empty", [("en", "No messages to show"), ("ar", "لا توجد رسائل لعرضها")]
)
async def test_system_only_inbox_hides_compose_and_reopens_fresh(
    user: User, language, empty
):
    api, _ = await setup(user, language, exchange=False)
    await user.should_see(empty)
    assert not any(
        b.text in ("Compose", "إنشاء رسالة") for b in user.find(ui.button).elements
    )
    label = "Refresh" if language == "en" else "تحديث"
    user.find(label).click()
    await asyncio.sleep(0.05)
    await user.should_see(empty)
    assert sum(path.endswith("/inbox") for _, path, _ in api.calls) == 2


async def test_abandoned_refresh_cannot_render_into_another_page(user: User):
    api, alive = await setup(user)
    api.block = asyncio.Event()
    user.find("Refresh").click()
    await asyncio.sleep(0.05)
    alive["value"] = False
    api.block.set()
    await asyncio.sleep(0.05)
    await user.should_see("Loading messages…")


async def test_structured_resource_editor_roundtrip(user: User):
    api, _ = await setup(user)
    user.find("Compose").click()
    await user.should_see("Subject")
    recipient = next(c for c in user.find(ui.select).elements if c.label == "To")
    recipient.options = {6: "User · Recipient"}
    recipient.update()
    recipient.value = [6]
    await user.should_see("Current recipient count: 1")
    user.find("Add resources", kind=ui.button).click()
    await user.should_see("Search text")
    next(c for c in user.find(ui.input).elements if c.label == "Search text").value = "Visible"
    user.find(kind=ui.button, content="Search").click()
    await user.should_see("Visible record")
    check = next(c for c in user.find(ui.checkbox).elements if c.props.get("aria-label") == "Visible record")
    check.value = True
    user.find("Add selected", kind=ui.button).click()
    await asyncio.sleep(0.1)
    subject = next(c for c in user.find(ui.input).elements if c.label == "Subject")
    assert next(iter(user.find(ui.editor).elements)).value == ""
    subject.value = "Linked resource"
    await asyncio.sleep(0.05)
    user.find(marker="messaging-send", kind=ui.button).click()
    await user.should_see("Message sent")
    link = api.sent[0]["resource_links"][0]
    assert link["resource_kind"] == "record" and link["target_id"] == 5
    assert link["link_token"] in api.sent[0]["body_rich_text"]


@pytest.mark.parametrize("recipient_type", ["to", "cc"])
@pytest.mark.parametrize("with_browser", [False, True])
async def test_everyone_allows_resource_attachment(user: User, recipient_type, with_browser):
    api, _ = await setup(user, browse=AsyncMock() if with_browser else None)
    user.find("Compose").click()
    await user.should_see(marker="message-recipients-to")
    if recipient_type == "cc":
        to = next(iter(user.find(marker="message-recipients-to").elements))
        to.options = {6: "User · Recipient"}
        to.value = [6]
        await user.should_see("Current recipient count: 1")
    user.find(marker="message-everyone-" + recipient_type).click()
    await asyncio.sleep(.1)
    assert next(iter(user.find("Add resources", kind=ui.button).elements)).enabled
    user.find("Add resources", kind=ui.button).click()
    await user.should_see("Search text")
    next(c for c in user.find(ui.input).elements if c.label == "Search text").value = "Visible"
    await asyncio.sleep(.1)
    next(c for c in user.find(ui.button).elements if c.text == "Search").mark("everyone-resource-search")
    user.find(marker="everyone-resource-search").click()
    await user.should_see("Visible record")
    next(c for c in user.find(ui.checkbox).elements if c.props.get("aria-label") == "Visible record").value = True
    user.find("Add selected", kind=ui.button).click()
    await asyncio.sleep(.1)
    next(c for c in user.find(ui.input).elements if c.label == "Subject").value = "Circular for everyone"
    await asyncio.sleep(.05)
    user.find(marker="messaging-send", kind=ui.button).click()
    await user.should_see("Message sent")
    assert {"selector_kind": "everyone", "target_id": None, "recipient_type": recipient_type} in api.sent[0]["selectors"]
    assert api.sent[0]["resource_links"][0]["target_id"] == 5


async def test_shared_remote_selector_retains_selection_and_disables_explained_results(
    user: User,
):
    api = Api()
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
    controls = {}

    @ui.page("/shared-messaging-selector")
    async def page():
        control = relationship_select("Recipient", {9: "Retained recipient"}, value=9, remote=True)

        async def selected(identity):
            return {"id": identity, "name": "Retained recipient", "eligible": True}

        load = scope["bind_remote_relationship_select"](
            control,
            "users",
            ("name",),
            ("name",),
            page_loader=lambda q: api.request(
                "GET", "/recipients/user", params={"q": q, "limit": 25}
            ),
            selected_loader=selected,
            option_reason=lambda row: None if row.get("eligible") else "No clearance",
        )
        controls.update(control=control, load=load)
        await load("Recipient")

    await user.open("/shared-messaging-selector")
    control = controls["control"]
    assert control.value == 9 and 9 in control.options
    assert "No clearance" not in control.options[3]
    assert control.option_details[3]["reason"] == "No clearance"
    assert control.option_details[2]["email"] == "recipient@example.test"
    control.update()
    rendered = {key: row for key, row in zip(control.options, control._props['options'])}
    assert rendered[3]['reason'] == 'No clearance'
    assert rendered[2]['email'] == 'recipient@example.test'
    assert list(control.options).index(3) in json.loads(
        control._props[":option-disable"].split(" => ", 1)[1].split(".includes", 1)[0]
    )
    assert api.calls[-1][2]["params"]["limit"] == 25


async def test_compose_security_search_respects_current_clearance(user: User):
    api, _ = await setup(user)
    user.find("Compose").click()
    await user.should_see("Subject")
    level = next(
        c for c in user.find(ui.select).elements if c.label == "Security level"
    )

    async def levels(*args, **kwargs):
        api.calls.append(("reference", args[0], kwargs))
        return {
            "items": [
                {"id": 1, "name": "General", "level_number": 0},
                {"id": 99, "name": "Above clearance", "level_number": 99},
            ]
        }

    api.administration_reference_page = levels
    # Invoke the genuine shared remote-search event registered on the control.
    listener = next(
        listener
        for listener in level._event_listeners.values()
        if listener.type == "inputValue"
    )
    from nicegui import events

    events.handle_event(
        listener.handler,
        events.GenericEventArguments(sender=level, client=level.client, args="Gen"),
    )
    await asyncio.sleep(0.4)
    assert 1 in level.options and 99 not in level.options
    assert any(
        method == "reference" and kwargs.get("filters") == {"assignable": True}
        for method, _, kwargs in api.calls
    )

    recipient = next(c for c in user.find(ui.select).elements if c.label == "To")
    listener = next(x for x in recipient._event_listeners.values() if x.type == "inputValue")
    events.handle_event(listener.handler, events.GenericEventArguments(sender=recipient, client=recipient.client, args="Re"))
    await asyncio.sleep(0.4)
    assert recipient.options[7] == "Role · Recipient"
    assert all(call[2]["params"]["security_level_id"] == 1 for call in api.calls if "/recipients/" in call[1] and "params" in call[2])


async def emit_query(control, query):
    from nicegui import events
    listener = next(x for x in control._event_listeners.values() if x.type == 'inputValue')
    events.handle_event(listener.handler, events.GenericEventArguments(sender=control, client=control.client, args=query))
    await asyncio.sleep(0.3)


async def test_two_character_mixed_search_keeps_to_and_cc_separate(user: User):
    api, _ = await setup(user)
    user.find('Compose').click()
    await user.should_see('Subject')
    controls = {c.label:c for c in user.find(ui.select).elements}
    assert 'To' in controls and 'Cc' in controls and 'Recipient kind' not in controls
    to, cc = controls['To'], controls['Cc']
    await emit_query(to, 'R')
    assert not any('/recipients/' in call[1] for call in api.calls)
    await emit_query(to, 'Re')
    assert set(to.options) == {6,7,8,9,10,11}
    assert 'User' in to.options[6] and 'Role' in to.options[7] and 'Organizational unit' in to.options[8]
    to.value = [6]
    await user.should_see('Current recipient count: 1')
    await emit_query(cc, 'Re')
    cc.value = [7,8]
    await asyncio.sleep(0.1)
    await emit_query(to, '')
    assert to.value == [6] and to.options[6] == 'User · Recipient'
    assert cc.value == [7,8]
    cc.value = [8]
    await asyncio.sleep(0.1)
    next(c for c in user.find(ui.input).elements if c.label=='Subject').value='Mixed recipients'
    # A positional text target also matches the Sender filter; NiceGUI ignores
    # kind in that overload and iterates a set, making the old click unstable.
    send = user.find(marker='messaging-send', kind=ui.button)
    assert len(send.elements) == 1
    assert next(iter(send.elements)).enabled
    send.click()
    await user.should_see('Message sent')
    assert api.sent[0]['selectors'] == [
        {'recipient_type':'to','selector_kind':'user','target_id':2},
        {'recipient_type':'cc','selector_kind':'org_unit','target_id':2},
    ]


async def test_shared_browser_can_add_to_either_address_field(user: User):
    async def browse(**kwargs):
        assert kwargs['selection_mode'] == 'all'
        assert await kwargs['on_selection']({'type':'role','id':2})
    api, _ = await setup(user, browse=browse)
    user.find('Compose').click()
    await user.should_see('Subject')
    buttons = sorted(user.find('Browse organization structure',kind=ui.button).elements, key=lambda c:c.id)[-2:]
    assert len(buttons)==2
    for i,button in enumerate(sorted(buttons,key=lambda x:x.id)):
        button.mark('browse'+str(i))
        user.find(marker='browse'+str(i)).click()
        await asyncio.sleep(0.1)
    controls = {c.label:c for c in user.find(ui.select).elements}
    assert controls['To'].value == controls['Cc'].value == [7]


async def test_abandoned_recipient_search_does_not_update_controls(user: User):
    api, alive = await setup(user)
    user.find('Compose').click()
    await user.should_see('Subject')
    control = next(c for c in user.find(ui.select).elements if c.label == 'To')
    api.block = asyncio.Event()
    await emit_query(control, 'Re')
    alive['value'] = False
    api.block.set()
    await asyncio.sleep(.1)
    assert control.options == {}
    assert len([call for call in api.calls if '/recipients/' in call[1]]) == 3


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_due_date_guidance_follows_action_field_visibility(user: User, language):
    await setup(user, language=language)
    user.find('Compose' if language=='en' else 'إنشاء رسالة').click()
    await user.should_see('Subject' if language=='en' else 'الموضوع')
    await user.should_see('Action required' if language=='en' else 'يتطلب إجراءً')
    action = next(c for c in user.find(ui.checkbox).elements if c.text == ('Action required' if language=='en' else 'يتطلب إجراءً'))
    due = next(c for c in action.client.elements.values() if isinstance(c,ui.input) and c.props.get('type')=='date' and c.label == ('Action due date' if language=='en' else 'تاريخ استحقاق الإجراء'))
    help_text = 'The due date uses your working timezone and is informational.' if language=='en' else 'يُستخدم نطاقك الزمني لتاريخ الاستحقاق، وهو تاريخ إرشادي.'
    guidance = next(c for c in action.client.elements.values() if isinstance(c,ui.label) and c.text == help_text)
    assert not due.visible and not guidance.visible
    action.value=True
    await asyncio.sleep(.05)
    assert due.visible and guidance.visible
    action.value=False
    await asyncio.sleep(.05)
    assert not due.visible and not guidance.visible


async def test_add_resource_explains_failed_eligibility_recheck(user: User):
    api, _ = await setup(user)
    user.find('Compose').click()
    await user.should_see('Subject')
    user.find("Add resources", kind=ui.button).click()
    await user.should_see("Search text")
    next(c for c in user.find(ui.input).elements if c.label == "Search text").value = "Visible"
    user.find(kind=ui.button, content="Search").click()
    await user.should_see("Visible record")
    check = next(c for c in user.find(ui.checkbox).elements if c.props.get("aria-label") == "Visible record")
    check.value = True
    original = api.request

    async def unavailable(method, path, **kwargs):
        if '/resources/' in path:
            return {'items': [{'id': 5, 'title': 'Visible record', 'eligible': False,
                               'reason_code': 'message_resource_level_too_high'}]}
        return await original(method, path, **kwargs)

    api.request = unavailable
    user.find("Add selected", kind=ui.button).click()
    await user.should_see(render_message_plain('messaging.reason.message_resource_level_too_high'))
    editor = next(iter(user.find(ui.editor).elements))
    assert 'data-wathiq-link' not in (editor.value or '')


async def test_resource_batch_recheck_is_all_or_nothing(user: User):
    api, _ = await setup(user)
    async def search(payload):
        return {'items': [{'type': 'record', 'record': {'id': i, 'title': 'Candidate '+str(i), 'security_level_id': 1}}
                          for i in (5, 6)], 'next_cursor': None}
    api.full_text_search = search
    user.find('Compose').click()
    await user.should_see('Subject')
    user.find('Add resources', kind=ui.button).click()
    await user.should_see('Search text')
    next(c for c in user.find(ui.input).elements if c.label == 'Search text').value = 'Candidate'
    user.find(kind=ui.button, content='Search').click()
    await user.should_see('Candidate 5')
    for check in user.find(ui.checkbox).elements:
        if check.props.get('aria-label') in ('Candidate 5', 'Candidate 6'):
            check.value = True
    original = api.request
    async def recheck(method, path, **kwargs):
        if '/resources/' in path:
            identity = kwargs['params']['target_id']
            return {'items': [{'id': identity, 'title': 'Candidate '+str(identity),
                              'eligible': identity == 5,
                              'reason_code': None if identity == 5 else 'message_resource_unavailable'}]}
        return await original(method, path, **kwargs)
    api.request = recheck
    user.find('Add selected', kind=ui.button).click()
    await user.should_see(render_message_plain('messaging.reason.message_resource_unavailable'))
    assert 'data-wathiq-link' not in next(iter(user.find(ui.editor).elements)).value
    await user.should_see('Selected resources: 2')


async def test_resource_markers_do_not_become_authored_body():
    from frontend.webui.messaging_workspace import body_without_resources, body_with_resource_markers
    legacy = '<p>Authored text</p><p><span data-wathiq-link="abc">Old record title</span></p><p>After</p>'
    assert body_without_resources(legacy) == '<p>Authored text</p><p>After</p>'
    stored = body_with_resource_markers(legacy, [{'link_token': 'new'}])
    assert 'Old record title' not in stored
    assert stored == '<p>Authored text</p><p>After</p><span data-wathiq-link="new"></span>'


@pytest.mark.parametrize('mailbox', ['inbox', 'outbox'])
async def test_mailbox_recipient_filter_search_browse_and_clear(user: User, mailbox):
    async def browse(**kwargs):
        assert kwargs['selection_mode'] == 'all'
        assert await kwargs['on_selection']({'type': 'org_unit', 'id': 2})
    api, _ = await setup(user, mailbox=mailbox, browse=browse)
    controls = {c.label: c for c in user.find(ui.select).elements}
    assert 'Recipient kind' not in controls
    recipient = controls['Recipient']
    await emit_query(recipient, 'R')
    assert not any('/recipients/' in path for _, path, _ in api.calls)
    await emit_query(recipient, 'Re')
    assert set(recipient.options) == {6, 7, 8, 9, 10, 11}
    recipient.value = 7
    user.find('Search subject', kind=ui.button).click()
    await asyncio.sleep(.1)
    params = [kwargs['params'] for method,path,kwargs in api.calls if path.endswith('/'+mailbox)][-1]
    assert params['recipient_kind'] == 'role' and params['recipient_id'] == 2
    user.find(marker='mailbox-browse-recipient',kind=ui.button).click()
    await asyncio.sleep(.1)
    assert recipient.value == 8
    recipient.value = None
    user.find('Search subject',kind=ui.button).click()
    await asyncio.sleep(.1)
    params = [kwargs['params'] for method,path,kwargs in api.calls if path.endswith('/'+mailbox)][-1]
    assert 'recipient_id' not in params and 'recipient_kind' not in params


@pytest.mark.parametrize('recipient_type', ['to', 'cc'])
@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_reply_prefills_sender_and_cc_has_no_completion_prompt(user: User, recipient_type, language):
    api = Api()
    original = api.request
    message = dict(id='delivery', envelope_id='envelope', subject='Original subject', availability='available',
        sender_name='Original sender', sender_user_id=2, sender_kind='user', sent_at='2026-10-03',
        priority='high', security_level_id=1, security_level_name='General', selectors=[],
        body_rich_text='<p>Original body</p>', resource_links=[], is_test=False, message_kind='user_message',
        expires_at='2029-10-03T00:00:00Z', action_required=True, action_due_date=None, action_due_timezone=None,
        recipient_type=recipient_type, action_status='outstanding' if recipient_type=='to' else None,
        effective_action=dict(action_required=True, due_date=None, due_timezone=None))
    async def request(method, path, **kwargs):
        if path.endswith('/inbox'): return dict(items=[message], has_more=False)
        if path.endswith('/inbox/delivery/read'): return message
        return await original(method,path,**kwargs)
    api.request = request
    await setup(user, api=api, language=language)
    if language == 'ar':
        set_active_messages({r['message_key']: r['translated_text'] for r in
            json.loads((ROOT / 'i18n/messages.ar.generated.json').read_text())['items']})
    user.find(marker='message-row-delivery').click()
    await user.should_see('Original subject')
    assert not any(c.props.get('label') == ('Open' if language == 'en' else 'فتح') for c in user.find(ui.button).elements)
    await user.should_see(kind=ui.button, content='Reply' if language=='en' else 'رد')
    reply_button = next(c for c in user.find(ui.button).elements if c.props.get('label') == ('Reply' if language=='en' else 'رد'))
    reply_button.mark('reply-action')
    user.find(marker='reply-action').click()
    await user.should_see('Current recipient count: 1' if language=='en' else 'عدد المستلمين الحالي: 1')
    to = next(c for c in user.find(ui.select).elements if c.label==('To' if language=='en' else 'إلى'))
    assert to.value == [6]
    subject = next(c for c in user.find(ui.input).elements if c.label==('Subject' if language=='en' else 'الموضوع'))
    assert subject.value == 'Re: Original subject'
    priority = max((c for c in user.find(ui.select).elements if c.label==('Priority' if language=='en' else 'الأولوية')), key=lambda c:c.id)
    assert priority.value == 'normal'
    security = next(c for c in user.find(ui.select).elements if c.label==('Security level' if language=='en' else 'درجة السرية'))
    assert security.value == 1
    assert next(iter(user.find(ui.editor).elements)).value == ''
    prompts = [c for c in user.find(ui.checkbox).elements if c.text==('Is the action done?' if language=='en' else 'هل اكتمل الإجراء؟')]
    if recipient_type == 'cc':
        assert prompts == []
    else:
        assert len(prompts) == 1 and prompts[0].value is False
        await user.should_see(render_message_plain('messaging.help.completion'))
        user.find(marker="message-everyone-to").click()
        await asyncio.sleep(.1)
        prompts[0].value = True
        await asyncio.sleep(.1)
        assert to.value == [-1]
    subject.value = 'Edited reply subject'
    user.find('Save draft' if language=='en' else 'حفظ المسودة',kind=ui.button).click()
    await asyncio.sleep(.1)
    saved = next(kwargs['json'] for method,path,kwargs in reversed(api.calls) if method=='POST' and path.endswith('/drafts'))
    assert saved['subject'] == 'Edited reply subject'


async def test_reopening_reply_draft_preserves_edited_subject(user: User):
    api = Api()
    original = api.request
    draft = dict(id='draft', subject='Previously edited subject', body_rich_text='<p>Saved body</p>',
        security_level_id=1, priority='high', selectors=[], resource_links=[], version=1,
        relationship_kind='reply', related_delivery_id='original', related_envelope_id=None)
    async def request(method, path, **kwargs):
        if path.endswith('/drafts'): return dict(items=[draft], has_more=False)
        if path.endswith('/drafts/draft'): return draft
        if path.endswith('/inbox/original'): return dict(subject='Original subject', security_level_id=1)
        return await original(method,path,**kwargs)
    api.request = request
    await setup(user, api=api, mailbox='drafts')
    user.find(marker='message-row-draft').click()
    await user.should_see('Subject')
    subject = next(c for c in user.find(ui.input).elements if c.label=='Subject')
    assert next(iter(user.find(marker='message-row-draft').elements)).visible
    assert not any(c.props.get('label') == 'Open' for c in user.find(ui.button).elements)
    assert not any(isinstance(c, ui.dialog) for c in subject.client.elements.values())
    assert subject.value == 'Previously edited subject'
    assert next(iter(user.find(ui.editor).elements)).value == '<p>Saved body</p>'

@pytest.mark.parametrize('mailbox', ['inbox', 'outbox'])
@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_mailbox_row_keeps_page_and_discards_stale_detail(user: User, mailbox, language):
    api = Api()
    original = api.request
    list_cursors = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    async def request(method, path, **kwargs):
        if path.endswith('/' + mailbox):
            list_cursors.append(kwargs.get('params', {}).get('cursor'))
            return dict(items=[dict(id='first', availability='restricted'),
                               dict(id='second', availability='restricted')], has_more=True, next_cursor='page-two')
        if '/first' in path:
            first_started.set()
            await release_first.wait()
            return dict(availability='available', subject='Stale response must never render')
        if '/second' in path:
            return dict(availability='restricted')
        return await original(method, path, **kwargs)
    api.request = request
    await setup(user, api=api, language=language, mailbox=mailbox)
    user.find('Next' if language == 'en' else 'التالي', kind=ui.button).click()
    await asyncio.sleep(.05)
    assert list_cursors == [None, 'page-two']
    user.find(marker='message-row-first').click()
    await first_started.wait()
    user.find(marker='message-row-second').click()
    await asyncio.sleep(.05)
    release_first.set()
    await asyncio.sleep(.05)
    assert 'Stale response must never render' not in [getattr(c, 'text', '') for c in user.find(ui.label).elements]
    assert next(iter(user.find(marker='message-row-second').elements)).visible
    assert next(iter(user.find('Previous' if language == 'en' else 'السابق', kind=ui.button).elements)).enabled

@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_inbox_date_filters_and_browse_below_recipient(user: User, language):
    api, _ = await setup(user, language=language, browse=AsyncMock())
    labels = {r['message_key']: r['translated_text'] for r in json.loads((ROOT / 'i18n/messages.ar.generated.json').read_text())['items']}
    english_labels = {r['message_key']: r['default_text'] for r in json.loads((ROOT / 'i18n/messages.en.json').read_text())}
    def label(key, english):
        return (labels if language == 'ar' else english_labels)['messaging.' + key]
    recipient = next(c for c in user.find(ui.select).elements if c.label == label('field.recipient', 'Recipient'))
    browse = next(iter(user.find(marker='mailbox-browse-recipient').elements))
    assert recipient.parent_slot.parent is browse.parent_slot.parent
    assert isinstance(recipient.parent_slot.parent, ui.column)
    for key, value in [('sent_from', '2026-10-01'), ('sent_before', '2026-10-05')]:
        next(c for c in user.find(ui.input).elements if c.label == label('field.' + key, 'Sent from' if key == 'sent_from' else 'Sent before')).value = value
    user.find(label('field.search', 'Search subject'), kind=ui.button).click()
    await asyncio.sleep(.1)
    params = next(kwargs['params'] for method, path, kwargs in reversed(api.calls) if path.endswith('/inbox'))
    assert params['sent_from'] == '2026-10-01T00:00:00Z'
    assert params['sent_before'] == '2026-10-05T00:00:00Z'


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('mailbox', ['inbox', 'drafts'])
async def test_mailbox_sender_and_draft_recipient_filters(user: User, language, mailbox):
    api, _ = await setup(user, language=language, mailbox=mailbox, browse=AsyncMock())
    marker = 'mailbox-sender' if mailbox == 'inbox' else 'mailbox-recipient'
    control = next(iter(user.find(marker=marker).elements))
    control.options = {2: 'Sender'} if mailbox == 'inbox' else {7: 'Role · Auditor'}
    control.value = 2 if mailbox == 'inbox' else 7
    await asyncio.sleep(.05)
    user.find('Search subject' if language == 'en' else 'البحث في الموضوع', kind=ui.button).click()
    await asyncio.sleep(.1)
    params = next(kwargs['params'] for method, path, kwargs in reversed(api.calls) if path.endswith('/' + mailbox))
    if mailbox == 'inbox':
        assert params['sender_user_id'] == 2
    else:
        assert params['recipient_kind'] == 'role' and params['recipient_id'] == 2
    control.value = None
    user.find('Search subject' if language == 'en' else 'البحث في الموضوع', kind=ui.button).click()
    await asyncio.sleep(.1)
    params = next(kwargs['params'] for method, path, kwargs in reversed(api.calls) if path.endswith('/' + mailbox))
    assert 'sender_user_id' not in params and 'recipient_id' not in params


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_sent_draft_disappears_before_mailbox_refresh_finishes(user: User, language):
    api = Api()
    original = api.request
    sent, refreshing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    draft = dict(id='draft', subject='Ready draft', body_rich_text='<p>Body</p>',
                 security_level_id=1, priority='normal', version=1,
                 selectors=[dict(selector_kind='everyone', target_id=None, recipient_type='to')],
                 resource_links=[], relationship_kind=None, related_delivery_id=None, related_envelope_id=None)
    async def request(method, path, **kwargs):
        if path.endswith('/drafts'):
            if sent.is_set():
                refreshing.set()
                await release.wait()
                return dict(items=[], has_more=False)
            return dict(items=[draft], has_more=False)
        if path.endswith('/drafts/draft/send'):
            sent.set()
            return dict(envelope_id='sent')
        if path.endswith('/drafts/draft'):
            return {**draft, 'version': 2 if method == 'PUT' else 1}
        return await original(method, path, **kwargs)
    api.request = request
    await setup(user, api=api, mailbox='drafts', language=language)
    user.find(marker='message-row-draft').click()
    await user.should_see(kind=ui.input, content='Subject' if language == 'en' else 'الموضوع')
    await asyncio.sleep(.1)
    user.find('Send' if language == 'en' else 'إرسال', kind=ui.button).click()
    try:
        await asyncio.wait_for(refreshing.wait(), 2)
        await user.should_not_see(marker='message-row-draft')
    finally:
        release.set()
    await user.should_see('No messages to show' if language == 'en' else 'لا توجد رسائل لعرضها')


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_draft_panel_switch_save_and_cancel_keep_listing(user: User, language):
    api = Api()
    original = api.request
    started, release = asyncio.Event(), asyncio.Event()
    cursors, saved = [], []
    async def request(method, path, **kwargs):
        if path.endswith('/drafts'):
            cursors.append(kwargs['params'].get('cursor'))
            return dict(items=[dict(id='first', subject='First draft'), dict(id='second', subject='Second draft')],
                        has_more=True, next_cursor='page-two')
        if path.endswith('/drafts/first'):
            started.set()
            await release.wait()
        if '/drafts/' in path:
            if method == 'PUT':
                saved.append(kwargs['json'])
                return dict(id='second', version=2)
            return dict(id=path.rsplit('/',1)[1], subject='First draft' if path.endswith('/first') else 'Second draft',
                        body_rich_text='<p>Draft body</p>', security_level_id=1, priority='normal',
                        selectors=[], resource_links=[], version=1, relationship_kind=None,
                        related_delivery_id=None, related_envelope_id=None)
        return await original(method,path,**kwargs)
    api.request = request
    await setup(user, api=api, mailbox='drafts', language=language)
    user.find('Next' if language=='en' else 'التالي', kind=ui.button).click()
    await asyncio.sleep(.05)
    user.find(marker='message-row-first').click()
    await started.wait()
    user.find(marker='message-row-second').click()
    await user.should_see(kind=ui.input, content='Subject' if language=='en' else 'الموضوع')
    release.set()
    await asyncio.sleep(.05)
    subject = next(c for c in user.find(ui.input).elements if c.label==('Subject' if language=='en' else 'الموضوع'))
    assert subject.value == 'Second draft'
    subject.value = 'Updated draft'
    user.find('Save draft' if language=='en' else 'حفظ المسودة', kind=ui.button).click()
    await asyncio.sleep(.1)
    assert saved[0]['subject'] == 'Updated draft'
    assert cursors == [None, 'page-two', 'page-two']
    assert subject.visible
    user.find('Cancel' if language=='en' else 'إلغاء', kind=ui.button).click()
    assert next(iter(user.find(marker='message-row-second').elements)).visible

@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_earlier_dialog_preserves_latest_and_navigates_back(user: User, language):
    api = Api()
    original = api.request
    linked_requests = []
    def message(identity, parent=None):
        return dict(id=identity, envelope_id=identity, subject=identity + ' subject', availability='available',
            sender_name='Sender', sender_kind='user', sender_user_id=2, sent_at='2026-10-04', priority='normal',
            security_level_id=1, security_level_name='General', selectors=[], body_rich_text='<p>'+identity+' body</p>',
            resource_links=[], is_test=False, message_kind='user_message', expires_at='2029-10-04T00:00:00Z',
            action_required=False, action_due_date=None, action_due_timezone=None, recipient_type='to',
            effective_action=dict(action_required=False, due_date=None), linked_envelope_id=parent)
    async def request(method, path, **kwargs):
        if path.endswith('/inbox'): return dict(items=[message('latest','earlier')], has_more=False)
        if path.endswith('/inbox/latest/read'): return message('latest','earlier')
        if '/linked/' in path:
            linked_requests.append(path)
            identity = path.rsplit('/',1)[1]
            return message(identity, 'oldest' if identity=='earlier' else None)
        return await original(method,path,**kwargs)
    api.request = request
    await setup(user,api=api,language=language)
    user.find(marker='message-row-latest').click()
    await user.should_see('latest body')
    # Use the pane's link, then the dialog's link, without touching the listing.
    user.find(marker='earlier-link-latest').click()
    await user.should_see('earlier body')
    assert next(iter(user.find(marker='message-row-latest').elements)).visible
    user.find(marker='earlier-link-earlier').click()
    await user.should_see('oldest body')
    user.find(marker='linked-message-back').click()
    await user.should_see('earlier body')
    assert all('/linked/latest/' in path for path in linked_requests)
    user.find(marker='linked-message-close').click()
    await user.should_see('latest body')
    assert not any(c.value for c in next(iter(user.find(marker='message-row-latest').elements)).client.elements.values() if isinstance(c,ui.dialog))


@pytest.mark.parametrize("language", ["en", "ar"])
async def test_everyone_selection_exclusivity_and_removal(user: User, language):
    api, _ = await setup(user, language=language)
    user.find("Compose" if language == "en" else "إنشاء رسالة").click()
    await user.should_see(marker="message-recipients-to")
    to = next(iter(user.find(marker="message-recipients-to").elements))
    cc = next(iter(user.find(marker="message-recipients-cc").elements))
    label = "Everyone" if language == "en" else "الجميع"
    buttons = [next(iter(user.find(marker="message-everyone-" + kind).elements)) for kind in ("to", "cc")]
    to.options={6:"Recipient"}; to.value=[6]
    await user.should_see("Current recipient count: 1" if language == "en" else "عدد المستلمين الحالي: 1")
    user.find(marker="message-everyone-cc").click()
    await asyncio.sleep(.1)
    assert cc.value == [-1] and to.value == [6]
    assert not cc.props["use-input"] and to.props["use-input"]
    assert not buttons[1].enabled
    user.find(marker="message-everyone-to").click()
    await asyncio.sleep(.1)
    assert to.value == [-1] and cc.value == []
    assert not to.props["use-input"] and not cc.props["use-input"]
    assert not buttons[0].enabled and not buttons[1].enabled
    to.value=[]
    await asyncio.sleep(.1)
    assert buttons[0].enabled and buttons[1].enabled
    assert not any('/recipients/everyone' in c[1] for c in api.calls if len(c)>1)


async def test_outbox_pages_keep_the_submitted_subject_until_search(user: User):
    api = Api()
    original = api.request
    queries = []

    async def request(method, path, **kwargs):
        if path == '/api/v1/messages/outbox':
            queries.append(kwargs['params'])
            return {'items': [], 'has_more': True, 'next_cursor': 'page-two'}
        return await original(method, path, **kwargs)

    api.request = request
    await setup(user, mailbox='outbox', api=api)
    label = 'Search subject'
    field = next(control for control in user.find(ui.input).elements if control.label == label)
    field.value = 'Submitted'
    user.find(kind=ui.button, content=label).click()
    await asyncio.sleep(.05)
    assert queries[-1] == {'limit': 25, 'q': 'Submitted'}
    field.value = 'Draft'
    user.find('Next', kind=ui.button).click()
    await asyncio.sleep(.05)
    assert queries[-1] == {'limit': 25, 'cursor': 'page-two', 'q': 'Submitted'}
    user.find('Previous', kind=ui.button).click()
    await asyncio.sleep(.05)
    assert queries[-1] == {'limit': 25, 'q': 'Submitted'}
    assert field.value == 'Draft'
    user.find(kind=ui.button, content=label).click()
    await asyncio.sleep(.05)
    assert queries[-1] == {'limit': 25, 'q': 'Draft'}
