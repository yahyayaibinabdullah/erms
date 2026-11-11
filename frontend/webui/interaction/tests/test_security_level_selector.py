"""Exercise the actual selector binding without a persistent database."""
import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from nicegui import ui, background_tasks
from nicegui.testing import User
from frontend.webui.entity_selectors import relationship_options
from frontend.webui.relationship_select import relationship_select
from frontend.webui.entity_selectors import relationship_search_query
from frontend.webui.security_level_controls import build_security_selector
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain, set_active_messages

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).parents[2]



class Api:
    def __init__(self):
        self.ceiling = 50
        self.calls = []
        self.gate = None
        self.rows = [dict(id=i+1, code=code, name=code, level_number=number)
                     for i, (code, number) in enumerate([('G', 0), ('R', 50), ('S', 75), ('TS', 100)])]

    async def administration_reference_page(self, resource, **params):
        self.calls.append(params)
        maximum = min(self.ceiling, 0 if params['filters']['parent_aggregation_id'] == 1 else 100)
        if self.gate:
            await self.gate.wait()
        return dict(items=[r for r in self.rows if r['level_number'] <= maximum],
                    maximum_level=maximum, minimum_level=None)

    async def get(self, resource, identity):
        return self.rows[identity-1]


async def setup(user, language):
    api = Api()
    scope = dict(ui=ui, api=api, Any=Any, Callable=Callable, asyncio=asyncio, json=json,
                 background_tasks=background_tasks, ApiError=ApiError, error_message=str,
                 render_message_plain=render_message_plain, relationship_options=relationship_options,
                 relationship_search_query=relationship_search_query)
    scope['bind_resource_security_select'] = build_security_selector(api,error_message=str)
    @ui.page('/security-selector')
    def page():
        translations = {r['message_key']: r['translated_text'] for r in
                        json.loads((ROOT / 'i18n/messages.ar.generated.json').read_text())['items']}
        set_active_messages(translations if language == 'ar' else {})
        scope['parent'] = ui.select({1: 'General parent', 2: 'Top secret parent'}, value=2)
        scope['control'] = relationship_select('Security level', {1: 'G', 2: 'R', 3: 'S'}, value=3)
        scope['load'] = scope['bind_resource_security_select'](scope['control'], parent_control=scope['parent'])
    await user.open('/security-selector')
    await asyncio.sleep(.05)
    return api, scope


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_constraints_refresh_and_clear_invalid_selection(user: User, language):
    api, scope = await setup(user, language)
    control = scope['control']
    assert set(control.options) == {1, 2}
    assert control.value is None  # Old S selection exceeds clearance.
    assert any(('أدوارك' if language == 'ar' else 'effective-role') in element.text
               for element in user.find(ui.label).elements)
    control.value = 2
    scope['parent'].value = 1
    await asyncio.sleep(.05)
    assert set(control.options) == {1}
    assert control.value is None
    scope['parent'].value = 2
    await asyncio.sleep(.05)
    assert set(control.options) == {1, 2}
    api.ceiling = 0
    await scope['load']()
    assert set(control.options) == {1}
    assert all(call['limit'] == 25 and call['filters']['assignable'] for call in api.calls)


async def test_old_response_cannot_restore_previous_parent_choices(user: User):
    api, scope = await setup(user, 'en')
    gate = asyncio.Event()
    api.gate = gate
    old = asyncio.create_task(scope['load']())
    await asyncio.sleep(.01)
    api.gate = None
    scope['parent'].value = 1
    await asyncio.sleep(.05)
    assert set(scope['control'].options) == {1}
    gate.set()
    await old
    assert set(scope['control'].options) == {1}
    scope['control'].delete()
    await scope['load']()  # Abandoned controls are never updated.


async def test_old_api_response_cannot_expose_unfiltered_choices(user: User):
    api, scope = await setup(user, 'en')
    async def old_page(*args, **kwargs):
        return {'items': api.rows, 'total': len(api.rows)}
    api.administration_reference_page = old_page
    await scope['load']()
    assert scope['control'].options == {}
    assert scope['control'].value is None
