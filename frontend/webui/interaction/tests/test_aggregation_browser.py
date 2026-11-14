"""Real NiceGUI events for the full-width browser; bounded fake API, no database."""
from frontend.webui.personal_resources import PersonalResourceState
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing import User
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
from frontend.webui.aggregation_browser import build_aggregation_browser
from frontend.webui.aggregation_state import new_aggregation_state


class Api:
    def __init__(self):
        self.calls = []
        self.name = 'Meeting files'
        self.block = None
        self.fail = False

    async def browse_schemes(self):
        return [dict(id=1, code='SA', title='Scheme')]

    async def browse_page(self, path, **params):
        self.calls.append((path, params.copy()))
        if self.block:
            await self.block.wait()
        if self.fail:
            raise ApiError(500, 'Unavailable')
        if path == 'classification-schemes/1/roots':
            rows = [dict(id=1, code='1111', title='Meetings', is_terminal=True)]
        elif path == 'classifications/1/aggregations':
            rows = [dict(id=i, title=self.name if i == 1 else f'File {i}', aggregation_number=f'A-{i}',
                         child_aggregation_count=0, record_count=1) for i in range(1, 28)]
        elif path == 'aggregations/1/records':
            rows = [dict(id=10, title='Minutes', record_number='R-1', digital_component_count=1)]
        else:
            rows = []
        offset = int(params.get('cursor') or 0)
        return dict(items=rows[offset:offset+25], total=len(rows), next_cursor=str(offset+25) if offset+25<len(rows) else None)


async def setup(user, direction='ltr'):
    api=Api(); state={'resource':'aggregations'}; opened=[]; aggregation_state=new_aggregation_state()
    async def destination(kind,item):
        opened.append((kind,item['id'])); state['resource']=kind
    namespace={}
    @ui.page('/aggregation-test')
    async def page():
        state['resource']='aggregations'
        namespace.update(current_direction={"value":direction},Any=Any,asyncio=asyncio,ui=ui,api=api,state=state,personal=PersonalResourceState(),
            auth_state={'principal':{'global_privileges':[]}},render_message=render_message,
            ApiError=ApiError,error_message=str,can_add_from_collection=lambda *_:False,
            set_aggregation_mode_controls=lambda *_:None,bind_remote_scheme_select=lambda *_:None,
            tree_expander_icon=lambda expanded:'expand_more' if expanded else 'chevron_left' if direction=='rtl' else 'chevron_right',
            page_client=SimpleNamespace(run_javascript=AsyncMock(return_value={'page':0,'tree':70})),
            open_aggregation=lambda item:destination('aggregation-details',item),
            show_record_details=lambda item:destination('record-details',item))
        for name in ('search_bar','guidance','add_button','add_record_button','aggregation_search_mode','aggregation_browse_mode'):
            namespace[name]=ui.label('')
        namespace['table_container']=ui.column()
        import inspect
        namespace.update(aggregation_state=aggregation_state,get_resource=lambda:state['resource'],principal=lambda:namespace['auth_state']['principal'],render_table=lambda *_:None)
        _,open_browser,_=build_aggregation_browser(**{name:namespace[name] for name in inspect.signature(build_aggregation_browser).parameters})
        await open_browser()
        state['aggregation_browse']=aggregation_state['aggregation_browse']
    await user.open('/aggregation-test')
    return api,state,opened


def button(user, *, title=None, icon=None):
    candidates=[b for b in user.find(ui.button).elements
                if (icon is None or b.props.get('icon')==icon)
                and (title is None or (b.props.get('aria-label')==title if icon else any(getattr(e,'text',None)==title for e in b.descendants())))]
    selected=min(candidates,key=lambda b:b.id)
    selected.mark(f'button-{selected.id}')
    return user.find(marker=f'button-{selected.id}')


@pytest.mark.parametrize('direction,chevron',[('ltr','chevron_right'),('rtl','chevron_left')])
async def test_titles_navigate_and_disclosures_only_expand(user:User,direction,chevron):
    api,state,opened=await setup(user,direction)
    button(user,title='Meetings',icon=chevron).click()
    await user.should_see('Meeting files')
    assert not opened
    button(user,title='Meeting files',icon=chevron).click()
    await user.should_see('Minutes')
    assert not opened
    button(user,title='Minutes').click()
    await asyncio.sleep(.05)
    assert opened==[('record-details',10)]
    assert not any('summary' in path or 'retention' in path for path,_ in api.calls)
    assert state['aggregation_browse']['scroll']['tree']==70


async def test_return_reloads_pages_and_preserves_expansion(user:User):
    api,state,opened=await setup(user)
    button(user,title='Meetings').click()
    await user.should_see('Meeting files')
    button(user,icon='expand_more') # classification is expanded
    more=[b for b in user.find(ui.button).elements if b.props.get('icon')=='more_horiz']
    assert more
    more[0].mark('more');user.find(marker='more').click()
    await user.should_see('File 27')
    button(user,title='Meeting files').click()
    await asyncio.sleep(.05)
    assert opened==[('aggregation-details',1)]
    api.name='Updated title'
    await user.open('/aggregation-test')
    await user.should_see('Updated title')
    await user.should_see('File 27')
    assert opened==[('aggregation-details',1)]
    assert ('classification',1) in state['aggregation_browse']['expanded']
    assert [p['cursor'] for path,p in api.calls if path=='classifications/1/aggregations']==[None,'25',None,'25']


async def test_abandoned_branch_response_does_not_update_browser(user:User):
    api,state,_=await setup(user)
    api.block=asyncio.Event()
    button(user,title='Meetings').click()
    await asyncio.sleep(.05)
    state['resource']='dashboard'
    api.block.set()
    await asyncio.sleep(.05)
    branch=state['aggregation_browse']['collections']['classification:1:aggregations']
    assert branch['items']==[]
