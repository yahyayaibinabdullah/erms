"""Exercise the real governed-move dialog and bounded destination selector."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from frontend.webui.aggregation_actions import build_aggregation_actions
from frontend.webui.entity_selectors import build_relationship_selector
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import set_active_messages

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
AR = {x['message_key']: x['translated_text'] for x in json.loads(
    (Path(__file__).parents[2] / 'i18n/messages.ar.generated.json').read_text())['items']}


async def setup_move(user, resource, language):
    api = SimpleNamespace(
        relationship_page=AsyncMock(return_value={'items': []}),
        get=AsyncMock(),
        acl_move_preview=AsyncMock(return_value={
            'added_count': 1, 'removed_count': 2, 'ownership_changes': False,
            'affected_subtree': {'affected_aggregation_count': 2, 'affected_record_count': 3}}),
        move_with_acl=AsyncMock(return_value={'id': 7, 'version': 5}),
    )
    saved = AsyncMock()
    state = {}
    bind = build_relationship_selector(api, error_message=str)

    def bind_destination(*args, **kwargs):
        state['load'] = bind(*args, **kwargs)

    @ui.page('/governed-move-contract')
    async def page():
        set_active_messages(AR if language == 'ar' else {})
        _, move, _ = build_aggregation_actions(
            api=api, bind_remote_relationship_select=bind_destination, error_message=str)
        await move(resource, {'id': 7, 'version': 4, 'medium': 'physical'}, saved)

    await user.open('/governed-move-contract')
    state['dialog'] = next(d for d in user.find(ui.dialog).elements if d.value)
    state['destination'] = next(iter(user.find(ui.select).elements))
    state['reason'] = next(iter(user.find(ui.textarea).elements))
    state['keep'] = next(iter(user.find(ui.checkbox).elements))
    return api, saved, state


def submit(user):
    button = next(b for b in user.find(ui.button).elements if b.props.get('icon') == 'drive_file_move')
    button.mark('move-submit')
    user.find(marker='move-submit').click()


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['aggregations', 'records'])
async def test_move_title_uses_localized_resource_name(user, resource, language):
    _, _, s = await setup_move(user, resource, language)
    expected = {
        ('en', 'aggregations'): 'Move aggregation', ('en', 'records'): 'Move record',
        ('ar', 'aggregations'): 'نقل ملف', ('ar', 'records'): 'نقل وثيقة',
    }[language, resource]
    title = next(e for e in s['dialog'].descendants()
                 if isinstance(e, ui.label) and 'text-xl' in e.classes)
    assert title.text.replace('\u2068', '').replace('\u2069', '') == expected
    if resource == 'records':
        with user:
            s['destination'].set_options({8: 'Destination'}, value=8)
        await asyncio.sleep(.1)
        labels = [e.text for e in s['dialog'].descendants() if isinstance(e, ui.label)]
        assert not any('Subtree:' in text or 'الشجرة الفرعية' in text for text in labels)


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('aggregations,records', [(0, 0), (2, 3), (7, 11)])
async def test_move_preview_displays_backend_subtree_counts(user, language, aggregations, records):
    api, _, s = await setup_move(user, 'aggregations', language)
    api.acl_move_preview.return_value['affected_subtree'] = {
        'affected_aggregation_count': aggregations, 'affected_record_count': records}
    with user:
        s['destination'].set_options({8: 'Destination'}, value=8)
    await asyncio.sleep(.1)
    key = 'webui.refresh_preview.label.subtree_get_aggregations_get_2_records_e9a4c3b8'
    template = AR[key] if language == 'ar' else 'Subtree: {get} aggregations · {get_2} records'
    expected = template.format(get=aggregations, get_2=records)
    assert expected in [e.text.replace('\u2068', '').replace('\u2069', '')
                        for e in s['dialog'].descendants() if isinstance(e, ui.label)]


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['aggregations', 'records'])
async def test_dialog_opens_and_empty_search_can_recover(user, resource, language):
    api, saved, s = await setup_move(user, resource, language)
    control = s['destination']
    assert control.enabled and not control.options
    api.relationship_page.assert_not_awaited()
    hint = next(e for e in s['dialog'].descendants() if isinstance(e, ui.label) and 'text-amber-800' in e.classes)
    assert not hint.visible
    with user:
        await s['load']('no match')
    assert hint.visible and control.enabled
    api.relationship_page.assert_awaited_once_with(
        'aggregations', ('aggregation_number', 'title'), 'no match',
        limit=25, filters=None, eligible_classifications=False)
    api.relationship_page.return_value = {'items': [
        {'id': 7, 'aggregation_number': 'SELF', 'medium': 'physical'},
        {'id': 8, 'aggregation_number': 'PHYSICAL', 'medium': 'physical'},
        {'id': 9, 'aggregation_number': 'DIGITAL', 'medium': 'digital'},
        {'id': 10, 'aggregation_number': 'MIXED', 'medium': 'mixed'},
    ]}
    with user:
        await s['load']('destination')
    assert set(control.options) == ({8} if resource == 'aggregations' else {7, 8, 10})
    assert not hint.visible
    with user:
        control.value = 8
    await asyncio.sleep(.1)
    api.relationship_page.return_value = {'items': []}
    with user:
        await s['load']('different search')
    assert control.value == 8 and 8 in control.options and not hint.visible
    api.move_with_acl.assert_not_awaited()
    saved.assert_not_awaited()


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['aggregations', 'records'])
@pytest.mark.parametrize('keep', [False, True])
@pytest.mark.parametrize('ownership', [False, True])
async def test_move_requires_destination_reason_preview_and_preserves_payload(user, resource, language, keep, ownership):
    api, saved, s = await setup_move(user, resource, language)
    submit(user)
    await asyncio.sleep(.1)
    api.move_with_acl.assert_not_awaited()
    api.acl_move_preview.return_value['ownership_changes'] = ownership
    with user:
        s['destination'].set_options({8: 'Destination'}, value=8)
    await asyncio.sleep(.1)
    submit(user)
    await asyncio.sleep(.1)
    api.move_with_acl.assert_not_awaited()
    with user:
        s['keep'].value = keep
        s['reason'].value = '  Approved move  '
    await asyncio.sleep(.1)
    api.acl_move_preview.assert_awaited_with(resource, 7, 8, keep_current_access_as_override=keep)
    submit(user)
    await asyncio.sleep(.1)
    api.move_with_acl.assert_awaited_once_with(resource, 7, {
        'destination_aggregation_id': 8, 'resource_version': 4,
        'keep_current_access_as_override': keep,
        'confirm_ownership_change': ownership, 'reason': 'Approved move'})
    saved.assert_awaited_once_with({'id': 7, 'version': 5})
    assert not s['dialog'].value


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['aggregations', 'records'])
@pytest.mark.parametrize('failure', ['preview', 'write'])
async def test_denied_preview_or_conflicting_write_keeps_dialog_and_data(user, resource, language, failure):
    api, saved, s = await setup_move(user, resource, language)
    if failure == 'preview':
        api.acl_move_preview.side_effect = ApiError(403, 'Denied')
    else:
        api.move_with_acl.side_effect = ApiError(409, 'Conflict')
    with user:
        s['destination'].set_options({8: 'Destination'}, value=8)
        s['reason'].value = 'Reason retained'
    await asyncio.sleep(.1)
    submit(user)
    await asyncio.sleep(.1)
    assert s['dialog'].value and s['reason'].value == 'Reason retained'
    assert api.move_with_acl.await_count == (0 if failure == 'preview' else 1)
    saved.assert_not_awaited()


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['aggregations', 'records'])
async def test_cancel_ignores_late_destination_results_and_never_moves(user, resource, language):
    api, saved, s = await setup_move(user, resource, language)
    started, release = asyncio.Event(), asyncio.Event()
    async def pending(*args, **kwargs):
        started.set()
        await release.wait()
        return {'items': [{'id': 8, 'title': 'Late destination', 'medium': 'physical'}]}
    api.relationship_page.side_effect = pending
    with user:
        task = asyncio.create_task(s['load']('late'))
    await started.wait()
    with user:
        s['dialog'].close()
    release.set()
    await task
    assert not s['destination'].options
    api.move_with_acl.assert_not_awaited()
    saved.assert_not_awaited()
