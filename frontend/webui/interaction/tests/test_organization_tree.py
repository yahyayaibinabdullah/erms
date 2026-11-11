"""Real NiceGUI browser events with bounded fake API data; no database access."""
import inspect
from frontend.webui import organization_browser
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing import User

from frontend.webui.api_client import ApiError
from frontend.webui.capabilities import can_open_organization_detail
from frontend.webui.i18n_catalogue import render_message

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
def isolated_browser_storage(monkeypatch):
    monkeypatch.setattr(organization_browser,'app',SimpleNamespace(storage=SimpleNamespace(user={})))


class Api:
    def __init__(self):
        self.calls = []
        self.name = 'Records Management'
        self.block = None
        self.roots = [dict(id=i, name=f'Root {i}', code=f'R{i}', status='active') for i in range(1, 28)]

    async def organization_roots(self, **params):
        self.calls.append(('roots', params))
        offset = params.get('offset', 0)
        return self.roots[offset:offset + params['limit']]

    async def organization_children(self, entity_id, **params):
        self.calls.append(('children', entity_id, params.copy()))
        if self.block:
            await self.block.wait()
        rows = [dict(id=100+i, name=self.name if i == 1 else f'Unit {i}', code=f'U{i}', status='active') for i in range(1, 29)] if entity_id == 1 else []
        offset = params['unit_offset']
        roles = [dict(id=10, name='Records Manager', code='RM-MGR', status='active')]
        return dict(org_units=rows[offset:offset + params['limit']],
                    roles=roles[params['role_offset']:][:params['limit']] if entity_id == 1 and offset+params['limit'] >= len(rows) else [],
                    more_org_units=offset+params['limit'] < len(rows),
                    more_roles=entity_id == 1 and offset+params['limit'] < len(rows))

    async def organization_role_users(self, entity_id, **params):
        self.calls.append(('users', entity_id, params))
        return [dict(id=7, name='أميرة المنصوري', email='amira@example.test', status='active',
                     role_id=entity_id, assignment_id=70)]

    async def search_organization(self, query, **params):
        self.calls.append(('search', query, params))
        return [dict(id=7, name='أميرة المنصوري', type='user', role_id=10,
                     assignment_id=70, org_unit_path=[1], status='active')]

    async def organization_summary(self, *args):
        self.calls.append(('summary', args))
        return dict(id=1, name='Root 1', code='R1', status='active')


async def setup(user, *, direction='ltr', privileges=None, saved=None, selector=False, on_selection=None):
    api = Api()
    storage = {'organization_browser_state': saved or {}}
    state = {}
    opened = []
    async def destination(kind, entity_id):
        opened.append((kind, entity_id))
        state['resource'] = kind
    @ui.page('/organization-test')
    async def page():
        namespace = dict(Any=Any, Callable=Callable, asyncio=asyncio, ui=ui, api=api,
                         app=SimpleNamespace(storage=SimpleNamespace(user=storage)), state=state,
                         render_message=render_message, ApiError=ApiError,
                         can_open_organization_detail=can_open_organization_detail,
                         auth_state={'principal': {'global_privileges': privileges if privileges is not None else ['organization.administer', 'identity.users.administer']}},
                         register_navigation=lambda *args: None, show_authenticated_view=lambda: None,
                         page_client=SimpleNamespace(run_javascript=AsyncMock()),
                         tree_expander_icon=lambda expanded: 'expand_more' if expanded else 'chevron_left' if direction=='rtl' else 'chevron_right',
                         localized_lifecycle_value=str, localized_account_type=str,
                         entity_metadata_label=str, format_timestamp=str,
                         render_user_avatar=lambda *args, **kwargs: None,
                         error_message=str,
                         select_user_details=lambda i: destination('user',i),
                         select_role_details=lambda i: destination('role',i),
                         select_organization_unit_details=lambda i: destination('org_unit',i))
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','guidance','title','subtitle'):
            namespace[name] = ui.label('')
        namespace['table_container'] = ui.column()
        organization_browser.app.storage.user=storage
        namespace.update(current_page=lambda:state.get('resource'),
            get_principal=lambda:namespace['auth_state'].get('principal'),
            enter_organization_browser=lambda:state.update(resource='organization-browser',rows=[],searched=True,aggregation_detail=None))
        factory=organization_browser.build_organization_browser
        namespace['show_organization_structure']=factory(**{key:namespace[key] for key in inspect.signature(factory).parameters})
        await namespace['show_organization_structure'](selection_mode=selector if isinstance(selector,str) else 'org_unit' if selector else None, on_selection=on_selection)
    await user.open('/organization-test')
    return api, storage, state, opened


def button(user, label):
    choices = [b for b in user.find(ui.button).elements if 'organization-browser-disclosure' not in b.classes and (b.props.get('aria-label') == label or b.text == label)]
    assert choices, label
    b = min(choices, key=lambda e:e.id)
    b.mark(f'org-{b.id}')
    return user.find(marker=f'org-{b.id}')


def expander(user, code):
    b = next(b for b in user.find(ui.button).elements if 'organization-browser-disclosure' in b.classes and b.props['aria-label'].startswith(f'{code} ·'))
    b.mark(f'org-{b.id}')
    return user.find(marker=f'org-{b.id}')


@pytest.mark.parametrize('target,expected',[('U1 · Records Management',('org_unit',101)),('RM-MGR · Records Manager',('role',10)),('أميرة المنصوري',('user',7))])
async def test_nodes_open_existing_destinations_without_summary_reads(user: User, target, expected):
    api, storage, _, opened = await setup(user, saved={'expanded':['org_unit:1','role:10'], 'branch_counts':{'org_unit:1':29}})
    button(user,target).click()
    await asyncio.sleep(.08)
    assert opened == [expected]
    assert not any(c[0]=='summary' for c in api.calls)
    assert storage['organization_browser_state']['expanded'] == ['org_unit:1','role:10']
    assert not any('grow min-w-0 h-full overflow-y-auto' in str(e.classes) for e in user.find(ui.column).elements)


@pytest.mark.parametrize('direction,icon',[('ltr','chevron_right'),('rtl','chevron_left')])
async def test_disclosure_is_separate_and_direction_aware(user: User,direction,icon):
    _,_,_,opened=await setup(user,direction=direction)
    b=next(b for b in user.find(ui.button).elements if 'organization-browser-disclosure' in b.classes)
    assert b.props['icon']==icon and b.props['aria-expanded']=='false'
    expander(user,'R1').click()
    await user.should_see('Records Management')
    assert not opened
    assert any(b.props.get('icon')=='expand_more' and b.props.get('aria-expanded')=='true' for b in user.find(ui.button).elements)


async def test_browse_only_cannot_open_detail_pages(user: User):
    _,_,_,opened=await setup(user,privileges=['organization.browse'])
    assert not any(b.props.get('aria-label')=='R1 · Root 1' and 'organization-browser-disclosure' not in b.classes for b in user.find(ui.button).elements)
    expander(user,'R1').click()
    await user.should_see('Records Management')
    assert not opened


async def test_branch_pages_are_restored_on_return_and_freshly_read(user: User):
    api,storage,_,_=await setup(user,saved={'expanded':['org_unit:1'],'branch_counts':{'org_unit:1':29}})
    await user.should_see('Unit 28')
    assert [c[2]['unit_offset'] for c in api.calls if c[0]=='children']==[0,25]
    button(user,'U28 · Unit 28').click()
    await asyncio.sleep(.05)
    assert storage['organization_browser_state']['branch_counts']['org_unit:1']==29
    api.name='Fresh translated unit'
    await user.open('/organization-test')
    await user.should_see('Fresh translated unit')
    await user.should_see('Unit 28')


async def test_abandoned_read_cannot_render_into_new_page(user: User):
    api,_,state,_=await setup(user)
    api.block=asyncio.Event()
    expander(user,'R1').click()
    await asyncio.sleep(.03)
    state['resource']='dashboard'
    api.block.set()
    await asyncio.sleep(.08)
    await user.should_not_see('Records Management')


async def test_selector_retains_summary_and_does_not_navigate(user: User):
    api,_,_,opened=await setup(user,selector=True)
    button(user,'R1 · Root 1').click()
    await asyncio.sleep(.08)
    assert any(c[0]=='summary' for c in api.calls)
    assert not opened


async def test_root_pages_are_restored_without_unbounded_download(user: User):
    api,_,_,_=await setup(user,saved={'root_count':27})
    await user.should_see('Root 27')
    assert [(c[1].get('offset',0),c[1]['limit']) for c in api.calls if c[0]=='roots']==[(0,26),(25,26)]


async def test_refresh_updates_names_without_detail_requests(user: User):
    api,_,_,_=await setup(user,saved={'expanded':['org_unit:1']})
    api.name='Renamed unit'
    button(user,render_message('webui.show_organization_structure.button.refresh_7f802034')).click()
    await user.should_see('Renamed unit')
    assert not any(c[0]=='summary' for c in api.calls)


async def test_search_result_opens_exact_user_occurrence_and_retains_query(user: User):
    api,storage,_,opened=await setup(user,saved={'query':'أميرة'})
    await user.should_see('أميرة المنصوري')
    button(user,'أميرة المنصوري').click()
    await asyncio.sleep(.08)
    assert opened==[('user',7)]
    saved=storage['organization_browser_state']
    assert saved['query']=='أميرة'
    assert saved['selected']['assignment_id']==70
    assert saved['expanded']==['org_unit:1','role:10']
    assert not any(c[0]=='summary' for c in api.calls)


@pytest.mark.parametrize('direction', ['ltr', 'rtl'])
async def test_roles_follow_last_unit_page(user: User, direction):
    api, _, _, _ = await setup(user, direction=direction, saved={'expanded': ['org_unit:1']})
    await user.should_see('Unit 25')
    await user.should_not_see('Records Manager')
    button(user, render_message('webui.render_collection.button.load_more_755f4879')).click()
    await user.should_see('Records Manager')
    labels = [b.props.get('aria-label') for b in sorted(user.find(ui.button).elements, key=lambda b: b.id)
              if 'organization-browser-content' in b.classes]
    assert labels.index('U28 · Unit 28') < labels.index('RM-MGR · Records Manager')
    calls = [call[2] for call in api.calls if call[0] == 'children']
    assert [(call['unit_offset'], call['role_offset']) for call in calls] == [(0, 0), (25, 0)]


@pytest.mark.parametrize("target,kind", [("R1 · Root 1","org_unit"),("RM-MGR · Records Manager","role"),("أميرة المنصوري","user")])
async def test_mixed_selector_accepts_all_entity_types(user: User, target, kind):
    selected=[]
    async def choose(node):
        selected.append(node)
        return True
    await setup(user,selector="all",on_selection=choose)
    if kind != "org_unit":
        expander(user,"R1").click()
        await asyncio.sleep(.08)
        button(user,render_message('webui.render_collection.button.load_more_755f4879')).click()
        await asyncio.sleep(.08)
    if kind == "user":
        expander(user,"RM-MGR").click()
        await asyncio.sleep(.08)
    button(user,target).click()
    await asyncio.sleep(.08)
    button(user,render_message('webui.show_organization_structure.button.select_replace_cf383c4d',replace=render_message('messaging.field.recipient'))).click()
    await asyncio.sleep(.08)
    assert selected[0]['type'] == kind
