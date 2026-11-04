"""Render the real dashboard across identity and cache boundaries, without a database."""
import ast
import asyncio
import copy
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import Client, ui
from frontend.webui import app as webui
from frontend.webui.i18n_catalogue import clear_active_messages, set_active_messages

SOURCE = ast.parse((Path(__file__).parents[2] / 'app.py').read_text())


def load(name, scope):
    node = next(n for n in ast.walk(SOURCE)
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<dashboard-identity>','exec'),scope)
    return scope[name]


def summary(identity):
    count = 12 if identity==1 else 0
    return dict(
        application_configuration=dict(DASHBOARD_RECENT_ITEM_LIMIT=3,DASHBOARD_RECENT_DAYS=14,
            DASHBOARD_FAVOURITE_ITEM_LIMIT=2,DASHBOARD_REVIEW_PREVIEW_LIMIT=2,
            DEFAULT_WORKING_TIMEZONE='UTC',REVIEW_WARNING_WINDOW_DAYS=3),
        overview_counts={'aggregations':count,'records':count},
        overview_medium_counts={kind:dict(physical=count,digital=0,mixed=0) for kind in ('aggregations','records')},
        overview_resource_attention_counts={kind:dict(vital=0,held=0) for kind in ('aggregations','records')},
        overview_aggregation_status_counts=dict(open=count,closed=0),
        overview_digital_component_metrics=dict(component_count=0,storage_size_in_bytes=0),
        classification_metrics={key:0 for key in ('published_scheme_count','draft_scheme_count',
            'inactive_scheme_count','branch_count','terminal_count','assignable_terminal_count',
            'draft_terminal_count','inactive_classification_count')},
        unclassified_root_count=0,ownership_counts=[],
        favourites={'records':[],'aggregations':[
            dict(id=99,title='USER A PRIVATE FAVOURITE',aggregation_number='A-99',parent_aggregation_id=None)
        ] if identity==1 else []},
        recent_activity=[dict(entity_type='record',entity_id=88,title='USER A PRIVATE ACTIVITY',
            record_number='A-88',operation='CREATE',occurred_at='2026-11-04T00:00:00Z')] if identity==1 else [],
        review_warning_window_days=3,overdue_review_count=0,upcoming_review_count=0,
        overdue_reviews=[],upcoming_reviews=[])


class DashboardFixture:
    def __init__(self,client):
        self.tasks=[]
        self.state={'localization':{'effective_language':'en','working_timezone':'UTC'}}
        self.auth={'principal':{'user':{'id':1},'global_privileges':[]}}
        self.api=SimpleNamespace(dashboard_summary=AsyncMock(side_effect=self.fetch))
        self.host=ui.column()
        self.scope=dict(vars(webui),state=self.state,auth_state=self.auth,api=self.api,
            page_client=SimpleNamespace(id=client.id,_deleted=False,has_socket_connection=True),
            table_container=self.host,title=SimpleNamespace(text=''),subtitle=SimpleNamespace(text=''),
            guidance=SimpleNamespace(text=''),register_navigation=Mock(),show_authenticated_view=Mock(),
            set_connection_status=Mock(),format_timestamp=lambda v:str(v),
            error_message=lambda e:str(e),
            accept_application_configuration=lambda c:self.state.update(application_configuration=c),
            background_tasks=SimpleNamespace(create=self.schedule))
        for control in ('add_button','add_record_button','search_bar','aggregation_mode_bar'):
            self.scope[control]=Mock()
        for name in ('dashboard_session_key','clear_dashboard_session','select_dashboard'):
            load(name,self.scope)

    async def fetch(self,**kwargs):
        return copy.deepcopy(summary(self.auth['principal']['user']['id']))

    def schedule(self,coroutine):
        task=asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    def labels(self,client):
        return '\n'.join(str(e.text) for e in client.elements.values()
                         if isinstance(e,ui.label) and not e.is_deleted)

    async def close(self):
        for task in self.tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)


@pytest.mark.asyncio
async def test_real_dashboard_a_b_a_and_same_account_login_never_reuse_another_session():
    client=Client(ui.page('/dashboard-identity-regression'),request=None)
    fixture=None
    try:
        with client:
            set_active_messages({})
            fixture=DashboardFixture(client)
            for identity in (1,2,1,1):
                fixture.scope['clear_dashboard_session']()
                fixture.auth['principal']={'user':{'id':identity},'global_privileges':[]}
                await fixture.scope['select_dashboard']()
                labels=fixture.labels(client)
                if identity==1:
                    assert 'USER A PRIVATE FAVOURITE' in labels
                    assert 'USER A PRIVATE ACTIVITY' in labels
                else:
                    assert 'USER A PRIVATE' not in labels
                    assert fixture.state['favourites']=={'aggregations':[],'records':[]}
                assert fixture.state['dashboard_summary_cache_key'][1]==identity
                assert fixture.state['dashboard_summary_cache']['overview_counts']['records']==(12 if identity==1 else 0)
            assert fixture.api.dashboard_summary.await_count==4
    finally:
        if fixture:await fixture.close()
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})


@pytest.mark.asyncio
async def test_real_dashboard_valid_cache_is_immediate_and_refresh_is_single_flight():
    client=Client(ui.page('/dashboard-cache-regression'),request=None)
    fixture=None
    try:
        with client:
            set_active_messages({})
            fixture=DashboardFixture(client)
            await fixture.scope['select_dashboard']()
            release,started=asyncio.Event(),asyncio.Event()
            async def refresh(**kwargs):
                started.set()
                await release.wait()
                return summary(2)  # same user, changed authorized data
            fixture.api.dashboard_summary.side_effect=refresh
            await fixture.scope['select_dashboard']()
            assert 'USER A PRIVATE FAVOURITE' in fixture.labels(client)
            await started.wait()
            assert fixture.api.dashboard_summary.await_count==2
            # Repeated clicks on Refresh while its request is running cannot fan out.
            button=next(e for e in client.elements.values() if isinstance(e,ui.button)
                        and not e.is_deleted and e.props.get('loading'))
            handler=button._event_listeners[next(k for k,v in button._event_listeners.items() if v.type=='click')].handler
            await inspect.getclosurevars(handler).nonlocals['callback']()
            assert fixture.api.dashboard_summary.await_count==2
            assert 'USER A PRIVATE FAVOURITE' in fixture.labels(client)
            release.set()
            await asyncio.gather(*fixture.tasks)
            assert 'USER A PRIVATE' not in fixture.labels(client)
            assert fixture.state['dashboard_summary_cache']['overview_counts']['records']==0
    finally:
        if fixture:await fixture.close()
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})


@pytest.mark.asyncio
async def test_real_dashboard_rejects_unkeyed_or_foreign_cache_before_first_response():
    client=Client(ui.page('/dashboard-foreign-cache-regression'),request=None)
    fixture=None
    try:
        with client:
            set_active_messages({})
            fixture=DashboardFixture(client)
            for old_key in (None,(0,1,'en','UTC'),(0,2,'ar','UTC')):
                fixture.state['dashboard_summary_cache']=summary(1)
                if old_key is None:fixture.state.pop('dashboard_summary_cache_key',None)
                else:fixture.state['dashboard_summary_cache_key']=old_key
                fixture.auth['principal']={'user':{'id':2},'global_privileges':[]}
                release,started=asyncio.Event(),asyncio.Event()
                async def fetch(**kwargs):
                    started.set()
                    await release.wait()
                    return summary(2)
                fixture.api.dashboard_summary.side_effect=fetch
                pending=asyncio.create_task(fixture.scope['select_dashboard']())
                await started.wait()
                assert 'USER A PRIVATE' not in fixture.labels(client)
                assert 'dashboard_summary_cache' not in fixture.state
                release.set()
                await pending
                assert 'USER A PRIVATE' not in fixture.labels(client)
                assert fixture.state['dashboard_summary_cache']['overview_counts']['records']==0
    finally:
        if fixture:await fixture.close()
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})


@pytest.mark.asyncio
async def test_real_dashboard_failed_refresh_retains_own_snapshot_and_restores_refresh_control():
    client=Client(ui.page('/dashboard-refresh-error-regression'),request=None)
    fixture=None
    try:
        with client:
            set_active_messages({})
            fixture=DashboardFixture(client)
            await fixture.scope['select_dashboard']()
            cached=fixture.state['dashboard_summary_cache']
            fixture.api.dashboard_summary.side_effect=webui.ApiError(503,'Temporary fixture outage')
            button=next(e for e in client.elements.values() if isinstance(e,ui.button)
                        and not e.is_deleted and any(v.type=='click' for v in e._event_listeners.values())
                        and str(e.text).endswith('Refresh'))
            handler=next(v.handler for v in button._event_listeners.values() if v.type=='click')
            await inspect.getclosurevars(handler).nonlocals['callback']()
            assert 'USER A PRIVATE FAVOURITE' in fixture.labels(client)
            assert fixture.state['dashboard_summary_cache'] is cached
            assert not button.is_deleted and not button.props.get('loading')
            fixture.scope['set_connection_status'].assert_called_with(False)
    finally:
        if fixture:await fixture.close()
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})
